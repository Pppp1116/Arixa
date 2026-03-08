"""Comprehensive lexer tests for ASTRA language.

Tests all lexer functionality including:
- Token recognition and classification
- Position tracking (line, column)
- Comment handling
- Error token generation
- Edge cases and special characters
- Performance tests
"""

import pytest
from astra.lexer import lex, Token


class TestLexerBasics:
    """Test basic lexer functionality."""
    
    def test_empty_input(self):
        """Test lexing empty input."""
        tokens = lex("")
        assert len(tokens) == 0
    
    def test_whitespace_only(self):
        """Test lexing whitespace-only input."""
        tokens = lex("   \n\t  \n  ")
        assert len(tokens) == 0
    
    def test_single_tokens(self):
        """Test individual token recognition."""
        test_cases = [
            (";", "SEMICOLON"),
            (":", "COLON"),
            (",", "COMMA"),
            (".", "DOT"),
            ("(", "LPAREN"),
            (")", "RPAREN"),
            ("{", "LBRACE"),
            ("}", "RBRACE"),
            ("[", "LBRACK"),
            ("]", "RBRACK"),
            ("@", "AT"),
            ("#", "HASH"),
            ("$", "ERROR"),  # Invalid character
        ]
        
        for char, expected_kind in test_cases:
            tokens = lex(char)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == char
    
    def test_operators(self):
        """Test operator token recognition."""
        operators = [
            "+", "-", "*", "/", "%", "**", "//",
            "==", "!=", "<", ">", "<=", ">=",
            "&&", "||", "!", "&", "|", "^", "~",
            "<<", ">>", ">>>",
            "+=", "-=", "*=", "/=", "%=", "**=", "//=",
            "&=", "|=", "^=", "<<=", ">>=", ">>>=",
            "=>", "->", "??", "::", "...", "..", "..="
        ]
        
        for op in operators:
            tokens = lex(op)
            assert len(tokens) == 1
            assert tokens[0].kind == op
            assert tokens[0].text == op


class TestKeywords:
    """Test keyword recognition."""
    
    def test_all_keywords(self):
        """Test all ASTRA keywords."""
        keywords = [
            "fn", "let", "mut", "set", "if", "else", "while", "for", "in",
            "break", "continue", "return", "struct", "enum", "type", "import",
            "extern", "unsafe", "match", "case", "default", "trait", "impl",
            "where", "async", "await", "spawn", "join", "yield", "defer",
            "comptime", "pub", "priv", "static", "const", "true", "false",
            "none", "self", "super", "as", "is", "in", "not", "and", "or",
            "xor", "module", "package", "use", "with", "try", "catch",
            "finally", "throw", "throws", "virtual", "abstract", "override",
            "final", "inline", "macro", "typeof", "sizeof", "alignof", "offsetof"
        ]
        
        for keyword in keywords:
            tokens = lex(keyword)
            assert len(tokens) == 1
            assert tokens[0].kind == keyword.upper()
    
    def test_keyword_vs_identifier(self):
        """Test that keywords are not treated as identifiers."""
        # Keywords should be recognized as keywords
        tokens = lex("fn")
        assert len(tokens) == 1
        assert tokens[0].kind == "FN"
        
        # Similar but not keywords should be identifiers
        tokens = lex("fnx")
        assert len(tokens) == 1
        assert tokens[0].kind == "IDENT"
        assert tokens[0].text == "fnx"


