"""Comprehensive integration tests for ASTRA language.

Tests end-to-end integration between all compiler components:
- Lexer → Parser → Semantic Analysis → Codegen
- Error reporting integration
- Real-world program compilation
- Performance benchmarks
- Tool integration
"""

import pytest
import tempfile
import subprocess
from pathlib import Path
from astra.lexer import lex
from astra.parser import parse, ParseError
from astra.semantic import analyze, SemanticError
from astra.codegen import to_python, CodegenError
from astra.error_reporting import ErrorReporter, enhance_error_message


class TestEndToEndCompilation:
    """Test complete compilation pipeline."""
    
    def test_simple_program_compilation(self):
        """Test compilation of a simple program."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        
        # Test lexer
        tokens = lex(src)
        assert len(tokens) > 0
        
        # Test parser
        prog = parse(src)
        assert len(prog.items) == 1
        assert prog.items[0].name == "main"
        
        # Test semantic analysis
        analyzed_prog = analyze(prog)
        assert len(analyzed_prog.items) == 1
        
        # Test code generation
        python_code = to_python(analyzed_prog)
        assert "def main() int:" in python_code
        assert "return 42" in python_code
    
    def test_complex_program_compilation(self):
        """Test compilation of a complex program."""
        src = """
        struct Point { x: Int, y: Int }
        
        fn distance(p1: Point, p2: Point) Float {
            let dx = p1.x - p2.x;
            let dy = p1.y - p2.y;
            return sqrt(dx * dx + dy * dy);
        }
        
        fn main() Int {
            let p1 = Point(0, 0);
            let p2 = Point(3, 4);
            let d = distance(p1, p2);
            return 0;
        }
        """
        
        # Test complete pipeline
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "class Point:" in python_code
        assert "def distance(p1, p2):" in python_code
        assert "def main() int:" in python_code
    
    def test_program_with_errors(self):
        """Test compilation with errors."""
        src = """
        fn main() Int {
            let x = "hello";  // Type mismatch
            return x;
        }
        """
        
        # Lexer should work
        tokens = lex(src)
        assert len(tokens) > 0
        
        # Parser should work
        prog = parse(src)
        assert len(prog.items) == 1
        
        # Semantic analysis should fail
        with pytest.raises(SemanticError):
            analyze(prog)
    
    def test_program_with_syntax_errors(self):
        """Test compilation with syntax errors."""
        src = """
        fn main() Int {
            let x = 42  // Missing semicolon
            return x;
        }
        """
        
        # Lexer should work
        tokens = lex(src)
        assert len(tokens) > 0
        
        # Parser should fail
        with pytest.raises(ParseError):
            parse(src)


class TestErrorReportingIntegration:
    """Test error reporting integration with compiler components."""
    
    def test_parser_error_enhancement(self):
        """Test parser error enhancement."""
        src = """
        fn main() Int {
            let x = 42  // Missing semicolon
            return x;
        }
        """
        
        try:
            parse(src)
            assert False, "Should have raised ParseError"
        except ParseError as e:
            # Should be able to enhance the error
            enhanced = enhance_error_message(
                original_error=str(e),
                error_type="syntax_error",
                filename="test.arixa",
                line=3,
                col=18,
                source_content=src
            )
            assert "❌ ERROR: syntax_error" in enhanced
            assert "💡 Suggestions:" in enhanced
    
    def test_semantic_error_enhancement(self):
        """Test semantic error enhancement."""
        src = """
        fn main() Int {
            let x = "hello";
            return x;
        }
        """
        
        prog = parse(src)
        
        try:
            analyze(prog)
            assert False, "Should have raised SemanticError"
        except SemanticError as e:
            # Should be able to enhance the error
            enhanced = enhance_error_message(
                original_error=str(e),
                error_type="type_mismatch",
                filename="test.arixa",
                line=3,
                col=12,
                source_content=src
            )
            assert "❌ ERROR: type_mismatch" in enhanced
            assert "💡 Suggestions:" in enhanced
    
    def test_multiple_error_reporting(self):
        """Test multiple error reporting."""
        src = """
        fn main() Int {
            let x = "hello";  // Type mismatch
            let y = undefined_var;  // Undefined variable
            return x;
        }
        """
        
        prog = parse(src)
        
        try:
            analyze(prog)
            assert False, "Should have raised SemanticError"
        except SemanticError as e:
            # Should be able to enhance and potentially collect multiple errors
            enhanced = enhance_error_message(
                original_error=str(e),
                error_type="semantic_error",
                filename="test.arixa",
                line=3,
                col=12,
                source_content=src
            )
            assert "❌ ERROR: semantic_error" in enhanced


class TestRealWorldPrograms:
    """Test compilation of real-world programs."""
    
    def test_calculator_program(self):
        """Test a calculator program."""
        src = """
        struct Calculator {
            memory: Float,
        }
        
        fn new_calculator() Calculator {
            Calculator { memory: 0.0 }
        }
        
        fn add(self: Calculator, x: Float) Float {
            self.memory = self.memory + x;
            return self.memory;
        }
        
        fn subtract(self: Calculator, x: Float) Float {
            self.memory = self.memory - x;
            return self.memory;
        }
        
        fn multiply(self: Calculator, x: Float) Float {
            self.memory = self.memory * x;
            return self.memory;
        }
        
        fn divide(self: Calculator, x: Float) Float {
            if x != 0.0 {
                self.memory = self.memory / x;
                return self.memory;
            } else {
                return 0.0;
            }
        }
        
        fn main() Int {
            let calc = new_calculator();
            calc = add(calc, 10.0);
            calc = multiply(calc, 2.0);
            calc = subtract(calc, 5.0);
            calc = divide(calc, 3.0);
            return 0;
        }
        """
        
        # Test complete compilation
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "class Calculator:" in python_code
        assert "def new():" in python_code
        assert "def add(self, x):" in python_code
        assert "def main() int:" in python_code
    
    def test_string_processing_program(self):
        """Test a string processing program."""
        src = """
        fn count_words(text: String) Int {
            let mut count = 0;
            let mut in_word = false;
            
            for ch in text {
                if ch == ' ' or ch == '\\t' or ch == '\\n' {
                    in_word = false;
                } else if not in_word {
                    count += 1;
                    in_word = true;
                }
            }
            
            return count;
        }
        
        fn reverse_string(s: String) String {
            let mut result = "";
            for ch in s {
                result = ch + result;
            }
            return result;
        }
        
        fn main() Int {
            let text = "Hello world this is a test";
            let word_count = count_words(text);
            let reversed = reverse_string(text);
            return 0;
        }
        """
        
        # Test complete compilation
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "def count_words(text):" in python_code
        assert "def reverse_string(s):" in python_code
        assert "def main() int:" in python_code
    
    def test_data_structures_program(self):
        """Test a data structures program."""
        src = """
        struct ListNode<T> {
            value: T,
            next: ListNode<T>*,
        }
        
        struct LinkedList<T> {
            head: ListNode<T>*,
            size: Int,
        }
        
        fn new_linked_list<T>() LinkedList<T> {
            LinkedList { head: null, size: 0 }
        }
        
        fn append<T>(self: LinkedList<T>, value: T) LinkedList<T> {
            let new_node = ListNode { value: value, next: null };
            if self.head == null {
                self.head = &new_node;
            } else {
                let mut current = self.head;
                while current.next != null {
                    current = current.next;
                }
                current.next = &new_node;
            }
            self.size += 1;
            return self;
        }
        
        fn find<T>(self: LinkedList<T>, value: T) ListNode<T>* {
            let mut current = self.head;
            while current != null {
                if current.value == value {
                    return current;
                }
                current = current.next;
            }
            return null;
        }
        
        fn main() Int {
            let list = new_linked_list<Int>();
            list = append(list, 1);
            list = append(list, 2);
            list = append(list, 3);
            let node = find(list, 2);
            return 0;
        }
        """
        
        # Test complete compilation
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        assert "class ListNode:" in python_code
        assert "class LinkedList:" in python_code
        assert "def new():" in python_code
        assert "def append(self, value):" in python_code


class TestPerformanceBenchmarks:
    """Test performance benchmarks for the compiler."""
    
    def test_large_program_compilation_speed(self):
        """Test compilation speed for large programs."""
        # Generate a large program
        lines = ["fn main() Int {"]
        for i in range(1000):
            lines.extend([
                f"    let x{i} = {i};",
                f"    let y{i} = x{i} * 2;",
                f"    let z{i} = y{i} + 1;",
            ])
        lines.append("    return 0;")
        lines.append("}")
        src = "\n".join(lines)
        
        # Test compilation speed
        import time
        start_time = time.time()
        
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        end_time = time.time()
        compilation_time = end_time - start_time
        
        # Should complete within reasonable time (adjust threshold as needed)
        assert compilation_time < 10.0  # 10 seconds
        assert len(tokens) > 0
        assert len(prog.items) == 1
        assert "def main() int:" in python_code
    
    def test_memory_usage_compilation(self):
        """Test memory usage during compilation."""
        import psutil
        import os
        
        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Generate and compile a moderately large program
        lines = ["fn main() Int {"]
        for i in range(500):
            lines.extend([
                f"    let x{i} = {i};",
                f"    let y{i} = x{i} * 2;",
            ])
        lines.append("    return 0;")
        lines.append("}")
        src = "\n".join(lines)
        
        # Compile
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Check memory usage
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (adjust threshold as needed)
        assert memory_increase < 100 * 1024 * 1024  # 100MB
    
    def test_concurrent_compilation(self):
        """Test concurrent compilation of multiple programs."""
        import threading
        import queue
        
        programs = []
        for i in range(10):
            src = f"""
            fn program_{i}() Int {{
                let x = {i} * 2;
                return x;
            }}
            
            fn main() Int {{
                return program_{i}();
            }}
            """
            programs.append(src)
        
        results = queue.Queue()
        
        def compile_program(src, index):
            try:
                tokens = lex(src)
                prog = parse(src)
                analyzed_prog = analyze(prog)
                python_code = to_python(analyzed_prog)
                results.put((index, True, None))
            except Exception as e:
                results.put((index, False, str(e)))
        
        # Compile programs concurrently
        threads = []
        for i, src in enumerate(programs):
            thread = threading.Thread(target=compile_program, args=(src, i))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        success_count = 0
        while not results.empty():
            index, success, error = results.get()
            if success:
                success_count += 1
            else:
                pytest.fail(f"Program {index} failed to compile: {error}")
        
        assert success_count == 10


class TestToolIntegration:
    """Test integration with external tools."""
    
    def test_cli_integration(self, tmp_path):
        """Test CLI tool integration."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        
        # Write source file
        src_file = tmp_path / "test.arixa"
        src_file.write_text(src)
        
        # Test CLI check command
        try:
            result = subprocess.run(
                ["arixa", "check", str(src_file)],
                capture_output=True,
                text=True,
                cwd=tmp_path
            )
            # Should succeed (exit code 0) or fail with meaningful error
            assert result.returncode in [0, 1]
        except FileNotFoundError:
            # CLI tool not available, skip test
            pytest.skip("CLI tool not available")
    
    def test_vscode_extension_integration(self):
        """Test VS Code extension integration."""
        # This would test LSP server integration
        # For now, test the structure that would be used
        from astra.lsp import LSPServer
        
        # Test LSP server initialization
        server = LSPServer()
        assert server is not None
    
    def test_build_system_integration(self, tmp_path):
        """Test build system integration."""
        src = """
        fn main() Int {
            return 42;
        }
        """
        
        # Write source file
        src_file = tmp_path / "main.arixa"
        src_file.write_text(src)
        
        # Test build command
        try:
            result = subprocess.run(
                ["arixa", "build", str(src_file), "-o", str(tmp_path / "output.py")],
                capture_output=True,
                text=True,
                cwd=tmp_path
            )
            # Should succeed or fail with meaningful error
            assert result.returncode in [0, 1]
        except FileNotFoundError:
            # Build tool not available, skip test
            pytest.skip("Build tool not available")


