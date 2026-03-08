"""Comprehensive error reporting tests for ASTRA language.

Tests all error reporting functionality including:
- Error message formatting
- Context extraction
- Suggestion generation
- Error code assignment
- Multiple error handling
- Performance tests
"""

import pytest
from astra.error_reporting import (
    ErrorReporter, EnhancedError, ErrorSuggestion, ErrorContext,
    enhance_error_message
)


class TestErrorReporter:
    """Test ErrorReporter class functionality."""
    
    def test_error_reporter_initialization(self):
        """Test ErrorReporter initialization."""
        reporter = ErrorReporter()
        assert reporter.max_context_lines == 3
        assert reporter.error_patterns is not None
        
        # Test with custom context lines
        reporter_custom = ErrorReporter(max_context_lines=5)
        assert reporter_custom.max_context_lines == 5
    
    def test_create_enhanced_error(self):
        """Test enhanced error creation."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    let x = 42",
            "    return x",
            "}"
        ]
        
        error = reporter.create_enhanced_error(
            error_type="syntax_error",
            message="Expected ';' at end of statement",
            filename="example.arixa",
            line=2,
            col=14,
            source_lines=source_lines,
            error_code="PARSE001"
        )
        
        assert isinstance(error, EnhancedError)
        assert error.error_type == "syntax_error"
        assert error.message == "Expected ';' at end of statement"
        assert error.filename == "example.arixa"
        assert error.line == 2
        assert error.col == 14
        assert error.error_code == "PARSE001"
        assert error.severity == "error"
    
    def test_context_extraction(self):
        """Test context extraction from source."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    let x = 42",
            "    return x",
            "}"
        ]
        
        context = reporter._extract_context(source_lines, 2, 14)
        
        assert isinstance(context, ErrorContext)
        assert context.line_content == "    let x = 42"
        assert context.column_highlight == "             ^"
        assert len(context.nearby_lines) == 4  # All lines within context
    
    def test_suggestion_generation(self):
        """Test suggestion generation for error types."""
        reporter = ErrorReporter()
        
        # Test syntax error suggestions
        suggestions = reporter._get_suggestions("syntax_error", "Expected ';' at end of statement")
        assert len(suggestions) > 0
        assert any("Check syntax" in s.action for s in suggestions)
        
        # Test undefined name suggestions
        suggestions = reporter._get_suggestions("undefined_name", "Name 'x' is not defined")
        assert len(suggestions) > 0
        assert any("Check spelling" in s.action for s in suggestions)
        
        # Test type mismatch suggestions
        suggestions = reporter._get_suggestions("type_mismatch", "Expected Int but found String")
        assert len(suggestions) > 0
        assert any("Check types" in s.action for s in suggestions)
    
    def test_message_analysis_suggestions(self):
        """Test message-based suggestion generation."""
        reporter = ErrorReporter()
        
        # Test expected/got pattern
        suggestions = reporter._analyze_message_for_suggestions("Expected ';' but got '}'")
        assert len(suggestions) > 0
        assert any("Check syntax" in s.action for s in suggestions)
        
        # Test undefined pattern
        suggestions = reporter._analyze_message_for_suggestions("Name 'undefined_var' is not defined")
        assert len(suggestions) > 0
        assert any("Check name scope" in s.action for s in suggestions)
        
        # Test type pattern
        suggestions = reporter._analyze_message_for_suggestions("Type mismatch: Int vs String")
        assert len(suggestions) > 0
        assert any("Type conversion" in s.action for s in suggestions)
    
    def test_error_formatting(self):
        """Test error message formatting."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    let x = 42",
            "    return x",
            "}"
        ]
        
        error = reporter.create_enhanced_error(
            error_type="syntax_error",
            message="Expected ';' at end of statement",
            filename="example.arixa",
            line=2,
            col=14,
            source_lines=source_lines,
            error_code="PARSE001"
        )
        
        formatted = reporter.format_error(error)
        
        assert "❌ ERROR: syntax_error" in formatted
        assert "📍 example.arixa:2:14" in formatted
        assert "📄 Context:" in formatted
        assert "💬 Expected ';' at end of statement" in formatted
        assert "💡 Suggestions:" in formatted
        assert "🔍 Error code: PARSE001" in formatted
    
    def test_warning_formatting(self):
        """Test warning message formatting."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    let unused = 42",
            "    return 0",
            "}"
        ]
        
        error = reporter.create_enhanced_error(
            error_type="unused_variable",
            message="Variable 'unused' is declared but never used",
            filename="example.arixa",
            line=2,
            col=9,
            source_lines=source_lines,
            severity="warning",
            error_code="WARN001"
        )
        
        formatted = reporter.format_error(error)
        
        assert "⚠️ WARNING: unused_variable" in formatted
        assert "📍 example.arixa:2:9" in formatted
        assert "💬 Variable 'unused' is declared but never used" in formatted
    
    def test_multiple_errors_formatting(self):
        """Test multiple errors formatting."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    let x = \"hello\"",
            "    return x",
            "}"
        ]
        
        errors = [
            reporter.create_enhanced_error(
                error_type="type_mismatch",
                message="Expected return type 'Int' but found 'String'",
                filename="example.arixa",
                line=3,
                col=12,
                source_lines=source_lines,
                error_code="SEM102"
            ),
            reporter.create_enhanced_error(
                error_type="type_mismatch",
                message="Cannot assign String to Int variable",
                filename="example.arixa",
                line=2,
                col=13,
                source_lines=source_lines,
                error_code="SEM102"
            )
        ]
        
        formatted = reporter.format_multiple_errors(errors)
        
        assert "Found 2 errors:" in formatted
        assert "--- Error 1 ---" in formatted
        assert "--- Error 2 ---" in formatted
        assert "❌ ERROR: type_mismatch" in formatted
    
    def test_custom_suggestions(self):
        """Test custom suggestions in errors."""
        reporter = ErrorReporter()
        source_lines = [
            "fn main() Int {",
            "    return some_function()",
            "}"
        ]
        
        error = reporter.create_enhanced_error(
            error_type="undefined_name",
            message="Name 'some_function' is not defined",
            filename="example.arixa",
            line=2,
            col=12,
            source_lines=source_lines,
            error_code="SEM101"
        )
        
        # Add custom suggestions
        error.suggestions.extend([
            ErrorSuggestion(
                action="Import missing module",
                description="Add the appropriate import statement",
                code_example="import std.some_module;"
            ),
            ErrorSuggestion(
                action="Define the function",
                description="Create the function before using it",
                code_example="fn some_function() Int { return 42; }"
            )
        ])
        
        formatted = reporter.format_error(error)
        
        assert "Import missing module" in formatted
        assert "Add the appropriate import statement" in formatted
        assert "import std.some_module;" in formatted
        assert "Define the function" in formatted
        assert "Create the function before using it" in formatted


class TestEnhancedError:
    """Test EnhancedError class functionality."""
    
    def test_enhanced_error_creation(self):
        """Test EnhancedError creation."""
        context = ErrorContext(
            line_content="let x = 42",
            column_highlight="        ^",
            nearby_lines=["fn main() Int {", "    let x = 42", "    return x", "}"]
        )
        
        suggestions = [
            ErrorSuggestion("Add semicolon", "Add a semicolon at the end", "let x = 42;")
        ]
        
        error = EnhancedError(
            error_type="syntax_error",
            message="Expected ';' at end of statement",
            filename="example.arixa",
            line=2,
            col=14,
            context=context,
            suggestions=suggestions,
            severity="error",
            error_code="PARSE001"
        )
        
        assert error.error_type == "syntax_error"
        assert error.message == "Expected ';' at end of statement"
        assert error.filename == "example.arixa"
        assert error.line == 2
        assert error.col == 14
        assert error.context == context
        assert len(error.suggestions) == 1
        assert error.severity == "error"
        assert error.error_code == "PARSE001"
    
    def test_enhanced_error_with_optional_fields(self):
        """Test EnhancedError with optional fields."""
        context = ErrorContext(
            line_content="let x = 42",
            column_highlight="        ^",
            nearby_lines=["fn main() Int {", "    let x = 42", "    return x", "}"]
        )
        
        error = EnhancedError(
            error_type="info",
            message="Informational message",
            filename="example.arixa",
            line=2,
            col=14,
            context=context,
            suggestions=[],
            severity="info"
            # No error_code
        )
        
        assert error.error_type == "info"
        assert error.error_code is None


class TestErrorSuggestion:
    """Test ErrorSuggestion class functionality."""
    
    def test_error_suggestion_creation(self):
        """Test ErrorSuggestion creation."""
        suggestion = ErrorSuggestion(
            action="Add semicolon",
            description="Add a semicolon at the end of the statement",
            code_example="let x = 42;"
        )
        
        assert suggestion.action == "Add semicolon"
        assert suggestion.description == "Add a semicolon at the end of the statement"
        assert suggestion.code_example == "let x = 42;"
    
    def test_error_suggestion_without_example(self):
        """Test ErrorSuggestion without code example."""
        suggestion = ErrorSuggestion(
            action="Check syntax",
            description="Verify the syntax is correct"
        )
        
        assert suggestion.action == "Check syntax"
        assert suggestion.description == "Verify the syntax is correct"
        assert suggestion.code_example is None


class TestErrorContext:
    """Test ErrorContext class functionality."""
    
    def test_error_context_creation(self):
        """Test ErrorContext creation."""
        context = ErrorContext(
            line_content="let x = 42",
            column_highlight="        ^",
            nearby_lines=["fn main() Int {", "    let x = 42", "    return x", "}"],
            function_name="main",
            module_name="example"
        )
        
        assert context.line_content == "let x = 42"
        assert context.column_highlight == "        ^"
        assert len(context.nearby_lines) == 4
        assert context.function_name == "main"
        assert context.module_name == "example"
    
    def test_error_context_without_optional_fields(self):
        """Test ErrorContext without optional fields."""
        context = ErrorContext(
            line_content="let x = 42",
            column_highlight="        ^",
            nearby_lines=["fn main() Int {", "    let x = 42", "    return x", "}"]
        )
        
        assert context.line_content == "let x = 42"
        assert context.column_highlight == "        ^"
        assert len(context.nearby_lines) == 4
        assert context.function_name is None
        assert context.module_name is None


class TestErrorEnhancement:
    """Test error enhancement functionality."""
    
    def test_enhance_error_message(self):
        """Test basic error message enhancement."""
        original_error = "SEM example.arixa:3:12: Expected return type 'Int' but found 'String'"
        source_content = """fn main() Int {
    let x = "hello";
    return x;
}"""
        
        enhanced = enhance_error_message(
            original_error=original_error,
            error_type="type_mismatch",
            filename="example.arixa",
            line=3,
            col=12,
            source_content=source_content
        )
        
        assert "❌ ERROR: type_mismatch" in enhanced
        assert "📍 example.arixa:3:12" in enhanced
        assert "📄 Context:" in enhanced
        assert "💬 Expected return type 'Int' but found 'String'" in enhanced
        assert "💡 Suggestions:" in enhanced
    
    def test_enhance_error_message_with_context(self):
        """Test error enhancement with specific context."""
        original_error = "PARSE example.arixa:2:14: Expected ';' at end of statement"
        source_content = """fn main() Int {
    let x = 42
    return x;
}"""
        
        enhanced = enhance_error_message(
            original_error=original_error,
            error_type="syntax_error",
            filename="example.arixa",
            line=2,
            col=14,
            source_content=source_content
        )
        
        assert "❌ ERROR: syntax_error" in enhanced
        assert "let x = 42" in enhanced
        assert "             ^" in enhanced
        assert "💡 Suggestions:" in enhanced


class TestErrorPatterns:
    """Test error pattern functionality."""
    
    def test_expected_token_pattern(self):
        """Test expected token error pattern."""
        reporter = ErrorReporter()
        pattern = reporter.error_patterns.get("expected_token", {})
        
        assert pattern is not None
        assert "suggestions" in pattern
        assert len(pattern["suggestions"]) > 0
    
    def test_undefined_name_pattern(self):
        """Test undefined name error pattern."""
        reporter = ErrorReporter()
        pattern = reporter.error_patterns.get("undefined_name", {})
        
        assert pattern is not None
        assert "suggestions" in pattern
        assert len(pattern["suggestions"]) > 0
    
    def test_type_mismatch_pattern(self):
        """Test type mismatch error pattern."""
        reporter = ErrorReporter()
        pattern = reporter.error_patterns.get("type_mismatch", {})
        
        assert pattern is not None
        assert "suggestions" in pattern
        assert len(pattern["suggestions"]) > 0
    
    def test_borrow_checker_pattern(self):
        """Test borrow checker error pattern."""
        reporter = ErrorReporter()
        pattern = reporter.error_patterns.get("borrow_checker", {})
        
        assert pattern is not None
        assert "suggestions" in pattern
        assert len(pattern["suggestions"]) > 0


class TestErrorReportingIntegration:
    """Test error reporting integration with other components."""
    
    def test_parser_error_integration(self):
        """Test integration with parser errors."""
        # This would test integration with actual parser
        # For now, test the structure
        reporter = ErrorReporter()
        
        # Simulate parser error
        source_lines = ["fn main() Int {", "    let x = 42", "    return x", "}"]
        error = reporter.create_enhanced_error(
            error_type="syntax_error",
            message="Expected ';' at end of statement",
            filename="example.arixa",
            line=2,
            col=14,
            source_lines=source_lines,
            error_code="PARSE001"
        )
        
        assert error.error_type == "syntax_error"
        assert error.error_code == "PARSE001"
    
    def test_semantic_error_integration(self):
        """Test integration with semantic errors."""
        # This would test integration with actual semantic analyzer
        # For now, test the structure
        reporter = ErrorReporter()
        
        # Simulate semantic error
        source_lines = ["fn main() Int {", "    let x = \"hello\";", "    return x;", "}"]
        error = reporter.create_enhanced_error(
            error_type="type_mismatch",
            message="Expected return type 'Int' but found 'String'",
            filename="example.arixa",
            line=3,
            col=12,
            source_lines=source_lines,
            error_code="SEM102"
        )
        
        assert error.error_type == "type_mismatch"
        assert error.error_code == "SEM102"
    
    def test_codegen_error_integration(self):
        """Test integration with codegen errors."""
        # This would test integration with actual codegen
        # For now, test the structure
        reporter = ErrorReporter()
        
        # Simulate codegen error
        source_lines = ["fn main() Int {", "    return unsupported_operation()", "}"]
        error = reporter.create_enhanced_error(
            error_type="codegen_error",
            message="Operation 'unsupported_operation' is not supported",
            filename="example.arixa",
            line=2,
            col=12,
            source_lines=source_lines,
            error_code="CODEGEN501"
        )
        
        assert error.error_type == "codegen_error"
        assert error.error_code == "CODEGEN501"


class TestErrorReportingPerformance:
    """Test error reporting performance."""
    
    def test_large_context_handling(self):
        """Test handling large source contexts."""
        reporter = ErrorReporter(max_context_lines=10)
        
        # Generate a large source file
        source_lines = ["fn main() Int {"]
        for i in range(1000):
            source_lines.append(f"    let x{i} = {i};")
        source_lines.append("    return 0;")
        source_lines.append("}")
        
        # Create error in the middle
        error = reporter.create_enhanced_error(
            error_type="syntax_error",
            message="Test error",
            filename="large.arixa",
            line=500,
            col=10,
            source_lines=source_lines,
            error_code="TEST001"
        )
        
        # Should handle large context efficiently
        assert len(error.context.nearby_lines) <= 21  # 10 lines before + error line + 10 lines after
    
    def test_many_errors_formatting(self):
        """Test formatting many errors."""
        reporter = ErrorReporter()
        source_lines = ["fn main() Int {", "    let x = 42", "    return x", "}"]
        
        # Create many errors
        errors = []
        for i in range(100):
            error = reporter.create_enhanced_error(
                error_type="test_error",
                message=f"Test error {i}",
                filename="test.arixa",
                line=2,
                col=10,
                source_lines=source_lines,
                error_code=f"TEST{i:03d}"
            )
            errors.append(error)
        
        # Should format many errors efficiently
        formatted = reporter.format_multiple_errors(errors)
        assert "Found 100 errors:" in formatted
        assert "--- Error 1 ---" in formatted
        assert "--- Error 100 ---" in formatted
    
    def test_complex_suggestion_generation(self):
        """Test complex suggestion generation performance."""
        reporter = ErrorReporter()
        
        # Test with complex error messages
        complex_messages = [
            "Expected ';' at end of statement but got '}'",
            "Name 'complex_variable_name' is not defined in this context",
            "Type mismatch: expected 'Map<String, List<Int>>' but found 'Array<String>>'",
            "Cannot create mutable reference to 'complex_nested_struct.field.subfield' because it is already borrowed",
        ]
        
        for message in complex_messages:
            suggestions = reporter._get_suggestions("test_error", message)
            assert len(suggestions) > 0
            assert len(suggestions) <= 3  # Should limit to 3 suggestions


class TestErrorReportingEdgeCases:
    """Test error reporting edge cases."""
    
    def test_empty_source_lines(self):
        """Test error with empty source lines."""
        reporter = ErrorReporter()
        
        error = reporter.create_enhanced_error(
            error_type="test_error",
            message="Test error",
            filename="empty.arixa",
            line=1,
            col=1,
            source_lines=[],
            error_code="TEST001"
        )
        
        assert error.context.line_content == ""
        assert error.context.nearby_lines == []
    
    def test_line_out_of_bounds(self):
        """Test error with line number out of bounds."""
        reporter = ErrorReporter()
        source_lines = ["fn main() Int {", "    return 0;", "}"]
        
        # Test with line number beyond file length
        error = reporter.create_enhanced_error(
            error_type="test_error",
            message="Test error",
            filename="test.arixa",
            line=10,
            col=1,
            source_lines=source_lines,
            error_code="TEST001"
        )
        
        # Should handle gracefully
        assert error.context.line_content == ""
    
    def test_column_out_of_bounds(self):
        """Test error with column number out of bounds."""
        reporter = ErrorReporter()
        source_lines = ["fn main() Int {", "    return 0;", "}"]
        
        # Test with column number beyond line length
        error = reporter.create_enhanced_error(
            error_type="test_error",
            message="Test error",
            filename="test.arixa",
            line=2,
            col=100,
            source_lines=source_lines,
            error_code="TEST001"
        )
        
        # Should handle gracefully
        assert len(error.context.column_highlight) >= 100
    
    def test_unicode_characters_in_context(self):
        """Test error with Unicode characters in context."""
        reporter = ErrorReporter()
        source_lines = ["fn main() Int {", "    let 变量 = 42;", "    return 变量;", "}"]
        
        error = reporter.create_enhanced_error(
            error_type="test_error",
            message="Test error",
            filename="unicode.arixa",
            line=2,
            col=10,
            source_lines=source_lines,
            error_code="TEST001"
        )
        
        # Should handle Unicode characters correctly
        assert "变量" in error.context.line_content
        assert len(error.context.nearby_lines) == 4
    
    def test_very_long_line(self):
        """Test error with very long line."""
        reporter = ErrorReporter()
        long_line = "let x = " + "a" * 1000 + ";"
        source_lines = ["fn main() Int {", long_line, "    return x;", "}"]
        
        error = reporter.create_enhanced_error(
            error_type="test_error",
            message="Test error",
            filename="long.arixa",
            line=2,
            col=500,
            source_lines=source_lines,
            error_code="TEST001"
        )
        
        # Should handle long lines correctly
        assert len(error.context.line_content) > 1000
        assert len(error.context.column_highlight) >= 500


if __name__ == "__main__":
    pytest.main([__file__])
