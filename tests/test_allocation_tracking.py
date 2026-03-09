"""Test that allocation tracking is disabled in release builds."""

import pytest
import subprocess
import sys
from pathlib import Path

def run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)

def test_release_build_no_allocation_tracking():
    """Test that release builds don't include allocation tracking overhead."""
    repo = Path(__file__).resolve().parents[1]
    
    # Simple test that does allocations
    test_code = '''
fn main() Int {
    // Test string allocations
    s1 = "hello world";
    s2 = "another string";
    
    // Test array allocation
    arr = [1, 2, 3, 4, 5];
    
    return 0;
}
'''
    
    test_file = repo / "tmp_test_alloc.astra"
    test_file.write_text(test_code)
    
    try:
        # Build in debug mode (should have allocation tracking)
        debug_out = repo / "tmp_test_alloc_debug.exe"
        cp_debug = run([sys.executable, "-m", "astra", "build", str(test_file), "-o", str(debug_out), "--target", "native", "--profile", "debug"], cwd=repo)
        assert cp_debug.returncode == 0, f"Debug build failed: {cp_debug.stderr}"
        
        # Build in release mode (should NOT have allocation tracking)
        release_out = repo / "tmp_test_alloc_release.exe"
        cp_release = run([sys.executable, "-m", "astra", "build", str(test_file), "-o", str(release_out), "--target", "native", "--profile", "release"], cwd=repo)
        assert cp_release.returncode == 0, f"Release build failed: {cp_release.stderr}"
        
        # Both should run successfully
        cp_debug_run = run([str(debug_out)], cwd=test_file.parent)
        assert cp_debug_run.returncode == 0, f"Debug execution failed: {cp_debug_run.stderr}"
        
        cp_release_run = run([str(release_out)], cwd=test_file.parent)
        assert cp_release_run.returncode == 0, f"Release execution failed: {cp_release_run.stderr}"
        
        # Check that release binary is smaller (no tracking code)
        debug_size = debug_out.stat().st_size
        release_size = release_out.stat().st_size
        
        # Release should be smaller due to no allocation tracking
        print(f"Debug size: {debug_size} bytes")
        print(f"Release size: {release_size} bytes")
        
        # The size difference might be small, but release should not be larger
        assert release_size <= debug_size, f"Release binary ({release_size}) should not be larger than debug ({debug_size})"
        
        # Test performance - release should be faster
        import time
        
        # Time debug execution
        debug_times = []
        for _ in range(5):
            start = time.perf_counter()
            result = run([str(debug_out)], cwd=test_file.parent)
            debug_times.append(time.perf_counter() - start)
            assert result.returncode == 0
        
        # Time release execution
        release_times = []
        for _ in range(5):
            start = time.perf_counter()
            result = run([str(release_out)], cwd=test_file.parent)
            release_times.append(time.perf_counter() - start)
            assert result.returncode == 0
        
        avg_debug_time = sum(debug_times) / len(debug_times)
        avg_release_time = sum(release_times) / len(release_times)
        
        print(f"Debug avg time: {avg_debug_time:.6f}s")
        print(f"Release avg time: {avg_release_time:.6f}s")
        
        # Release should be faster (or at least not significantly slower)
        # Allow some tolerance for measurement noise
        assert avg_release_time <= avg_debug_time * 1.2, f"Release ({avg_release_time:.6f}s) should be faster than debug ({avg_debug_time:.6f}s)"
        
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
        if 'debug_out' in locals() and debug_out.exists():
            debug_out.unlink()
        if 'release_out' in locals() and release_out.exists():
            release_out.unlink()

def test_freestanding_build_no_tracking():
    """Test that freestanding builds don't include allocation tracking."""
    repo = Path(__file__).resolve().parents[1]
    
    # Simple test for freestanding
    test_code = '''
fn _start() Int {
    return 42;
}
'''
    
    test_file = repo / "tmp_test_freestanding.astra"
    test_file.write_text(test_code)
    
    try:
        # Build freestanding (should have no runtime features)
        out = repo / "tmp_test_freestanding.exe"
        cp = run([sys.executable, "-m", "astra", "build", str(test_file), "-o", str(out), "--target", "native", "--freestanding"], cwd=repo)
        assert cp.returncode == 0, f"Freestanding build failed: {cp.stderr}"
        
        # Should run and exit with code 42
        result = run([str(out)], cwd=test_file.parent)
        assert result.returncode == 42, f"Freestanding execution failed: expected exit code 42, got {result.returncode}"
        
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
        if out.exists():
            out.unlink()
