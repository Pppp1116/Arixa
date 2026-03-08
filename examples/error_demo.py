#!/usr/bin/env python3
"""
Demonstration script for ASTRA's enhanced error reporting system.

This script shows how the enhanced error reporting works with various
error types and provides examples of the formatted output.
"""

import sys
from pathlib import Path

# Add the astra module to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "astra"))

from error_reporting import ErrorReporter, EnhancedError, ErrorSuggestion, ErrorContext


def demo_basic_error_formatting():
    """Demonstrate basic error formatting."""
    print("=== Basic Error Formatting Demo ===\n")
    
    # Create sample source code
    source_code = """fn main() -> Int {
    let x = 42
    return x
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create a sample error
    error = reporter.create_enhanced_error(
        error_type="syntax_error",
        message="Expected ';' at end of statement",
        filename="example.arixa",
        line=2,
        col=14,
        source_lines=source_lines,
        error_code="PARSE001"
    )
    
    # Format and display the error
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_type_mismatch_error():
    """Demonstrate a type mismatch error with suggestions."""
    print("=== Type Mismatch Error Demo ===\n")
    
    source_code = """fn main() -> Int {
    let x = "hello"
    return x
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create a type mismatch error
    error = reporter.create_enhanced_error(
        error_type="type_mismatch",
        message="Expected return type 'Int' but found 'String'",
        filename="type_error.arixa",
        line=3,
        col=12,
        source_lines=source_lines,
        error_code="SEM102"
    )
    
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_borrow_checker_error():
    """Demonstrate a borrow checker error with detailed suggestions."""
    print("=== Borrow Checker Error Demo ===\n")
    
    source_code = """fn main() -> Int {
    let x = 42;
    let r1 = &x;
    let r2 = &mut x;
    return *r2;
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create a borrow checker error
    error = reporter.create_enhanced_error(
        error_type="borrow_checker",
        message="Cannot create mutable reference to `x` because it is already borrowed",
        filename="borrow_error.arixa",
        line=4,
        col=14,
        source_lines=source_lines,
        error_code="SEM200"
    )
    
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_multiple_errors():
    """Demonstrate formatting multiple errors."""
    print("=== Multiple Errors Demo ===\n")
    
    source_code = """fn main() -> Int {
    let x = "hello"
    let y = undefined_var
    return x
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create multiple errors
    errors = [
        reporter.create_enhanced_error(
            error_type="type_mismatch",
            message="Expected type 'Int' but found 'String'",
            filename="multi_error.arixa",
            line=2,
            col=13,
            source_lines=source_lines,
            error_code="SEM102"
        ),
        reporter.create_enhanced_error(
            error_type="undefined_name",
            message="Name 'undefined_var' is not defined in this scope",
            filename="multi_error.arixa",
            line=3,
            col=13,
            source_lines=source_lines,
            error_code="SEM101"
        )
    ]
    
    formatted_errors = reporter.format_multiple_errors(errors)
    print(formatted_errors)
    print()


def demo_warning_error():
    """Demonstrate a warning-level error."""
    print("=== Warning Error Demo ===\n")
    
    source_code = """fn main() -> Int {
    let unused = 42;
    return 42;
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create a warning
    error = reporter.create_enhanced_error(
        error_type="unused_variable",
        message="Variable 'unused' is declared but never used",
        filename="warning.arixa",
        line=2,
        col=9,
        source_lines=source_lines,
        severity="warning",
        error_code="WARN001"
    )
    
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_custom_suggestions():
    """Demonstrate custom error suggestions."""
    print("=== Custom Suggestions Demo ===\n")
    
    source_code = """fn main() -> Int {
    return some_function()
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter()
    
    # Create an error with custom suggestions
    error = reporter.create_enhanced_error(
        error_type="undefined_name",
        message="Name 'some_function' is not defined in this scope",
        filename="custom.arixa",
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
            code_example="fn some_function() -> Int { return 42; }"
        )
    ])
    
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_large_context():
    """Demonstrate error with larger context."""
    print("=== Large Context Demo ===\n")
    
    source_code = """fn calculate_average(numbers: Vec<Int>) -> Float {
    let sum = 0;
    for num in numbers {
        sum = sum + num;
    }
    let average = sum / len(numbers);
    return average;
}

fn main() -> Int {
    let numbers = [1, 2, 3, 4, 5];
    let result = calculate_average(numbers);
    print("Average: " + result);
    return 0;
}"""
    
    source_lines = source_code.splitlines()
    reporter = ErrorReporter(max_context_lines=5)
    
    # Create an error in the middle of the code
    error = reporter.create_enhanced_error(
        error_type="type_mismatch",
        message="Cannot add Int and Float in division",
        filename="context.arixa",
        line=6,
        col=20,
        source_lines=source_lines,
        error_code="SEM102"
    )
    
    formatted_error = reporter.format_error(error)
    print(formatted_error)
    print()


def demo_error_enhancement():
    """Demonstrate enhancing existing error messages."""
    print("=== Error Enhancement Demo ===\n")
    
    # Original basic error message
    original_error = "SEM example.arixa:3:12: Expected return type 'Int' but found 'String'"
    
    source_code = """fn main() -> Int {
    let x = "hello";
    return x;
}"""
    
    # Enhance the error message
    enhanced_error = enhance_error_message(
        original_error=original_error,
        error_type="type_mismatch",
        filename="example.arixa",
        line=3,
        col=12,
        source_content=source_code
    )
    
    print("Original error:")
    print(original_error)
    print("\nEnhanced error:")
    print(enhanced_error)
    print()


def main():
    """Run all demonstrations."""
    print("ASTRA Enhanced Error Reporting System Demo")
    print("=" * 50)
    print()
    
    demo_basic_error_formatting()
    demo_type_mismatch_error()
    demo_borrow_checker_error()
    demo_multiple_errors()
    demo_warning_error()
    demo_custom_suggestions()
    demo_large_context()
    demo_error_enhancement()
    
    print("=== Demo Complete ===")
    print("\nThe enhanced error reporting system provides:")
    print("• Clear, structured error messages")
    print("• Contextual code highlighting")
    print("• Actionable suggestions")
    print("• Consistent formatting")
    print("• Educational error codes")
    print("• Multiple error support")
    print("• Configurable context levels")


if __name__ == "__main__":
    main()