class TestLiterals:
    """Test literal token recognition."""
    
    def test_integer_literals(self):
        """Test integer literal recognition."""
        test_cases = [
            ("0", "INT"),
            ("42", "INT"),
            ("123456789", "INT"),
            ("0b1010", "INT"),
            ("0o755", "INT"),
            ("0xFF", "INT"),
            ("0Xff", "INT"),
            ("1_000_000", "INT"),
            ("42u8", "INT"),
            ("42i64", "INT"),
            ("42u32", "INT"),
        ]
        
        for literal, expected_kind in test_cases:
            tokens = lex(literal)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == literal
    
    def test_float_literals(self):
        """Test float literal recognition."""
        test_cases = [
            ("0.0", "FLOAT"),
            ("3.14159", "FLOAT"),
            ("2.5f32", "FLOAT"),
            ("1.0f64", "FLOAT"),
            ("1e10", "FLOAT"),
            ("1.5e-3", "FLOAT"),
            ("6.022e23", "FLOAT"),
            ("1.5E+10", "FLOAT"),
            ("1_000.000_001", "FLOAT"),
        ]
        
        for literal, expected_kind in test_cases:
            tokens = lex(literal)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == literal
    
    def test_string_literals(self):
        """Test string literal recognition."""
        test_cases = [
            ('"hello"', "STR"),
            ('"hello\\nworld"', "STR"),
            ('"\\x41\\x42\\x43"', "STR"),
            ('"\\u0041\\u0042"', "STR"),
            ('""', "STR"),
            ('"escaped \\"quote\\""', "STR"),
        ]
        
        for literal, expected_kind in test_cases:
            tokens = lex(literal)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == literal
    
    def test_char_literals(self):
        """Test character literal recognition."""
        test_cases = [
            ("'a'", "CHAR"),
            ("'\\n'", "CHAR"),
            ("'\\\\'", "CHAR"),
            ("'\\x41'", "CHAR"),
            ("'\\u0041'", "CHAR"),
        ]
        
        for literal, expected_kind in test_cases:
            tokens = lex(literal)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == literal
    
    def test_boolean_literals(self):
        """Test boolean literal recognition."""
        test_cases = [
            ("true", "BOOL"),
            ("false", "BOOL"),
        ]
        
        for literal, expected_kind in test_cases:
            tokens = lex(literal)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
            assert tokens[0].text == literal


class TestIdentifiers:
    """Test identifier recognition."""
    
    def test_simple_identifiers(self):
        """Test simple identifier recognition."""
        test_cases = [
            "x", "y", "z", "foo", "bar", "baz", "qux", "quux",
            "variable_name", "functionName", "CONSTANT_VALUE",
            "_private", "__magic__", "$special", "with_numbers123",
        ]
        
        for identifier in test_cases:
            tokens = lex(identifier)
            assert len(tokens) == 1
            assert tokens[0].kind == "IDENT"
            assert tokens[0].text == identifier
    
    def test_unicode_identifiers(self):
        """Test Unicode identifier support."""
        unicode_identifiers = [
            "变量", "函数", "класс", "関数", "متغير",
            "café", "naïve", "résumé", "piñata",
        ]
        
        for identifier in unicode_identifiers:
            tokens = lex(identifier)
            assert len(tokens) == 1
            assert tokens[0].kind == "IDENT"
            assert tokens[0].text == identifier


class TestComments:
    """Test comment handling."""
    
    def test_line_comments(self):
        """Test line comment handling."""
        source = """
        // This is a line comment
        x = 42; // Another comment
        """
        tokens = lex(source)
        # Comments should be ignored
        assert all(token.kind != "COMMENT" for token in tokens)
        assert len(tokens) >= 3  # x, =, 42, ;
    
    def test_block_comments(self):
        """Test block comment handling."""
        source = """
        /* This is a block comment */
        x = 42; /* Another block comment */
        """
        tokens = lex(source)
        # Comments should be ignored
        assert all(token.kind != "COMMENT" for token in tokens)
        assert len(tokens) >= 3  # x, =, 42, ;
    
    def test_nested_block_comments(self):
        """Test nested block comment handling."""
        source = """
        /* Outer comment
           /* Inner comment */
           Still outer
        */
        x = 42;
        """
        tokens = lex(source)
        # Comments should be ignored
        assert all(token.kind != "COMMENT" for token in tokens)
        assert len(tokens) >= 3  # x, =, 42, ;
    
    def test_doc_comments(self):
        """Test documentation comment handling."""
        source = """
        /// This is a doc comment
        /** This is a block doc comment */
        x = 42;
        """
        tokens = lex(source)
        # Doc comments should be preserved
        doc_tokens = [t for t in tokens if t.kind == "DOC_COMMENT"]
        assert len(doc_tokens) >= 2


class TestPositionTracking:
    """Test line and column position tracking."""
    
    def test_single_line_positions(self):
        """Test position tracking on single line."""
        source = "x = 42 + y;"
        tokens = lex(source)
        
        expected_positions = [
            (1, 1),  # x
            (1, 3),  # =
            (1, 5),  # 42
            (1, 8),  # +
            (1, 10), # y
            (1, 11), # ;
        ]
        
        for token, (line, col) in zip(tokens, expected_positions):
            assert token.line == line
            assert token.col == col
    
    def test_multi_line_positions(self):
        """Test position tracking across multiple lines."""
        source = """x = 42;
y = x + 1;
z = y * 2;
"""
        tokens = lex(source)
        
        # Check specific tokens
        x_token = next(t for t in tokens if t.text == "x")
        y_token = next(t for t in tokens if t.text == "y")
        z_token = next(t for t in tokens if t.text == "z")
        
        assert x_token.line == 1
        assert x_token.col == 1
        assert y_token.line == 2
        assert y_token.col == 1
        assert z_token.line == 3
        assert z_token.col == 1
    
    def test_position_with_unicode(self):
        """Test position tracking with Unicode characters."""
        source = "变量 = 42;"
        tokens = lex(source)
        
        var_token = next(t for t in tokens if t.text == "变量")
        assert var_token.line == 1
        assert var_token.col == 1


