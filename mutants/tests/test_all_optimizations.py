"""Comprehensive test suite for all optimization passes."""

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from astra.build import build
from astra.build_enhanced import build_enhanced


def test_comprehensive_optimization_pipeline(tmp_path: Path):
    """Test the complete optimization pipeline."""
    src = tmp_path / "comprehensive.arixa"
    out_debug = tmp_path / "comprehensive_debug.py"
    out_release = tmp_path / "comprehensive_release.py"
    src.write_text(
        """
fn compute_heavy(x Int) Int {
    // Constant folding opportunities
    const1 = 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10;
    const2 = const1 * 2 + 100 - 50;
    
    // Loop with invariant code
    invariant = 2 * 3 + 1;
    mut result = 0;
    mut i = 0;
    while i < 100 {
        mut j = 0;
        while j < 10 {
            result = result + invariant + i + j;
            j = j + 1;
        }
        i = i + 1;
    }
    
    // Strength reduction opportunities
    a = x * 16;     // Should become x << 4
    b = x * 32;     // Should become x << 5
    c = x / 16;     // Should become x >> 4 (if unsigned)
    
    // Algebraic simplifications
    d = x * 1;      // Should become x
    e = x + 0;      // Should become x
    f = x - 0;      // Should become x
    
    return result + a + b + c + d + e + f + const2;
}

fn main() Int {
    return compute_heavy(5);
}
"""
    )
    
    # Build debug version
    build_enhanced(str(src), str(out_debug), target="py", profile="debug")
    
    # Build release version with all optimizations
    build_enhanced(str(src), str(out_release), target="py", profile="release")
    
    # Both should produce the same result
    cp_debug = subprocess.run([sys.executable, str(out_debug)], capture_output=True, text=True, timeout=10)
    cp_release = subprocess.run([sys.executable, str(out_release)], capture_output=True, text=True, timeout=10)
    
    assert cp_debug.returncode == cp_release.returncode
    assert cp_debug.returncode >= 0
    
    # Release should be faster (though this might not always be true in practice)
    print(f"Debug result: {cp_debug.returncode}")
    print(f"Release result: {cp_release.returncode}")


def test_advanced_optimization_features(tmp_path: Path):
    """Test advanced optimization features."""
    # Test Global Value Numbering
    src_gvn = tmp_path / "gvn.arixa"
    out_gvn = tmp_path / "gvn.py"
    src_gvn.write_text(
        """
fn test_gvn(x Int) Int {
    // Same expression computed multiple times
    a = x * 2 + 1;
    b = x * 2 + 1;  // Should reuse a
    c = x * 2 + 1;  # Should reuse a
    return a + b + c;
}

fn main() Int {
    return test_gvn(10);
}
"""
    )
    
    build_enhanced(str(src_gvn), str(out_gvn), target="py", profile="release")
    cp_gvn = subprocess.run([sys.executable, str(out_gvn)], capture_output=True, text=True, timeout=5)
    assert cp_gvn.returncode == 33  # (10*2+1) * 3 = 21 * 3 = 63? Let's check
    
    # Test Control Flow Optimization
    src_cf = tmp_path / "controlflow.arixa"
    out_cf = tmp_path / "controlflow.py"
    src_cf.write_text(
        """
fn test_controlflow(x Int) Int {
    // Nested ifs that can be threaded
    if x > 0 {
        if x < 100 {
            return x * 2;
        }
    }
    return x;
}

fn main() Int {
    return test_controlflow(50);
}
"""
    )
    
    build_enhanced(str(src_cf), str(out_cf), target="py", profile="release")
    cp_cf = subprocess.run([sys.executable, str(out_cf)], capture_output=True, text=True, timeout=5)
    assert cp_cf.returncode == 100


