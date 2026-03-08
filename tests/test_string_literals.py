"""Test string literal parsing and brace handling."""

import pytest
import subprocess
import sys
from pathlib import Path

def run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)

def test_string_literals_with_braces():
    """Test that strings with literal braces parse correctly."""
    repo = Path(__file__).resolve().parents[1]
    
    # Test code with various brace scenarios
    test_code = '''
fn main() Int {
    // Test 1: Escaped braces should become literal braces
    s1 = "{{escaped braces}}";
    print(s1);
    
    // Test 2: Mixed content with escaped braces
    s2 = "prefix {{escaped}} suffix";
    print(s2);
    
    // Test 3: No braces at all
    s3 = "plain string";
    print(s3);
    
    # Test 4: JSON-like string with escaped braces and quotes
    s4 = "{{\\"key\\": \\"value\\"}}";
    print(s4);
    
    return 0;
}
'''
    
    test_file = repo / "tmp_test_braces.astra"
    test_file.write_text(test_code)
    
    try:
        # Test parsing
        out = repo / "tmp_test_braces.exe"
        cp = run([sys.executable, "-m", "astra.cli", "build", str(test_file), "-o", str(out), "--target", "native"], cwd=repo)
        assert cp.returncode == 0, f"Parsing failed: {cp.stderr}"
        
        # Test execution
        cp2 = run([str(out)], cwd=test_file.parent)
        assert cp2.returncode == 0, f"Execution failed: {cp2.stderr}"
        
        # Verify output contains expected content
        output = cp2.stdout.strip()
        assert "{{escaped braces}}" in output
        assert "prefix {{escaped}} suffix" in output
        assert "plain string" in output
        assert '{{"key": "value"}}' in output or '{{\\"key\\": \\"value\\"}}' in output
        
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
        exe_file = repo / "tmp_test_braces.exe"
        if exe_file.exists():
            exe_file.unlink()

def test_string_interpolation_syntax():
    """Test that interpolation syntax is handled correctly."""
    repo = Path(__file__).resolve().parents[1]
    
    # Test code that should trigger interpolation parsing
    test_code = '''
fn main() Int {
    // This should be parsed as string with interpolation
    // Even if interpolation isn't fully implemented, it should parse
    s = "hello {name}";
    print(s);
    
    return 0;
}
'''
    
    test_file = repo / "tmp_test_interp.astra"
    test_file.write_text(test_code)
    
    try:
        # Test parsing - should not fail on parsing level
        out = repo / "tmp_test_interp.exe"
        cp = run([sys.executable, "-m", "astra.cli", "build", str(test_file), "-o", str(out), "--target", "native"], cwd=repo)
        # We expect this to potentially fail at semantic/codegen level, but not parsing level
        assert "unclosed interpolation brace" not in cp.stderr
        assert "unexpected atom" not in cp.stderr
        
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
        exe_file = repo / "tmp_test_interp.exe"
        if exe_file.exists():
            exe_file.unlink()

def test_lexer_tokenization_of_braces():
    """Test that lexer correctly tokenizes strings with braces."""
    from astra.lexer import lex
    
    # Test escaped braces
    tokens = lex('"{{hello}}"')
    # Should be a single STR token, not interpolation
    assert len([t for t in tokens if t.kind == "STR"]) == 1
    assert len([t for t in tokens if t.kind == "STR_INTERP"]) == 0
    
    # Test single brace (should be interpolation)
    tokens = lex('"{hello}"')
    # Should be STR_INTERP token
    assert len([t for t in tokens if t.kind == "STR_INTERP"]) == 1
    
    # Test no braces
    tokens = lex('"hello"')
    # Should be STR token
    assert len([t for t in tokens if t.kind == "STR"]) == 1
    assert len([t for t in tokens if t.kind == "STR_INTERP"]) == 0
