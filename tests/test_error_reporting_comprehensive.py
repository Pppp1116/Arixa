"""Comprehensive tests for the current enhanced error-reporting module."""

from __future__ import annotations

from astra.error_reporting import (
    ErrorContext,
    ErrorReporter,
    ErrorSuggestion,
    EnhancedError,
    enhance_error_message,
)


def test_error_reporter_defaults() -> None:
    reporter = ErrorReporter()
    assert reporter.max_context_lines == 3
    assert "type_mismatch" in reporter.error_patterns


def test_create_enhanced_error_and_context() -> None:
    reporter = ErrorReporter(max_context_lines=2)
    src = ["fn main() Int {", "    x = 1", "    return x", "}"]
    err = reporter.create_enhanced_error(
        error_type="syntax_error",
        message="expected ';'",
        filename="sample.arixa",
        line=2,
        col=8,
        source_lines=src,
        error_code="PARSE001",
    )
    assert isinstance(err, EnhancedError)
    assert err.filename == "sample.arixa"
    assert err.line == 2 and err.col == 8
    assert err.error_code == "PARSE001"
    assert isinstance(err.context, ErrorContext)
    assert err.context.line_content == "    x = 1"
    assert err.context.column_highlight.endswith("^")


def test_suggestions_from_type_and_message_patterns() -> None:
    reporter = ErrorReporter()
    suggestions = reporter._get_suggestions("type_mismatch", "Type mismatch: expected Int but got String")
    assert suggestions
    actions = {s.action for s in suggestions}
    assert "Check types" in actions or "Type conversion" in actions


def test_format_error_contains_sections() -> None:
    reporter = ErrorReporter()
    src = ["fn main() Int {", "    return nope", "}"]
    err = reporter.create_enhanced_error(
        error_type="undefined_name",
        message="undefined name nope",
        filename="u.arixa",
        line=2,
        col=12,
        source_lines=src,
        error_code="E0101",
    )
    formatted = reporter.format_error(err)
    assert "ERROR" in formatted
    assert "u.arixa:2:12" in formatted
    assert "undefined name nope" in formatted
    assert "Suggestions" in formatted
    assert "Error code: E0101" in formatted


def test_format_multiple_errors_lists_all_items() -> None:
    reporter = ErrorReporter()
    src = ["fn main() Int {", "    return 0", "}"]
    e1 = reporter.create_enhanced_error("syntax_error", "missing ;", "a.arixa", 2, 5, src)
    e2 = reporter.create_enhanced_error("type_mismatch", "bad type", "a.arixa", 2, 12, src)
    out = reporter.format_multiple_errors([e1, e2])
    assert "Found 2 errors" in out
    assert "--- Error 1 ---" in out
    assert "--- Error 2 ---" in out


def test_custom_suggestions_are_rendered() -> None:
    reporter = ErrorReporter()
    src = ["fn main() Int {", "    return missing()", "}"]
    err = reporter.create_enhanced_error("undefined_name", "missing function", "m.arixa", 2, 12, src)
    err.suggestions.append(
        ErrorSuggestion(
            action="Define function",
            description="Add function before use",
            code_example="fn missing() Int{ return 0; }",
        )
    )
    out = reporter.format_error(err)
    assert "Define function" in out
    assert "fn missing() Int{ return 0; }" in out


def test_enhance_error_message_wrapper() -> None:
    src = "fn main() Int{\n  return x;\n}\n"
    out = enhance_error_message(
        original_error="undefined name x",
        error_type="undefined_name",
        filename="wrap.arixa",
        line=2,
        col=10,
        source_content=src,
    )
    assert "wrap.arixa:2:10" in out
    assert "undefined name x" in out