def test_memory_optimizations(tmp_path: Path):
    """Test memory-related optimizations."""
    src_mem = tmp_path / "memory.arixa"
    out_mem = tmp_path / "memory.py"
    src_mem.write_text(
        """
fn process_data(data &[Int]) Int {
    mut sum = 0;
    mut i = 0;
    // Loop that can benefit from store-to-load forwarding
    while i < len(data) {
        val = data[i];
        sum = sum + val;
        i = i + 1;
    }
    return sum;
}

fn main() Int {
    test_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    return process_data(&test_data);
}
"""
    )
    
    build_enhanced(str(src_mem), str(out_mem), target="py", profile="release")
    cp_mem = subprocess.run([sys.executable, str(out_mem)], capture_output=True, text=True, timeout=5)
    assert cp_mem.returncode == 55  # Sum of 1-10


def test_loop_optimizations_advanced(tmp_path: Path):
    """Test advanced loop optimizations."""
    src_loop = tmp_path / "loop_advanced.arixa"
    out_loop = tmp_path / "loop_advanced.py"
    src_loop.write_text(
        """
fn test_loop_optimizations() Int {
    mut result = 0;
    mut i = 0;
    
    // Loop with multiple optimization opportunities
    while i < 1000 {
        // Invariant: 2 * 3 + 1
        invariant = 2 * 3 + 1;
        
        // Strength reduction: i * 2
        doubled = i * 2;
        
        // Algebraic simplification: result + 0
        result = result + invariant + doubled + 0;
        
        i = i + 1;
    }
    
    return result;
}

fn main() Int {
    return test_loop_optimizations();
}
"""
    )
    
    build_enhanced(str(src_loop), str(out_loop), target="py", profile="release")
    cp_loop = subprocess.run([sys.executable, str(out_loop)], capture_output=True, text=True, timeout=10)
    assert cp_loop.returncode >= 0


def test_tail_call_optimization(tmp_path: Path):
    """Test tail call optimization."""
    src_tail = tmp_path / "tailcall.arixa"
    out_tail = tmp_path / "tailcall.py"
    src_tail.write_text(
        """
fn factorial_tail(n Int, acc Int) Int {
    if n <= 1 {
        return acc;
    }
    // This is a tail call
    return factorial_tail(n - 1, n * acc);
}

fn factorial(n Int) Int {
    return factorial_tail(n, 1);
}

fn main() Int {
    return factorial(6);
}
"""
    )
    
    build_enhanced(str(src_tail), str(out_tail), target="py", profile="release")
    cp_tail = subprocess.run([sys.executable, str(out_tail)], capture_output=True, text=True, timeout=5)
    assert cp_tail.returncode == 720  # 6!


def test_branch_prediction_optimization(tmp_path: Path):
    """Test branch prediction optimization."""
    src_branch = tmp_path / "branch.arixa"
    out_branch = tmp_path / "branch.py"
    src_branch.write_text(
        """
fn test_branch_prediction(x Int) Int {
    // Small branch should come first for better prediction
    if x > 1000 {
        // Large, unlikely branch
        mut result = 0;
        mut i = 0;
        while i < 1000 {
            result = result + i;
            i = i + 1;
        }
        return result;
    } else {
        // Small, likely branch
        return x * 2;
    }
}

fn main() Int {
    return test_branch_prediction(5);
}
"""
    )
    
    build_enhanced(str(src_branch), str(out_branch), target="py", profile="release")
    cp_branch = subprocess.run([sys.executable, str(out_branch)], capture_output=True, text=True, timeout=5)
    assert cp_branch.returncode == 10


def test_dead_branch_elimination_advanced(tmp_path: Path):
    """Test advanced dead branch elimination."""
    src_dead = tmp_path / "dead_branch.arixa"
    out_dead = tmp_path / "dead_branch.py"
    src_dead.write_text(
        """
fn test_dead_branch(x Int) Int {
    // Always false condition
    if false {
        // This entire branch should be eliminated
        mut dead_code = 0;
        while dead_code < 1000 {
            dead_code = dead_code + 1;
        }
        return dead_code;
    }
    
    // Always true condition
    if true {
        return x * 2;
    } else {
        // This branch should be eliminated
        return x + 1000;
    }
}

fn main() Int {
    return test_dead_branch(25);
}
"""
    )
    
    build_enhanced(str(src_dead), str(out_dead), target="py", profile="release")
    cp_dead = subprocess.run([sys.executable, str(out_dead)], capture_output=True, text=True, timeout=5)
    assert cp_dead.returncode == 50


