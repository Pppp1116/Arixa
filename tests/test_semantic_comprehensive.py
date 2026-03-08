"""Comprehensive semantic analysis tests for ASTRA language.

Tests all semantic analysis functionality including:
- Type checking and inference
- Scope resolution
- Ownership and borrowing analysis
- Memory safety checks
- Function resolution
- Error detection
- Performance tests
"""

import pytest
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


class TestTypeChecking:
    """Test type checking and inference."""
    
    def test_basic_type_inference(self):
        """Test basic type inference for literals."""
        src = """
        fn main() Int {
            let x = 42;  // Should infer Int
            let y = 3.14;  // Should infer Float
            let z = "hello";  // Should infer String
            return x;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_type_annotation_verification(self):
        """Test type annotation verification."""
        src = """
        fn main() Int {
            let x: Int = 42;  // Correct type
            let y: String = "hello";  // Correct type
            return x;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_type_mismatch_error(self):
        """Test type mismatch error detection."""
        src = """
        fn main() Int {
            let x: Int = "hello";  // Type mismatch
            return x;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "type" in str(exc_info.value).lower()
    
    def test_function_parameter_types(self):
        """Test function parameter type checking."""
        src = """
        fn add(a: Int, b: Int) Int {
            return a + b;
        }
        
        fn main() Int {
            return add(1, 2);  // Correct types
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_function_return_type_checking(self):
        """Test function return type checking."""
        src = """
        fn get_number() Int {
            return 42;  // Correct return type
        }
        
        fn main() Int {
            return get_number();
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_function_return_type_error(self):
        """Test function return type error detection."""
        src = """
        fn get_number() Int {
            return "hello";  // Wrong return type
        }
        
        fn main() Int {
            return get_number();
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "return type" in str(exc_info.value).lower()
    
    def test_binary_operation_types(self):
        """Test binary operation type checking."""
        src = """
        fn main() Int {
            let x = 1 + 2;  // Int + Int
            let y = 3.14 * 2.0;  // Float * Float
            return x;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_binary_operation_type_error(self):
        """Test binary operation type error detection."""
        src = """
        fn main() Int {
            let x = 1 + "hello";  // Int + String - error
            return x;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "type" in str(exc_info.value).lower()
    
    def test_cast_expressions(self):
        """Test cast expression type checking."""
        src = """
        fn main() Int {
            let x = 42;
            let y = x as Float;  // Valid cast
            let z = y as Int;  // Valid cast
            return z;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors


class TestScopeResolution:
    """Test scope resolution and name binding."""
    
    def test_local_variable_scope(self):
        """Test local variable scope resolution."""
        src = """
        fn main() Int {
            let x = 42;
            {
                let y = x + 1;  // x is accessible
                return y;
            }
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_variable_shadowing(self):
        """Test variable shadowing."""
        src = """
        fn main() Int {
            let x = 42;
            {
                let x = 24;  // Shadows outer x
                return x;
            }
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_undefined_variable_error(self):
        """Test undefined variable error detection."""
        src = """
        fn main() Int {
            return undefined_var;  // Undefined variable
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "undefined" in str(exc_info.value).lower() or "not defined" in str(exc_info.value).lower()
    
    def test_function_scope(self):
        """Test function scope resolution."""
        src = """
        fn helper() Int {
            return 42;
        }
        
        fn main() Int {
            return helper();  // Function is accessible
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_recursive_function(self):
        """Test recursive function calls."""
        src = """
        fn factorial(n: Int) Int {
            if n <= 1 {
                return 1;
            } else {
                return n * factorial(n - 1);  # Recursive call
            }
        }
        
        fn main() Int {
            return factorial(5);
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_mutability_checking(self):
        """Test mutability checking."""
        src = """
        fn main() Int {
            let x = 42;  // Immutable
            // x = 24;  // This would be an error
            let mut y = 42;  // Mutable
            y = 24;  // This is allowed
            return y;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_mutability_error(self):
        """Test mutability error detection."""
        src = """
        fn main() Int {
            let x = 42;  // Immutable
            x = 24;  // Error: cannot assign to immutable
            return x;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "immutable" in str(exc_info.value).lower() or "mut" in str(exc_info.value).lower()


class TestOwnershipAndBorrowing:
    """Test ownership and borrowing analysis."""
    
    def test_basic_ownership(self):
        """Test basic ownership semantics."""
        src = """
        fn main() Int {
            let x = 42;
            let y = x;  // x is moved
            return y;  // OK
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_use_after_move_error(self):
        """Test use-after-move error detection."""
        src = """
        fn main() Int {
            let x = 42;
            let y = x;  // x is moved
            return x;  // Error: use after move
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "move" in str(exc_info.value).lower()
    
    def test_immutable_borrowing(self):
        """Test immutable borrowing."""
        src = """
        fn main() Int {
            let x = 42;
            let r = &x;  // Immutable borrow
            return *r;  // OK
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_mutable_borrowing(self):
        """Test mutable borrowing."""
        src = """
        fn main() Int {
            let mut x = 42;
            let r = &mut x;  // Mutable borrow
            *r = 24;  // OK
            return *r;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_borrow_conflict_error(self):
        """Test borrow conflict error detection."""
        src = """
        fn main() Int {
            let x = 42;
            let r1 = &x;  // Immutable borrow
            let r2 = &mut x;  // Error: cannot borrow mutably while already borrowed
            return *r2;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "borrow" in str(exc_info.value).lower()
    
    def test_multiple_immutable_borrows(self):
        """Test multiple immutable borrows."""
        src = """
        fn main() Int {
            let x = 42;
            let r1 = &x;  // Immutable borrow
            let r2 = &x;  // Another immutable borrow - OK
            return *r1 + *r2;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_borrow_lifetime(self):
        """Test borrow lifetime analysis."""
        src = """
        fn main() Int {
            let r;
            {
                let x = 42;
                r = &x;  // Error: x doesn't live long enough
            }
            return *r;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "lifetime" in str(exc_info.value).lower() or "live long enough" in str(exc_info.value).lower()


class TestStructAndEnumAnalysis:
    """Test struct and enum semantic analysis."""
    
    def test_struct_field_access(self):
        """Test struct field access."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn main() Int {
            let p = Point(1, 2);
            return p.x + p.y;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_struct_field_error(self):
        """Test struct field access error."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn main() Int {
            let p = Point(1, 2);
            return p.z;  // Error: field 'z' doesn't exist
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "field" in str(exc_info.value).lower()
    
    def test_enum_variant_access(self):
        """Test enum variant access."""
        src = """
        enum Color { Red, Green, Blue }
        
        fn main() Int {
            let c = Color::Red;
            return 0;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_match_exhaustiveness(self):
        """Test match exhaustiveness checking."""
        src = """
        enum Color { Red, Green, Blue }
        
        fn main() Int {
            let c = Color::Red;
            match c {
                Color::Red => return 1,
                Color::Green => return 2,
                Color::Blue => return 3,
            }
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_match_non_exhaustiveness_error(self):
        """Test match non-exhaustiveness error."""
        src = """
        enum Color { Red, Green, Blue }
        
        fn main() Int {
            let c = Color::Red;
            match c {
                Color::Red => return 1,
                Color::Green => return 2,
                // Missing Color::Blue case
            }
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "non-exhaustive" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()


class TestGenericAnalysis:
    """Test generic type analysis."""
    
    def test_generic_function(self):
        """Test generic function analysis."""
        src = """
        fn identity<T>(x: T) T {
            return x;
        }
        
        fn main() Int {
            return identity(42);
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_generic_struct(self):
        """Test generic struct analysis."""
        src = """
        struct Container<T> { value: T }
        
        fn main() Int {
            let c = Container<Int> { value: 42 };
            return c.value;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_trait_bounds(self):
        """Test trait bounds analysis."""
        src = """
        trait Display {
            fn display(self: Self) String;
        }
        
        fn print_value<T>(x: T) Void where T: Display {
            x.display();
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors


class TestMemorySafety:
    """Test memory safety analysis."""
    
    def test_null_pointer_check(self):
        """Test null pointer checking."""
        src = """
        fn main() Int {
            let ptr: Int* = null;
            return 0;  // OK - not dereferencing
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_null_pointer_dereference_error(self):
        """Test null pointer dereference error."""
        src = """
        fn main() Int {
            let ptr: Int* = null;
            return *ptr;  // Error: dereferencing null pointer
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "null" in str(exc_info.value).lower()
    
    def test_array_bounds_check(self):
        """Test array bounds checking."""
        src = """
        fn main() Int {
            let arr = [1, 2, 3, 4, 5];
            return arr[2];  // OK - in bounds
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_array_bounds_error(self):
        """Test array bounds error detection."""
        src = """
        fn main() Int {
            let arr = [1, 2, 3, 4, 5];
            return arr[10];  # Error: out of bounds
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "bounds" in str(exc_info.value).lower() or "out of bounds" in str(exc_info.value).lower()


class TestControlFlowAnalysis:
    """Test control flow analysis."""
    
    def test_return_analysis(self):
        """Test return statement analysis."""
        src = """
        fn main() Int {
            return 42;  // OK - function returns Int
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_missing_return_error(self):
        """Test missing return error detection."""
        src = """
        fn main() Int {
            let x = 42;
            // Missing return statement
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "return" in str(exc_info.value).lower()
    
    def test_break_outside_loop_error(self):
        """Test break outside loop error."""
        src = """
        fn main() Int {
            break;  // Error: break outside loop
            return 0;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "break" in str(exc_info.value).lower()
    
    def test_continue_outside_loop_error(self):
        """Test continue outside loop error."""
        src = """
        fn main() Int {
            continue;  # Error: continue outside loop
            return 0;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "continue" in str(exc_info.value).lower()
    
    def test_unreachable_code_detection(self):
        """Test unreachable code detection."""
        src = """
        fn main() Int {
            return 42;
            let x = 24;  // Unreachable code
            return x;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should detect unreachable code (may be warning)


class TestModuleSystem:
    """Test module system analysis."""
    
    def test_import_resolution(self, tmp_path):
        """Test import resolution."""
        dep = tmp_path / "dep.arixa"
        dep.write_text("fn helper() Int { return 42; }")
        
        src = tmp_path / "main.arixa"
        src.write_text('import "dep"; fn main() Int { return dep::helper(); }')
        
        prog = parse(src.read_text(), filename=str(src))
        analyze(prog, filename=str(src))  # Should not raise any errors
    
    def test_circular_import_error(self, tmp_path):
        """Test circular import error detection."""
        file1 = tmp_path / "module1.arixa"
        file1.write_text('import "module2"; fn f1() Int { return 42; }')
        
        file2 = tmp_path / "module2.arixa"
        file2.write_text('import "module1"; fn f2() Int { return 24; }')
        
        prog = parse(file1.read_text(), filename=str(file1))
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog, filename=str(file1))
        assert "circular" in str(exc_info.value).lower()


class TestAsyncAnalysis:
    """Test async/await analysis."""
    
    def test_async_function_analysis(self):
        """Test async function analysis."""
        src = """
        async fn async_function() Int {
            return 42;
        }
        
        fn main() Int {
            return 0;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_await_in_async_context(self):
        """Test await in async context."""
        src = """
        async fn async_function() Int {
            let future = get_value();
            return await future;
        }
        
        async fn get_value() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should not raise any errors
    
    def test_await_outside_async_error(self):
        """Test await outside async context error."""
        src = """
        fn main() Int {
            let future = get_value();
            return await future;  // Error: await outside async function
        }
        
        async fn get_value() Int {
            return 42;
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError) as exc_info:
            analyze(prog)
        assert "await" in str(exc_info.value).lower()


class TestPerformance:
    """Test semantic analysis performance."""
    
    def test_large_program_analysis(self):
        """Test analysis of large programs."""
        lines = ["fn main() Int {"]
        for i in range(1000):
            lines.append(f"    let x{i} = {i};")
        lines.append("    return 0;")
        lines.append("}")
        src = "\n".join(lines)
        
        prog = parse(src)
        analyze(prog)  # Should complete without issues
    
    def test_complex_type_inference(self):
        """Test complex type inference performance."""
        src = """
        fn complex_function<T>(x: T, y: List<T>, z: Map<String, T>) String 
        where T: Display + Clone {
            return format("value: {}", x.clone());
        }
        fn main() Int {
            return 0;
        }
        """
        prog = parse(src)
        analyze(prog)  # Should handle complex generics


class TestIntegration:
    """Test semantic analysis integration."""
    
    def test_parser_semantic_integration(self):
        """Test parser-semantic analyzer integration."""
        src = "fn main() Int { return 42; }"
        prog = parse(src)
        analyze(prog)  # Should work seamlessly
    
    def test_error_propagation(self):
        """Test error propagation through analysis phases."""
        src = """
        fn undefined_function_call() Int {
            return non_existent_function();  # Should propagate error
        }
        """
        prog = parse(src)
        with pytest.raises(SemanticError):
            analyze(prog)


if __name__ == "__main__":
    pytest.main([__file__])