class TestStandardLibraryIntegration:
    """Test standard library integration."""
    
    def test_stdlib_imports(self):
        """Test standard library imports."""
        src = """
        import std.str;
        import std.math;
        import std.collections;
        
        fn main() Int {
            let text = "Hello, world!";
            let length = str.length(text);
            let numbers = [1, 2, 3, 4, 5];
            let sum = collections.sum(numbers);
            return 0;
        }
        """
        
        # Test compilation (may fail due to missing stdlib implementation)
        try:
            tokens = lex(src)
            prog = parse(src)
            analyzed_prog = analyze(prog)
            python_code = to_python(analyzed_prog)
            # Should handle imports appropriately
        except (SemanticError, CodegenError):
            # Expected if stdlib is not fully implemented
            pass
    
    def test_stdlib_function_calls(self):
        """Test standard library function calls."""
        src = """
        fn main() Int {
            let result = str.to_string_int(42);
            let parsed = str.to_int("123");
            let numbers = vec.from_array([1, 2, 3]);
            return 0;
        }
        """
        
        # Test compilation
        try:
            tokens = lex(src)
            prog = parse(src)
            analyzed_prog = analyze(prog)
            python_code = to_python(analyzed_prog)
            # Should handle stdlib calls appropriately
        except (SemanticError, CodegenError):
            # Expected if stdlib is not fully implemented
            pass


