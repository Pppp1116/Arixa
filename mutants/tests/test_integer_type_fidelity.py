import pytest
from astra.parser import parse
from astra.semantic import analyze, SemanticError
from astra.llvm_codegen import to_llvm_ir
from astra.ast import Program


def emit_llvm_ir(src: str, overflow_mode: str = "trap") -> str:
    """Helper to emit LLVM IR from source code"""
    prog = parse(src)
    analyze(prog)
    return to_llvm_ir(prog, overflow_mode=overflow_mode)


def test_u7_variable_allocation():
    """Test that u7 variables allocate as i7, not i64"""
    src = """
    fn main() u7 {
        x: u7 = 42u7;
        return x;
    }
    """
    ir = emit_llvm_ir(src)
    # Should contain i7 allocation, not i64
    assert "%x = alloca i7" in ir
    assert "define i7 @__astra_user_main()" in ir
    # Should NOT contain i64 allocation
    assert "%x = alloca i64" not in ir


def test_i13_function_parameter():
    """Test that i13 function parameters use i13 type"""
    src = """
    fn test_func(x: i13) i13 {
        return x + 1i13;
    }
    """
    ir = emit_llvm_ir(src)
    # Should contain i13 parameter type
    assert "define i13 @test_func(i13" in ir
    # Should NOT contain i64 parameter
    assert "define i64 @test_func" not in ir


def test_u23_arithmetic_preserves_type():
    """Test that u23 arithmetic preserves exact type"""
    src = """
    fn test(a: u23, b: u23) u23 {
        return a + b;
    }
    """
    ir = emit_llvm_ir(src)
    # Should contain u23 (i23) arithmetic
    assert "define i23 @test(i23" in ir
    # Function should work with i23 types
    assert "add i23" in ir or "call" in ir  # Either direct add or overflow intrinsic call


def test_u99_constant_literal():
    """Test that u99 constants emit as i99"""
    src = """
    fn test() u99 {
        return 300u99;
    }
    """
    ir = emit_llvm_ir(src)
    # Should contain i99 type
    assert "define i99 @test()" in ir
    # Should contain i99 constant
    assert "i99 300" in ir


def test_constant_range_validation():
    """Test that out-of-range literals are caught at compile time"""
    # u8 should reject 300
    with pytest.raises(SemanticError, match="literal 300 out of range for u8"):
        src = """
        fn main() u8 {
            return 300u8;
        }
        """
        prog = parse(src)
        analyze(prog)
    
    # u7 should reject -5
    with pytest.raises(SemanticError, match="literal -5 out of range for u7"):
        src = """
        fn main() u7 {
            return -5u7;
        }
        """
        prog = parse(src)
        analyze(prog)
    
    # i13 should reject 5000 (range is -4096 to 4095)
    with pytest.raises(SemanticError, match="literal 5000 out of range for i13"):
        src = """
        fn main() i13 {
            return 5000i13;
        }
        """
        prog = parse(src)
        analyze(prog)


def test_universal_type_fidelity():
    """Test multiple arbitrary widths in same function"""
    src = """
    fn mixed(a: u7, b: i13, c: u23) u99 {
        x: u7 = a + 1u7;
        y: i13 = b + 2i13;
        z: u23 = c + 3u23;
        return (x as u99) + (y as u99) + (z as u99);
    }
    
    fn main() u99 {
        return mixed(1u7, 2i13, 3u23);
    }
    """
    ir = emit_llvm_ir(src)
    # Each variable should have exact type allocation
    assert "%x = alloca i7" in ir
    assert "%y = alloca i13" in ir  
    assert "%z = alloca i23" in ir
    # Function signature should use exact types
    assert "define i99 @mixed(i7" in ir


def test_universal_overflow_intrinsics():
    """Test overflow intrinsics work for all arbitrary widths in debug mode"""
    test_cases = [
        ("u7", "i7", False),
        ("i13", "i13", True),
        ("u23", "i23", False),
        ("u99", "i99", False),
    ]
    
    for width, llvm_type, signed in test_cases:
        # Test debug mode generates overflow intrinsics
        src = f"""
        fn test(x: {width}) {width} {{
            return x + 1{width};
        }}
        """
        ir = emit_llvm_ir(src, overflow_mode="trap")
        
        # Verify overflow intrinsic is present
        intrinsic = f"@llvm.{'u' if not signed else 's'}add.with.overflow.{llvm_type}"
        assert intrinsic in ir, f"Expected {intrinsic} in IR for {width}"
        
        # Verify conditional branch pattern
        assert "br i1" in ir, f"Expected conditional branch for {width} overflow"
        assert "overflow_trap" in ir, f"Expected overflow trap block for {width}"
        assert "overflow_ok" in ir, f"Expected overflow ok block for {width}"
        assert "call void @llvm.trap()" in ir, f"Expected llvm.trap call for {width}"
        
        # Test release mode generates plain arithmetic
        release_ir = emit_llvm_ir(src, overflow_mode="wrap")
        assert intrinsic not in release_ir, f"Should not have {intrinsic} in release mode for {width}"
        assert f"add {llvm_type}" in release_ir, f"Expected plain add for {width} in release"
        assert "br i1" not in release_ir, f"Should not have conditional branch in release for {width}"


@pytest.mark.parametrize("width", ["u7", "i13", "u23", "u99", "i128", "u64"])
def test_arbitrary_width_basic_operations(width: str):
    """Test basic operations work for arbitrary widths"""
    src = f"""
    fn test(x: {width}, y: {width}) {width} {{
        a: {width} = x + y;
        b: {width} = x - y;
        c: {width} = x * y;
        return a + b + c;
    }}
    """
    # Should parse and analyze without errors
    prog = parse(src)
    analyze(prog)
    
    # Should generate LLVM IR with correct types
    ir = to_llvm_ir(prog)
    llvm_type = "i" + width[1:]  # u7 -> i7, i13 -> i13
    assert f"define {llvm_type} @test({llvm_type}" in ir


def test_cast_between_arbitrary_widths():
    """Test casting between different arbitrary widths"""
    src = """
    fn test(x: u7) u23 {
        y: u23 = x as u23;
        z: i13 = x as i13;
        return y + (z as u23);
    }
    """
    prog = parse(src)
    analyze(prog)
    ir = to_llvm_ir(prog)
    
    # Should preserve exact types throughout
    assert "%x = alloca i7" in ir
    assert "%y = alloca i23" in ir
    assert "%z = alloca i13" in ir
    assert "define i23 @test(i7" in ir


def test_nested_arbitrary_width_structs():
    """Test arbitrary widths in struct contexts"""
    src = """
    struct Point {
        x: u7,
        y: u9,
    }
    
    fn test(p: Point) u16 {
        return (p.x as u16) + (p.y as u16);
    }
    """
    prog = parse(src)
    analyze(prog)
    ir = to_llvm_ir(prog)
    
    # Should handle arbitrary width fields correctly
    assert "define i16 @test" in ir


if __name__ == "__main__":
    pytest.main([__file__])
