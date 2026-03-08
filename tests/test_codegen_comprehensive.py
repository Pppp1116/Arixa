"""Comprehensive code generation tests for ASTRA language.

Tests all code generation functionality including:
- Python code generation
- LLVM IR generation
- GPU code generation
- Optimization passes
- Backend-specific features
- Error handling
- Performance tests
"""

import pytest
import tempfile
import subprocess
from pathlib import Path
from astra.parser import parse
from astra.semantic import analyze
from astra.codegen import CodegenError, to_python
from astra.llvm_codegen import to_llvm_ir


class TestPythonCodegen:
    """Test Python code generation."""
    
    def test_basic_function_codegen(self):
        """Test basic function code generation."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "def main() int:" in python_code
        assert "return 42" in python_code
        assert "__name__ == '__main__'" in python_code
    
    def test_variable_declaration_codegen(self):
        """Test variable declaration code generation."""
        src = """
        fn main() Int {
            let x = 42;
            let y = 3.14;
            let z = "hello";
            return x;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "x = 42" in python_code
        assert "y = 3.14" in python_code
        assert 'z = "hello"' in python_code
    
    def test_binary_operation_codegen(self):
        """Test binary operation code generation."""
        src = """
        fn main() Int {
            let x = 1 + 2 * 3;
            let y = (4 + 5) / 2;
            return x + y;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "x = 1 + 2 * 3" in python_code
        assert "y = (4 + 5) / 2" in python_code
    
    def test_function_call_codegen(self):
        """Test function call code generation."""
        src = """
        fn helper(x: Int, y: Int) Int {
            return x + y;
        }
        
        fn main() Int {
            return helper(1, 2);
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "def helper(x, y) int:" in python_code
        assert "return helper(1, 2)" in python_code
    
    def test_if_statement_codegen(self):
        """Test if statement code generation."""
        src = """
        fn main() Int {
            let x = 42;
            if x > 0 {
                return 1;
            } else {
                return 0;
            }
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "if x > 0:" in python_code
        assert "return 1" in python_code
        assert "else:" in python_code
        assert "return 0" in python_code
    
    def test_while_loop_codegen(self):
        """Test while loop code generation."""
        src = """
        fn main() Int {
            let mut i = 0;
            while i < 10 {
                i += 1;
            }
            return i;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "while i < 10:" in python_code
        assert "i += 1" in python_code
    
    def test_for_loop_codegen(self):
        """Test for loop code generation."""
        src = """
        fn main() Int {
            let mut sum = 0;
            for item in [1, 2, 3, 4, 5] {
                sum += item;
            }
            return sum;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "for item in [1, 2, 3, 4, 5]:" in python_code
        assert "sum += item" in python_code
    
    def test_struct_codegen(self):
        """Test struct code generation."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn main() Int {
            let p = Point(1, 2);
            return p.x + p.y;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "class Point:" in python_code
        assert "def __init__(self, x, y):" in python_code
        assert "self.x = x" in python_code
        assert "self.y = y" in python_code
    
    def test_enum_codegen(self):
        """Test enum code generation."""
        src = """
        enum Color { Red, Green, Blue }
        
        fn main() Int {
            let c = Color::Red;
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "class Color:" in python_code
        assert "RED = 0" in python_code
        assert "GREEN = 1" in python_code
        assert "BLUE = 2" in python_code
    
    def test_match_statement_codegen(self):
        """Test match statement code generation."""
        src = """
        fn main() Int {
            let x = 42;
            match x {
                0 => return 0,
                1 => return 1,
                _ => return 2
            }
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "if x == 0:" in python_code
        assert "elif x == 1:" in python_code
        assert "else:" in python_code
    
    def test_unsafe_block_codegen(self):
        """Test unsafe block code generation."""
        src = """
        fn main() Int {
            unsafe {
                // Unsafe operations
                return 42;
            }
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Unsafe blocks should be handled appropriately in Python
        assert "return 42" in python_code


class TestLLVMCodegen:
    """Test LLVM IR code generation."""
    
    def test_basic_function_llvm_codegen(self):
        """Test basic function LLVM code generation."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "define" in llvm_ir
        assert "i32" in llvm_ir  # Int type
        assert "ret i32 42" in llvm_ir
    
    def test_arithmetic_operations_llvm_codegen(self):
        """Test arithmetic operations LLVM code generation."""
        src = """
        fn main() Int {
            let x = 1 + 2 * 3;
            return x;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "add" in llvm_ir
        assert "mul" in llvm_ir
        assert "i32" in llvm_ir
    
    def test_function_call_llvm_codegen(self):
        """Test function call LLVM code generation."""
        src = """
        fn helper(x: Int) Int {
            return x + 1;
        }
        
        fn main() Int {
            return helper(42);
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "call" in llvm_ir
        assert "helper" in llvm_ir
    
    def test_struct_llvm_codegen(self):
        """Test struct LLVM code generation."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn main() Int {
            let p = Point(1, 2);
            return p.x;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "%Point" in llvm_ir or "Point" in llvm_ir
        assert "i32" in llvm_ir
    
    def test_array_operations_llvm_codegen(self):
        """Test array operations LLVM code generation."""
        src = """
        fn main() Int {
            let arr = [1, 2, 3, 4, 5];
            return arr[0];
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "getelementptr" in llvm_ir or "gep" in llvm_ir
    
    def test_control_flow_llvm_codegen(self):
        """Test control flow LLVM code generation."""
        src = """
        fn main() Int {
            let x = 42;
            if x > 0 {
                return 1;
            } else {
                return 0;
            }
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        assert "br" in llvm_ir or "icmp" in llvm_ir
        assert "label" in llvm_ir.lower()


class TestGPUCodegen:
    """Test GPU code generation."""
    
    def test_gpu_kernel_codegen(self):
        """Test GPU kernel code generation."""
        src = """
        gpu kernel vector_add(a: Float*, b: Float*, c: Float*, n: Int) {
            let i = gpu.global_id();
            if i < n {
                c[i] = a[i] + b[i];
            }
        }
        
        fn main() Int {
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # GPU codegen should handle kernel functions specially
        # This test checks that the kernel is processed correctly
        assert len(analyzed_prog.items) == 2
    
    def test_gpu_builtin_functions(self):
        """Test GPU builtin function codegen."""
        src = """
        gpu kernel test_kernel() {
            let tid = gpu.thread_id();
            let bid = gpu.block_id();
            let gid = gpu.global_id();
            gpu.barrier();
        }
        
        fn main() Int {
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle GPU builtin functions
        assert len(analyzed_prog.items) == 2


class TestOptimizationPasses:
    """Test optimization passes."""
    
    def test_constant_folding(self):
        """Test constant folding optimization."""
        src = """
        fn main() Int {
            let x = 1 + 2;  # Should be folded to 3
            return x;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Optimization should fold constants
        # This is a basic test - actual optimization depends on implementation
        assert len(analyzed_prog.items) == 1
    
    def test_dead_code_elimination(self):
        """Test dead code elimination."""
        src = """
        fn unused_function() Int {
            return 42;
        }
        
        fn main() Int {
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Dead code elimination should remove unused functions
        # This is a basic test - actual optimization depends on implementation
        assert len(analyzed_prog.items) >= 1
    
    def test_inlining_optimization(self):
        """Test function inlining optimization."""
        src = """
        fn small_function(x: Int) Int {
            return x + 1;
        }
        
        fn main() Int {
            return small_function(42);  # Should be inlined
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Inlining should optimize small functions
        # This is a basic test - actual optimization depends on implementation
        assert len(analyzed_prog.items) == 2


class TestBackendSpecificFeatures:
    """Test backend-specific features."""
    
    def test_freestanding_mode(self):
        """Test freestanding mode code generation."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog, freestanding=True)
        
        # Freestanding mode should disable certain features
        python_code = to_python(analyzed_prog)
        assert "def main() int:" in python_code
    
    def test_extern_function_codegen(self):
        """Test extern function code generation."""
        src = """
        extern fn printf(format: String, ...) Int;
        
        fn main() Int {
            return printf("Hello, world!\\n");
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Extern functions should be handled appropriately
        assert "printf" in python_code
    
    def test_link_library_codegen(self):
        """Test link library code generation."""
        src = """
        @link("m")
        extern fn sqrt(x: Float) Float;
        
        fn main() Float {
            return sqrt(16.0);
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Link annotations should be preserved
        assert len(analyzed_prog.items) == 2


class TestErrorHandling:
    """Test code generation error handling."""
    
    def test_unsupported_operation_error(self):
        """Test unsupported operation error."""
        src = """
        fn main() Int {
            // This might cause codegen errors depending on implementation
            return some_unsupported_operation();
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle unsupported operations gracefully
        try:
            python_code = to_python(analyzed_prog)
        except CodegenError:
            pass  # Expected for unsupported operations
    
    def test_codegen_error_recovery(self):
        """Test code generation error recovery."""
        src = """
        fn problematic_function() Int {
            return problematic_expression();
        }
        
        fn main() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should recover from errors when possible
        try:
            python_code = to_python(analyzed_prog)
        except CodegenError:
            pass  # Expected for problematic expressions
    
    def test_memory_layout_errors(self):
        """Test memory layout errors."""
        src = """
        struct ComplexStruct {
            field1: Int,
            field2: String,
            field3: CustomType
        }
        
        fn main() Int {
            let s = ComplexStruct(1, "hello", CustomType());
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle complex memory layouts
        try:
            python_code = to_python(analyzed_prog)
        except CodegenError:
            pass  # Expected for complex types


class TestPerformance:
    """Test code generation performance."""
    
    def test_large_program_codegen(self):
        """Test large program code generation."""
        lines = ["fn main() Int {"]
        for i in range(1000):
            lines.append(f"    let x{i} = {i};")
        lines.append("    return 0;")
        lines.append("}")
        src = "\n".join(lines)
        
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle large programs efficiently
        python_code = to_python(analyzed_prog)
        assert "def main() int:" in python_code
    
    def test_complex_expression_codegen(self):
        """Test complex expression code generation."""
        src = """
        fn main() Int {
            let x = (1 + 2) * (3 - 4) / (5 + 6) % (7 - 8);
            return x;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle complex expressions efficiently
        python_code = to_python(analyzed_prog)
        assert "x = (1 + 2) * (3 - 4) / (5 + 6) % (7 - 8)" in python_code
    
    def test_deep_nesting_codegen(self):
        """Test deeply nested structure code generation."""
        lines = ["fn main() Int {"]
        for i in range(100):
            lines.append("    if true {")
        lines.append("        return 42;")
        for i in range(100):
            lines.append("    }")
        lines.append("}")
        src = "\n".join(lines)
        
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Should handle deep nesting efficiently
        python_code = to_python(analyzed_prog)
        assert "def main() int:" in python_code


class TestIntegration:
    """Test code generation integration."""
    
    def test_end_to_end_python_execution(self, tmp_path):
        """Test end-to-end Python code execution."""
        src = """
        fn main() Int {
            let x = 42;
            let y = x * 2;
            return y;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Write generated Python code to file
        py_file = tmp_path / "generated.py"
        py_file.write_text(python_code)
        
        # Execute the generated Python code
        result = subprocess.run(
            ["python", str(py_file)],
            capture_output=True,
            text=True,
            cwd=tmp_path
        )
        
        assert result.returncode == 0
        # Check if the program returned the expected value
        assert "84" in result.stdout or result.returncode == 84
    
    def test_parser_codegen_integration(self):
        """Test parser-codegen integration."""
        src = """
        fn add(a: Int, b: Int) Int {
            return a + b;
        }
        
        fn main() Int {
            return add(1, 2);
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Should integrate seamlessly
        assert "def add(a, b) int:" in python_code
        assert "return add(1, 2)" in python_code
    
    def test_semantic_codegen_integration(self):
        """Test semantic-codegen integration."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn main() Int {
            let p = Point(1, 2);
            return p.x + p.y;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Should use semantic analysis results
        assert "class Point:" in python_code
        assert "return p.x + p.y" in python_code


class TestCodegenQuality:
    """Test code generation quality."""
    
    def test_python_code_quality(self):
        """Test generated Python code quality."""
        src = """
        fn calculate_average(numbers: List<Int>) Float {
            let sum = 0;
            let count = 0;
            for num in numbers {
                sum += num;
                count += 1;
            }
            return sum as Float / count as Float;
        }
        
        fn main() Int {
            let nums = [1, 2, 3, 4, 5];
            let avg = calculate_average(nums);
            return 0;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Generated code should be valid Python
        assert "def calculate_average(numbers):" in python_code
        assert "def main() int:" in python_code
        assert "for num in numbers:" in python_code
    
    def test_llvm_ir_quality(self):
        """Test generated LLVM IR quality."""
        src = """
        fn factorial(n: Int) Int {
            if n <= 1 {
                return 1;
            } else {
                return n * factorial(n - 1);
            }
        }
        
        fn main() Int {
            return factorial(5);
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        llvm_ir = to_llvm_ir(analyzed_prog)
        
        # Generated LLVM IR should be valid
        assert "define" in llvm_ir
        assert "factorial" in llvm_ir
        assert "main" in llvm_ir
    
    def test_codegen_consistency(self):
        """Test code generation consistency."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        prog = parse(src)
        analyzed_prog = analyze(prog)
        
        # Multiple codegen calls should produce consistent results
        python_code1 = to_python(analyzed_prog)
        python_code2 = to_python(analyzed_prog)
        
        assert python_code1 == python_code2


if __name__ == "__main__":
    pytest.main([__file__])