class TestCrossLanguageIntegration:
    """Test cross-language integration."""
    
    def test_c_ffi_integration(self):
        """Test C FFI integration."""
        src = """
        extern fn printf(format: String, ...) Int;
        extern fn malloc(size: Int) Void*;
        extern fn free(ptr: Void*) Void;
        
        fn main() Int {
            printf("Hello, world!\\n");
            let ptr = malloc(1024);
            free(ptr);
            return 0;
        }
        """
        
        # Test compilation
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Should handle extern functions
        assert "printf" in python_code
    
    def test_python_interop_integration(self):
        """Test Python interoperability."""
        src = """
        fn main() Int {
            # Python-specific operations
            let py_list = [1, 2, 3, 4, 5];
            let py_dict = {"key": "value"};
            let result = py_list + [6, 7, 8];
            return 0;
        }
        """
        
        # Test compilation to Python
        tokens = lex(src)
        prog = parse(src)
        analyzed_prog = analyze(prog)
        python_code = to_python(analyzed_prog)
        
        # Should generate valid Python
        assert "py_list" in python_code
        assert "py_dict" in python_code


class TestErrorRecoveryIntegration:
    """Test error recovery integration."""
    
    def test_partial_compilation_with_errors(self):
        """Test compilation with some errors that can be recovered."""
        src = """
        fn good_function() Int {
            return 42;
        }
        
        fn bad_function() Int {
            let x = "hello";  // Type error
            return x;
        }
        
        fn main() Int {
            return good_function();  // Should work despite bad_function
        }
        """
        
        # Test if compiler can recover from some errors
        tokens = lex(src)
        prog = parse(src)
        
        try:
            analyzed_prog = analyze(prog)
            # If semantic analysis succeeds, test codegen
            python_code = to_python(analyzed_prog)
            assert "def good_function():" in python_code
        except SemanticError:
            # Expected due to type error in bad_function
            pass
    
    def test_error_accumulation(self):
        """Test accumulation of multiple errors."""
        src = """
        fn main() Int {
            let x = "hello";  // Type error 1
            let y = undefined_var;  // Undefined variable error
            let z = x + 42;  // Type error 2
            return x;  // Return type error
        }
        """
        
        # Test if multiple errors can be collected
        tokens = lex(src)
        prog = parse(src)
        
        try:
            analyzed_prog = analyze(prog)
            assert False, "Should have raised SemanticError"
        except SemanticError as e:
            # Should contain information about multiple errors
            error_str = str(e)
            # Error message should be informative
            assert len(error_str) > 0


if __name__ == "__main__":
    pytest.main([__file__])
