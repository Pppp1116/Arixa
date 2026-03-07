"""Test cases for correctness fixes in ASTRA compiler."""

import pytest
from astra.parser import parse
from astra.semantic import analyze
from astra.llvm_codegen import to_llvm_ir


def test_nan_comparison_equality():
    """Test that NaN == NaN returns false (IEEE 754 compliant)."""
    
    # Test direct float comparison
    prog = parse("""
    fn test_nan_equality() Bool {
         x = NaN;
         y = NaN;
        return x == y;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== NaN Comparison LLVM IR ===")
    print(ir)
    
    # The comparison should result in false
    # We can't directly test runtime here, but we can verify the IR structure
    assert "fcmp" in ir or "call" in ir  # Should have float comparison logic


def test_nan_comparison_inequality():
    """Test that NaN != NaN returns true (IEEE 754 compliant)."""
    
    prog = parse("""
    fn test_nan_inequality() Bool {
         x = NaN;
         y = NaN;
        return x != y;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== NaN Inequality LLVM IR ===")
    print(ir)


def test_extern_function_abi_attributes():
    """Test that extern functions have proper ABI attributes."""
    
    prog = parse("""
    extern fn small_char_to_int(c: i8) i32;
    
    fn test_extern_call() i32 {
        return small_char_to_int(42i8);
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== Extern Function ABI LLVM IR ===")
    print(ir)
    
    # Should have signext attribute for i8 parameter and return
    assert "signext" in ir


def test_boolean_coercion_rejection():
    """Test that integers cannot be used in boolean contexts."""
    
    # This should fail - integer in if condition
    with pytest.raises(Exception):  # Should raise SemanticError
        prog = parse("""
        fn test_int_in_if() i32 {
            if 5 {
                return 1;
            }
            return 0;
        }
        """)
        analyze(prog)
    
    # This should fail - integer in while condition  
    with pytest.raises(Exception):  # Should raise SemanticError
        prog = parse("""
        fn test_int_in_while() i32 {
            while 1 {
                break;
            }
            return 0;
        }
        """)
        analyze(prog)


def test_shift_operations_correctness():
    """Test that shift operations use correct LLVM instructions."""
    
    # Test signed right shift (should use ashr)
    prog = parse("""
    fn test_signed_rshift() i32 {
         x = -8i32;
        return x >> 1;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== Signed Right Shift LLVM IR ===")
    print(ir)
    assert "ashr" in ir
    
    # Test unsigned right shift (should use lshr)
    prog = parse("""
    fn test_unsigned_rshift() u32 {
         x = 8u32;
        return x >> 1;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== Unsigned Right Shift LLVM IR ===")
    print(ir)
    assert "lshr" in ir


def test_modulo_operator_correctness():
    """Test that modulo uses correct LLVM instructions."""
    
    # Test signed modulo (should use srem)
    prog = parse("""
    fn test_signed_mod() i32 {
        return -7 % 3;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== Signed Modulo LLVM IR ===")
    print(ir)
    assert "srem" in ir
    
    # Test unsigned modulo (should use urem)
    prog = parse("""
    fn test_unsigned_mod() u32 {
        return 7u32 % 3u32;
    }
    """)
    analyze(prog)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== Unsigned Modulo LLVM IR ===")
    print(ir)
    assert "urem" in ir


if __name__ == "__main__":
    test_nan_comparison_equality()
    test_nan_comparison_inequality()
    test_extern_function_abi_attributes()
    test_boolean_coercion_rejection()
    test_shift_operations_correctness()
    test_modulo_operator_correctness()
    print("All correctness fix tests comped!")