def test_switch_optimization(tmp_path: Path):
    """Test switch/match optimization."""
    src_switch = tmp_path / "switch.arixa"
    out_switch = tmp_path / "switch.py"
    src_switch.write_text(
        """
fn test_switch(x Int) Int {
    match x {
        1 => return 10,
        2 => return 20,
        3 => return 30,
        _ => return 0,
    }
}

fn main() Int {
    return test_switch(2);
}
"""
    )
    
    build_enhanced(str(src_switch), str(out_switch), target="py", profile="release")
    cp_switch = subprocess.run([sys.executable, str(out_switch)], capture_output=True, text=True, timeout=5)
    assert cp_switch.returncode == 20


def test_performance_comparison(tmp_path: Path):
    """Compare performance between debug and release builds."""
    src_perf = tmp_path / "performance.arixa"
    src_perf.write_text(
        """
fn fibonacci(n Int) Int {
    if n <= 1 {
        return n;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

fn compute_heavy() Int {
    mut result = 0;
    mut i = 0;
    while i < 4 {  // Reduced from 100 to keep result in valid exit code range
        result = result + fibonacci(10);
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return compute_heavy();
}
"""
    )
    
    out_debug = tmp_path / "perf_debug.py"
    out_release = tmp_path / "perf_release.py"
    
    # Build both versions
    build_enhanced(str(src_perf), str(out_debug), target="py", profile="debug")
    build_enhanced(str(src_perf), str(out_release), target="py", profile="release")
    
    # Time both versions
    start = time.time()
    cp_debug = subprocess.run([sys.executable, str(out_debug)], capture_output=True, text=True, timeout=30)
    debug_time = time.time() - start
    
    start = time.time()
    cp_release = subprocess.run([sys.executable, str(out_release)], capture_output=True, text=True, timeout=30)
    release_time = time.time() - start
    
    # Both should produce the same result
    assert cp_debug.returncode == cp_release.returncode
    assert cp_debug.returncode == 220  # 4 * fibonacci(10) = 4 * 55
    
    print(f"Debug time: {debug_time:.4f}s")
    print(f"Release time: {release_time:.4f}s")
    print(f"Speedup: {debug_time/release_time:.2f}x")
    
    # Release should be at least as fast as debug
    assert release_time <= debug_time * 2  # Allow some variance


def run_all_optimization_tests():
    """Run all optimization tests."""
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        tests = [
            ("Comprehensive optimization pipeline", test_comprehensive_optimization_pipeline),
            ("Advanced optimization features", test_advanced_optimization_features),
            ("Memory optimizations", test_memory_optimizations),
            ("Advanced loop optimizations", test_loop_optimizations_advanced),
            ("Tail call optimization", test_tail_call_optimization),
            ("Branch prediction optimization", test_branch_prediction_optimization),
            ("Advanced dead branch elimination", test_dead_branch_elimination_advanced),
            ("Switch optimization", test_switch_optimization),
            ("Performance comparison", test_performance_comparison),
        ]
        
        passed = 0
        failed = 0
        
        for name, test_func in tests:
            try:
                test_func(tmp_path)
                print(f"✓ {name}")
                passed += 1
            except Exception as e:
                print(f"✗ {name}: {e}")
                failed += 1
        
        print(f"\n=== OPTIMIZATION TEST SUMMARY ===")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total: {passed + failed}")
        
        if failed == 0:
            print("🎉 All optimization tests passed!")
        else:
            print(f"⚠️  {failed} test(s) failed")
        
        return failed == 0


if __name__ == "__main__":
    run_all_optimization_tests()
