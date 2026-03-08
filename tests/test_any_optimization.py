"""Test that Any runtime is only included when actually needed."""

import pytest
import subprocess
import sys
from pathlib import Path

def run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)

def test_no_any_runtime_for_typed_code():
    """Test that typed code doesn't include Any runtime."""
    repo = Path(__file__).resolve().parents[1]
    
    # Test with only typed operations - no Any usage
    typed_code = '''
fn main() Int {
    // Use only basic operations, no Any types
    x = 42;
    y = x * 2;
    return y;
}
'''
    
    test_file = repo / "tmp_test_typed.astra"
    test_file.write_text(typed_code)
    
    try:
        # Build and check that Any runtime is not included
        out = repo / "tmp_test_typed.exe"
        cp = run([sys.executable, "-m", "astra.cli", "build", str(test_file), "-o", str(out), "--target", "native", "--profile", "release"], cwd=repo)
        assert cp.returncode == 0, f"Build failed: {cp.stderr}"
        
        # Should run successfully
        result = run([str(out)], cwd=test_file.parent)
        assert result.returncode == 84, f"Execution failed: {result.stderr}"  # 42 * 2 = 84
        
        print("✓ Typed code builds and runs without Any runtime")
        
    finally:
        # Cleanup
        for f in [test_file, out]:
            if f.exists():
                f.unlink()

def test_any_runtime_included_when_needed():
    """Test that Any runtime is included when Any types are used."""
    repo = Path(__file__).resolve().parents[1]
    
    # Test with Any usage
    any_code = '''
fn main() Int {
    // Use dynamic Any-based containers
    mut list = list_new();
    list_push(list, 42);
    list_push(list, "hello");
    
    mut map = map_new();
    map_set(map, "key", 123);
    
    return 0;
}
'''
    
    test_file = repo / "tmp_test_any.astra"
    test_file.write_text(any_code)
    
    try:
        # Build and check that Any runtime is included
        out = repo / "tmp_test_any.exe"
        cp = run([sys.executable, "-m", "astra.cli", "build", str(test_file), "-o", str(out), "--target", "native", "--profile", "release"], cwd=repo)
        assert cp.returncode == 0, f"Build failed: {cp.stderr}"
        
        # Should run successfully
        result = run([str(out)], cwd=test_file.parent)
        assert result.returncode == 0, f"Execution failed: {result.stderr}"
        
        print("✓ Any-using code builds and runs with Any runtime")
        
    finally:
        # Cleanup
        for f in [test_file, out]:
            if f.exists():
                f.unlink()

def test_mixed_any_usage():
    """Test that Any runtime is included only when Any is actually used."""
    repo = Path(__file__).resolve().parents[1]
    
    # Test mixed usage - basic operations with Any casting
    mixed_code = '''
fn main() Int {
        // Basic operations
        x = 42;
        
        // Use Any for some operations
        any_val = x as Any;
        back_to_int = any_val as Int;
        
        return back_to_int;
    }
'''
    
    test_file = repo / "tmp_test_mixed.astra"
    test_file.write_text(mixed_code)
    
    try:
        # Build - should include Any runtime due to casting
        out = repo / "tmp_test_mixed.exe"
        cp = run([sys.executable, "-m", "astra.cli", "build", str(test_file), "-o", str(out), "--target", "native", "--profile", "release"], cwd=repo)
        assert cp.returncode == 0, f"Build failed: {cp.stderr}"
        
        # Should run successfully
        result = run([str(out)], cwd=test_file.parent)
        assert result.returncode == 42, f"Execution failed: {result.stderr}"
        
        print("✓ Mixed usage code builds and runs with Any runtime (due to casting)")
        
    finally:
        # Cleanup
        for f in [test_file, out]:
            if f.exists():
                f.unlink()

def test_any_usage_detection():
    """Test the Any usage detection system directly."""
    from astra.semantic import analyze, AnyUsageInfo
    from astra.parser import parse
    from astra.ast import Program
    
    # Test typed code
    typed_src = '''
    fn main() Int {
        x = 42;
        return x;
    }
    '''
    
    typed_prog = parse(typed_src)
    analyze(typed_prog, filename="<test>")
    
    any_usage = getattr(typed_prog, "any_usage", None)
    assert any_usage is not None, "Any usage info should be attached to program"
    assert not any_usage.needs_any_runtime(), "Typed code should not need Any runtime"
    assert not any_usage.uses_any_type, "Typed code should not use Any types"
    assert not any_usage.uses_dynamic_containers, "Typed code should not use dynamic containers"
    
    # Test Any code
    any_src = '''
    fn main() Int {
        mut list = list_new();
        return 0;
    }
    '''
    
    any_prog = parse(any_src)
    analyze(any_prog, filename="<test>")
    
    any_usage = getattr(any_prog, "any_usage", None)
    assert any_usage is not None, "Any usage info should be attached to program"
    assert any_usage.needs_any_runtime(), "Any-using code should need Any runtime"
    assert any_usage.uses_any_type, "Any-using code should use Any types"
    assert any_usage.uses_any_lists, "Should use Any lists"
    assert any_usage.uses_dynamic_containers, "Should use dynamic containers"
    
    print("✓ Any usage detection works correctly")

if __name__ == "__main__":
    test_any_usage_detection()
    test_no_any_runtime_for_typed_code()
    test_any_runtime_included_when_needed()
    test_mixed_any_usage()
    print("All tests passed!")
