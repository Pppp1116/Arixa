"""Enhanced error reporting system for ASTRA compiler.

Provides improved error messages with context, suggestions, and better formatting
to help developers understand and fix issues in their ASTRA code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from pathlib import Path
import re


@dataclass
class ErrorSuggestion:
    """A suggestion for fixing an error."""
    action: str
    description: str
    code_example: Optional[str] = None


@dataclass
class ErrorContext:
    """Context information for an error."""
    line_content: str
    column_highlight: str
    nearby_lines: List[str]
    function_name: Optional[str] = None
    module_name: Optional[str] = None


@dataclass
class EnhancedError:
    """Enhanced error with context and suggestions."""
    error_type: str
    message: str
    filename: str
    line: int
    col: int
    context: ErrorContext
    suggestions: List[ErrorSuggestion]
    severity: str = "error"  # error, warning, info
    error_code: Optional[str] = None


class ErrorReporter:
    """Enhanced error reporting system."""
    
    def __init__(self, max_context_lines: int = 3):
        self.max_context_lines = max_context_lines
        self.error_patterns = self._initialize_error_patterns()
    
    def _initialize_error_patterns(self) -> dict[str, dict]:
        """Initialize common error patterns with suggestions."""
        return {
            "expected_token": {
                "suggestions": [
                    ErrorSuggestion(
                        "Check syntax",
                        "Verify that you have the correct token at this position",
                        "fn main() -> Int { return 0; }"
                    ),
                    ErrorSuggestion(
                        "Add missing token",
                        "Add the expected token to fix the syntax error"
                    )
                ]
            },
            "undefined_name": {
                "suggestions": [
                    ErrorSuggestion(
                        "Check spelling",
                        "Verify the name is spelled correctly"
                    ),
                    ErrorSuggestion(
                        "Import missing module",
                        "Add the appropriate import statement",
                        "import std.str;"
                    ),
                    ErrorSuggestion(
                        "Declare variable",
                        "Declare the variable before using it",
                        "let x = 42;"
                    )
                ]
            },
            "type_mismatch": {
                "suggestions": [
                    ErrorSuggestion(
                        "Check types",
                        "Verify the types match the expected signature"
                    ),
                    ErrorSuggestion(
                        "Add type conversion",
                        "Use explicit type conversion if needed",
                        "value as Int"
                    )
                ]
            },
            "borrow_checker": {
                "suggestions": [
                    ErrorSuggestion(
                        "Check ownership",
                        "Review ownership and borrowing rules"
                    ),
                    ErrorSuggestion(
                        "Clone the value",
                        "Clone the value to avoid moving it",
                        "value.clone()"
                    ),
                    ErrorSuggestion(
                        "Use reference",
                        "Use a reference instead of moving the value",
                        "&value"
                    )
                ]
            },
            "mutability_conflict": {
                "suggestions": [
                    ErrorSuggestion(
                        "Declare as mutable",
                        "Add 'mut' to the variable declaration",
                        "mut x = 42;"
                    ),
                    ErrorSuggestion(
                        "Use immutable reference",
                        "Use an immutable reference instead",
                        "&x instead of &mut x"
                    )
                ]
            }
        }
    
    def create_enhanced_error(
        self,
        error_type: str,
        message: str,
        filename: str,
        line: int,
        col: int,
        source_lines: List[str],
        severity: str = "error",
        error_code: Optional[str] = None
    ) -> EnhancedError:
        """Create an enhanced error with context and suggestions."""
        
        # Extract context
        context = self._extract_context(source_lines, line, col)
        
        # Get suggestions based on error type
        suggestions = self._get_suggestions(error_type, message)
        
        return EnhancedError(
            error_type=error_type,
            message=message,
            filename=filename,
            line=line,
            col=col,
            context=context,
            suggestions=suggestions,
            severity=severity,
            error_code=error_code
        )
    
    def _extract_context(self, source_lines: List[str], line: int, col: int) -> ErrorContext:
        """Extract context information for an error."""
        # Adjust for 0-based indexing
        line_idx = line - 1
        
        # Get the current line content
        current_line = source_lines[line_idx] if 0 <= line_idx < len(source_lines) else ""
        
        # Create column highlight
        col_highlight = " " * col + "^"
        
        # Get nearby lines for context
        start = max(0, line_idx - self.max_context_lines)
        end = min(len(source_lines), line_idx + self.max_context_lines + 1)
        nearby_lines = source_lines[start:end]
        
        return ErrorContext(
            line_content=current_line,
            column_highlight=col_highlight,
            nearby_lines=nearby_lines
        )
    
    def _get_suggestions(self, error_type: str, message: str) -> List[ErrorSuggestion]:
        """Get suggestions based on error type and message."""
        suggestions = []
        
        # Get base suggestions for error type
        pattern = self.error_patterns.get(error_type, {})
        suggestions.extend(pattern.get("suggestions", []))
        
        # Add message-specific suggestions
        message_suggestions = self._analyze_message_for_suggestions(message)
        suggestions.extend(message_suggestions)
        
        return suggestions[:3]  # Limit to top 3 suggestions
    
    def _analyze_message_for_suggestions(self, message: str) -> List[ErrorSuggestion]:
        """Analyze error message to generate specific suggestions."""
        suggestions = []
        
        # Common patterns in error messages
        if "expected" in message.lower() and "got" in message.lower():
            suggestions.append(ErrorSuggestion(
                "Check syntax",
                "Review the syntax at this position for missing or incorrect tokens"
            ))
        
        if "undefined" in message.lower() or "not found" in message.lower():
            suggestions.append(ErrorSuggestion(
                "Check name scope",
                "Ensure the name is in scope and correctly spelled"
            ))
        
        if "type" in message.lower() and "mismatch" in message.lower():
            suggestions.append(ErrorSuggestion(
                "Type conversion",
                "Consider adding explicit type conversion"
            ))
        
        if "borrow" in message.lower() or "move" in message.lower():
            suggestions.append(ErrorSuggestion(
                "Ownership rules",
                "Review ASTRA's ownership and borrowing system"
            ))
        
        return suggestions
    
    def format_error(self, error: EnhancedError) -> str:
        """Format an enhanced error for display."""
        lines = []
        
        # Header with severity and location
        severity_symbol = {
            "error": "❌",
            "warning": "⚠️", 
            "info": "ℹ️"
        }.get(error.severity, "❌")
        
        lines.append(f"{severity_symbol} {error.severity.upper()}: {error.error_type}")
        lines.append(f"   📍 {error.filename}:{error.line}:{error.col}")
        lines.append("")
        
        # Context
        lines.append("📄 Context:")
        for i, nearby_line in enumerate(error.context.nearby_lines):
            line_num = error.line - len(error.context.nearby_lines) + i + 1
            if line_num == error.line:
                lines.append(f"{line_num:4d} | {nearby_line}")
                lines.append(f"     | {error.context.column_highlight}")
            else:
                lines.append(f"{line_num:4d} | {nearby_line}")
        
        lines.append("")
        
        # Error message
        lines.append(f"💬 {error.message}")
        lines.append("")
        
        # Suggestions
        if error.suggestions:
            lines.append("💡 Suggestions:")
            for i, suggestion in enumerate(error.suggestions, 1):
                lines.append(f"   {i}. {suggestion.action}")
                lines.append(f"      {suggestion.description}")
                if suggestion.code_example:
                    lines.append(f"      Example: `{suggestion.code_example}`")
                lines.append("")
        
        # Error code if available
        if error.error_code:
            lines.append(f"🔍 Error code: {error.error_code}")
            lines.append(f"   Learn more: https://astra-lang.dev/errors/{error.error_code}")
        
        return "\n".join(lines)
    
    def format_multiple_errors(self, errors: List[EnhancedError]) -> str:
        """Format multiple errors for display."""
        if not errors:
            return ""
        
        lines = []
        lines.append(f"Found {len(errors)} {'error' if len(errors) == 1 else 'errors'}:")
        lines.append("")
        
        for i, error in enumerate(errors, 1):
            lines.append(f"--- Error {i} ---")
            lines.append(self.format_error(error))
            if i < len(errors):
                lines.append("")
        
        return "\n".join(lines)


def _diag(
    error_type: str,
    filename: str,
    line: int,
    col: int,
    message: str,
    severity: str = "error",
    error_code: Optional[str] = None
) -> str:
    """Create a diagnostic message with enhanced formatting."""
    return f"{error_type.upper()} {filename}:{line}:{col}: {message}"


def enhance_error_message(
    original_error: str,
    error_type: str,
    filename: str,
    line: int,
    col: int,
    source_content: str
) -> str:
    """Enhance an existing error message with context and suggestions."""
    reporter = ErrorReporter()
    source_lines = source_content.splitlines()
    
    enhanced_error = reporter.create_enhanced_error(
        error_type=error_type,
        message=original_error,
        filename=filename,
        line=line,
        col=col,
        source_lines=source_lines
    )
    
    return reporter.format_error(enhanced_error)