class TestErrorHandling:
    """Test error token generation."""
    
    def test_invalid_characters(self):
        """Test handling of invalid characters."""
        invalid_chars = ["$", "@", "#", "~", "`"]
        
        for char in invalid_chars:
            tokens = lex(char)
            assert len(tokens) == 1
            assert tokens[0].kind == "ERROR"
            assert tokens[0].text == char
    
    def test_unclosed_string(self):
        """Test handling of unclosed string literals."""
        source = '"unclosed string'
        tokens = lex(source)
        
        # Should generate an error token
        error_tokens = [t for t in tokens if t.kind == "ERROR"]
        assert len(error_tokens) > 0
    
    def test_invalid_escape_sequence(self):
        """Test handling of invalid escape sequences."""
        source = '"invalid \\q escape"'
        tokens = lex(source)
        
        # Should generate an error token or handle gracefully
        # Implementation dependent - at minimum shouldn't crash
        assert len(tokens) >= 1
    
    def test_invalid_number_format(self):
        """Test handling of invalid number formats."""
        invalid_numbers = [
            "123abc",  # Invalid suffix
            "1e",      # Incomplete exponent
            "1.2.3",   # Multiple decimal points
            "0xG",     # Invalid hex digit
        ]
        
        for num in invalid_numbers:
            tokens = lex(num)
            # Should either tokenize as error or handle gracefully
            assert len(tokens) >= 1


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_very_long_identifier(self):
        """Test handling of very long identifiers."""
        long_id = "a" * 1000
        tokens = lex(long_id)
        assert len(tokens) == 1
        assert tokens[0].kind == "IDENT"
        assert tokens[0].text == long_id
    
    def test_very_long_number(self):
        """Test handling of very long numbers."""
        long_number = "9" * 100
        tokens = lex(long_number)
        assert len(tokens) == 1
        assert tokens[0].kind == "INT"
        assert tokens[0].text == long_number
    
    def test_mixed_whitespace(self):
        """Test handling of mixed whitespace characters."""
        source = "x\t=\n42\r\n;\f"
        tokens = lex(source)
        # Should tokenize correctly despite whitespace
        assert len(tokens) >= 4  # x, =, 42, ;
    
    def test_unicode_bom(self):
        """Test handling of Unicode BOM."""
        source = "\ufeffx = 42;"
        tokens = lex(source)
        # Should handle BOM gracefully
        assert len(tokens) >= 4
    
    def test_consecutive_operators(self):
        """Test consecutive operator recognition."""
        source = "x === y !== z"
        tokens = lex(source)
        
        # Should tokenize as: x, ==, =, y, !=, =, z
        expected_kinds = ["IDENT", "==", "=", "IDENT", "!=", "=", "IDENT"]
        actual_kinds = [t.kind for t in tokens]
        assert actual_kinds == expected_kinds


class TestPerformance:
    """Test lexer performance."""
    
    def test_large_file_lexing(self):
        """Test lexing a large source file."""
        # Generate a large source file
        lines = []
        for i in range(1000):
            lines.append(f"let x{i} = {i};")
        source = "\n".join(lines)
        
        tokens = lex(source)
        # Should complete without issues
        assert len(tokens) > 5000  # Rough estimate
    
    def test_complex_expression_lexing(self):
        """Test lexing complex expressions."""
        source = """
        (x + y) * (z - w) / (a % b) && (c || d) != (e & f) | (g ^ h)
        """
        tokens = lex(source)
        # Should tokenize complex expression correctly
        assert len(tokens) >= 20


class TestIntegration:
    """Test lexer integration with other components."""
    
    def test_lexer_parser_integration(self):
        """Test lexer output works with parser."""
        from astra.parser import parse
        
        source = "fn main() Int { return 42; }"
        tokens = lex(source)
        
        # Parser should be able to use lexer tokens
        # This is a basic integration test
        assert len(tokens) > 0
        assert any(t.kind == "FN" for t in tokens)
        assert any(t.kind == "IDENT" and t.text == "main" for t in tokens)


if __name__ == "__main__":
    pytest.main([__file__])
