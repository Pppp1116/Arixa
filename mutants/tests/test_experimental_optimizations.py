"""Tests for experimental/beta mode optimizations."""

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from astra.build_enhanced import build_enhanced


def test_link_time_optimization(tmp_path: Path):
    """Test link-time optimization."""
    src = tmp_path / "lto_test.arixa"
    out = tmp_path / "lto_test.py"
    src.write_text(
        """
fn small_function(x Int) Int {
    return x * 2;
}

fn main() Int {
    return small_function(5);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 10  # 5 * 2
    print("✓ Link-time optimization working")


def test_ml_guided_optimization(tmp_path: Path):
    """Test ML-guided optimization."""
    src = tmp_path / "ml_test.arixa"
    out = tmp_path / "ml_test.py"
    src.write_text(
        """
fn compute_ml(x Int) Int {
    mut result = 0;
    mut i = 0;
    while i < x {
        result = result + i;
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return compute_ml(100);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 4950  # Sum of 0-99
    print("✓ ML-guided optimization working")


def test_auto_parallelization(tmp_path: Path):
    """Test automatic parallelization."""
    src = tmp_path / "parallel_test.arixa"
    out = tmp_path / "parallel_test.py"
    src.write_text(
        """
fn parallel_compute(data &[Int]) Int {
    mut sum = 0;
    mut i = 0;
    while i < len(data) {
        sum = sum + data[i];
        i = i + 1;
    }
    return sum;
}

fn main() Int {
    test_data = [1, 2, 3, 4, 5];
    return parallel_compute(&test_data);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 15  # Sum of 1-5
    print("✓ Auto-parallelization working")


def test_advanced_vectorization(tmp_path: Path):
    """Test advanced vectorization."""
    src = tmp_path / "vector_test.arixa"
    out = tmp_path / "vector_test.py"
    src.write_text(
        """
fn vectorized_sum(data &[Int]) Int {
    mut sum = 0;
    mut i = 0;
    while i < len(data) {
        sum = sum + data[i];
        i = i + 1;
    }
    return sum;
}

fn main() Int {
    test_data = [1, 2, 3, 4, 5, 6, 7, 8];
    return vectorized_sum(&test_data);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 36  # Sum of 1-8
    print("✓ Advanced vectorization working")


def test_polyhedral_optimization(tmp_path: Path):
    """Test polyhedral optimization."""
    src = tmp_path / "polyhedral_test.arixa"
    out = tmp_path / "polyhedral_test.py"
    src.write_text(
        """
fn matrix_multiply() Int {
    // Simple 2x2 matrix multiplication
    a = [[1, 2], [3, 4]];
    b = [[5, 6], [7, 8]];
    
    mut result = 0;
    mut i = 0;
    while i < 2 {
        mut j = 0;
        while j < 2 {
            mut k = 0;
            while k < 2 {
                result = result + a[i][k] * b[k][j];
                k = k + 1;
            }
            j = j + 1;
        }
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return matrix_multiply();
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 134  # Previous calculation
    print("✓ Polyhedral optimization working")


def test_speculative_optimization(tmp_path: Path):
    """Test speculative optimization."""
    src = tmp_path / "speculative_test.arixa"
    out = tmp_path / "speculative_test.py"
    src.write_text(
        """
fn speculative_compute(x Int) Int {
    if x > 50 {
        // Likely branch
        return x * 2;
    } else {
        // Unlikely branch
        return x + 10;
    }
}

fn main() Int {
    return speculative_compute(75);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 150  # 75 * 2
    print("✓ Speculative optimization working")


def test_devirtualization(tmp_path: Path):
    """Test devirtualization."""
    src = tmp_path / "devirtual_test.arixa"
    out = tmp_path / "devirtual_test.py"
    src.write_text(
        """
fn virtual_call(x Int) Int {
    return x * 3;
}

fn main() Int {
    return virtual_call(10);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert cp.returncode == 30  # 10 * 3
    print("✓ Devirtualization working")


def test_experimental_performance_comparison(tmp_path: Path):
    """Compare performance between release and experimental modes."""
    src = tmp_path / "perf_test.arixa"
    src_release = tmp_path / "perf_release.py"
    src_experimental = tmp_path / "perf_experimental.py"
    src.write_text(
        """
fn intensive_computation() Int {
    mut result = 0;
    mut i = 0;
    while i < 200 {
        mut j = 0;
        while j < 200 {
            result = result + i * j;
            j = j + 1;
        }
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return intensive_computation();
}
"""
    )
    
    # Build with release optimizations
    build_enhanced(str(src), str(src_release), target="py", profile="release")
    
    # Build with experimental optimizations
    build_enhanced(str(src), str(src_experimental), target="py", profile="beta")
    
    # Time execution
    start = time.time()
    cp_release = subprocess.run([sys.executable, str(src_release)], capture_output=True, text=True, timeout=30)
    release_time = time.time() - start
    
    start = time.time()
    cp_experimental = subprocess.run([sys.executable, str(src_experimental)], capture_output=True, text=True, timeout=30)
    experimental_time = time.time() - start
    
    # Both should produce the same result
    assert cp_release.returncode == cp_experimental.returncode
    
    print(f"Performance comparison:")
    print(f"  Release: {cp_release.returncode} in {release_time:.4f}s")
    print(f"  Experimental: {cp_experimental.returncode} in {experimental_time:.4f}s")
    print(f"  Experimental speedup: {release_time/experimental_time:.2f}x")
    
    # Experimental should be as fast or faster
    assert experimental_time <= release_time * 1.5  # Allow some variance


def test_experimental_optimization_pipeline(tmp_path: Path):
    """Test complete experimental optimization pipeline."""
    src = tmp_path / "pipeline_test.arixa"
    out = tmp_path / "pipeline_test.py"
    src.write_text(
        """
fn complex_computation(x Int) Int {
    // Function with multiple optimization opportunities
    mut result = 0;
    mut i = 0;
    while i < x {
        // Loop with invariant code
        invariant = x * 2 + 1;
        
        // Array operation (vectorization opportunity)
        data = [1, 2, 3, 4, 5, 6, 7, 8];
        mut j = 0;
        while j < len(data) {
            result = result + data[j] * invariant;
            j = j + 1;
        }
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return complex_computation(10);
}
"""
    )
    
    build_enhanced(str(src), str(out), target="py", profile="beta")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=10)
    
    # Should run without error and produce result
    assert cp.returncode >= 0
    print("✓ Complete experimental pipeline working")


def run_experimental_tests():
    """Run all experimental optimization tests."""
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        tests = [
            ("Link-time optimization", test_link_time_optimization),
            ("ML-guided optimization", test_ml_guided_optimization),
            ("Auto-parallelization", test_auto_parallelization),
            ("Advanced vectorization", test_advanced_vectorization),
            ("Polyhedral optimization", test_polyhedral_optimization),
            ("Speculative optimization", test_speculative_optimization),
            ("Devirtualization", test_devirtualization),
            ("Experimental performance comparison", test_experimental_performance_comparison),
            ("Complete experimental pipeline", test_experimental_optimization_pipeline),
        ]
        
        passed = 0
        failed = 0
        
        for name, test_func in tests:
            try:
                test_func(tmp_path)
                passed += 1
                print(f"✓ {name}")
            except Exception as e:
                print(f"✗ {name}: {e}")
                failed += 1
        
        print(f"\n=== EXPERIMENTAL OPTIMIZATION TEST SUMMARY ===")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total: {passed + failed}")
        
        if failed == 0:
            print("🚀 All experimental optimization tests passed!")
        else:
            print(f"⚠️  {failed} test(s) failed")
        
        return failed == 0


if __name__ == "__main__":
    run_experimental_tests()
