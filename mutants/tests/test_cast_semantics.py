"""Test cast semantics to understand current signed/unsigned extension behavior."""

import pytest
from astra.parser import parse
from astra.semantic import analyze, SemanticError
from astra.llvm_codegen import to_llvm_ir


def parse_and_analyze(source):
    """Helper to parse and analyze ASTRA code."""
    prog = parse(source)
    analyze(prog)
    return prog


def test_cast_semantics_widening():
    """Test all widening cast scenarios to understand current behavior."""
    
    # Widening signed→signed (i7→i13)
    prog = parse_and_analyze("""
    fn test_i7_to_i13() i13 {
         x: i7 = -1;
        return x as i13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== i7→i13 LLVM IR ===")
    print(ir)
    assert "sext i7" in ir or "zext i7" in ir
    
    # Widening unsigned→unsigned (u7→u13)
    prog = parse_and_analyze("""
    fn test_u7_to_u13() u13 {
         x: u7 = 127;
        return x as u13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== u7→u13 LLVM IR ===")
    print(ir)
    assert "sext i7" in ir or "zext i7" in ir
    
    # Widening signed→unsigned (i7→u13)
    prog = parse_and_analyze("""
    fn test_i7_to_u13() u13 {
         x: i7 = -1;
        return x as u13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== i7→u13 LLVM IR ===")
    print(ir)
    assert "sext i7" in ir or "zext i7" in ir
    
    # Widening unsigned→signed (u7→i13)
    prog = parse_and_analyze("""
    fn test_u7_to_i13() i13 {
         x: u7 = 127;
        return x as i13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== u7→i13 LLVM IR ===")
    print(ir)
    assert "sext i7" in ir or "zext i7" in ir


def test_cast_semantics_narrowing():
    """Test narrowing cast scenarios."""
    
    # Narrowing explicit casts (i13→i7)
    prog = parse_and_analyze("""
    fn test_i13_to_i7() i7 {
         x: i13 = 100;
        return x as i7;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== i13→i7 LLVM IR ===")
    print(ir)
    assert "trunc i13" in ir


def test_cast_boundary_values():
    """Test critical boundary cases mentioned in the plan."""
    
    # u7(127) as i13 - should zero-extend to 127
    prog = parse_and_analyze("""
    fn test_u7_127_to_i13() i13 {
        return 127u7 as i13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== u7(127) as i13 LLVM IR ===")
    print(ir)
    
    # i7(-1) as u13 - should sign-extend to 8191
    prog = parse_and_analyze("""
    fn test_i7_neg1_to_u13() u13 {
        return -1i7 as u13;
    }
    """)
    ir = to_llvm_ir(prog, filename='test', overflow_mode='trap')
    print("=== i7(-1) as u13 LLVM IR ===")
    print(ir)


def test_implicit_coercion_rejection():
    """Test that implicit coercions are properly rejected."""
    
    # u32 -> u16 should be rejected without explicit cast
    with pytest.raises(SemanticError):
        parse_and_analyze("""
        fn test_u32_to_u16() u16 {
             x: u32 = 1000;
             y: u16 = x;  // Should be rejected
            return y;
        }
        """)
    
    # i32 -> u32 should be rejected without explicit cast
    with pytest.raises(SemanticError):
        parse_and_analyze("""
        fn test_i32_to_u32() u32 {
             x: i32 = -1;
             y: u32 = x;  // Should be rejected
            return y;
        }
        """)


if __name__ == "__main__":
    test_cast_semantics_widening()
    test_cast_semantics_narrowing()
    test_cast_boundary_values()
    test_implicit_coercion_rejection()
    print("All cast semantics tests comped!")
