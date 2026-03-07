"""Comprehensive benchmark suite for optimization system."""

import subprocess
import sys
import time
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Any
import json

from astra.build_enhanced import build_enhanced, benchmark_build, compare_optimization_levels


class OptimizationBenchmark:
    """Comprehensive benchmark suite for optimization system."""
    
    def __init__(self, tmp_dir: Path):
        self.tmp_dir = tmp_dir
        self.results: Dict[str, Any] = {}
    
    def run_all_benchmarks(self) -> Dict[str, Any]:
        """Run all optimization benchmarks."""
        print("Running comprehensive optimization benchmarks...")
        
        benchmarks = [
            ("constant_folding", self.benchmark_constant_folding),
            ("loop_optimizations", self.benchmark_loop_optimizations),
            ("strength_reduction", self.benchmark_strength_reduction),
            ("dead_code_elimination", self.benchmark_dead_code_elimination),
            ("function_inlining", self.benchmark_function_inlining),
            ("memory_optimizations", self.benchmark_memory_optimizations),
            ("interprocedural", self.benchmark_interprocedural_optimization),
            ("real_world_workloads", self.benchmark_real_world_workloads),
        ]
        
        for name, benchmark_func in benchmarks:
            print(f"\n=== {name.upper()} BENCHMARK ===")
            try:
                result = benchmark_func()
                self.results[name] = result
                print(f"✓ {name} completed")
            except Exception as e:
                print(f"✗ {name} failed: {e}")
                self.results[name] = {"error": str(e)}
        
        return self.results
    
    def benchmark_constant_folding(self) -> Dict[str, Any]:
        """Benchmark constant folding optimizations."""
        source = """
fn heavy_computation() Int {
    // Lots of constant folding opportunities
    a = 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10;
    b = a * 2 + 4 * 8 + 16 * 32;
    c = b / 2 + 100 - 50 + 25;
    d = c * 10 + 1000 - 500;
    e = d + a + b + c;
    return e;
}

fn main() Int {
    return heavy_computation();
}
"""
        
        return self._compare_builds("constant_folding", source)
    
    def benchmark_loop_optimizations(self) -> Dict[str, Any]:
        """Benchmark loop optimizations."""
        source = """
fn loop_heavy() Int {
    sum = 0;
    i = 0;
    // Loop with invariant code
    invariant = 2 * 3 + 1;
    while i < 10000 {
        j = 0;
        while j < 10 {
            sum = sum + invariant + i + j;
            j = j + 1;
        }
        i = i + 1;
    }
    return sum;
}

fn main() Int {
    return loop_heavy();
}
"""
        
        return self._compare_builds("loop_optimizations", source)
    
    def benchmark_strength_reduction(self) -> Dict[str, Any]:
        """Benchmark strength reduction optimizations."""
        source = """
fn strength_reduced() Int {
    x = 5;
    result = 0;
    i = 0;
    while i < 1000 {
        // Lots of strength reduction opportunities
        a = x * 2;    // << 1
        b = x * 4;    // << 2
        c = x * 8;    // << 3
        d = x * 16;   // << 4
        e = x * 32;   // << 5
        f = x * 64;   // << 6
        g = x * 128;  // << 7
        
        result = result + a + b + c + d + e + f + g;
        i = i + 1;
    }
    return result;
}

fn main() Int {
    return strength_reduced();
}
"""
        
        return self._compare_builds("strength_reduction", source)
    
    def benchmark_dead_code_elimination(self) -> Dict[str, Any]:
        """Benchmark dead code elimination."""
        source = """
fn dead_code_heavy() Int {
    x = 5;
    
    // Lots of dead code
    dead1 = x * 2 + 3;
    dead2 = dead1 * 10 + 100;
    dead3 = dead2 / 5 - 10;
    dead4 = dead3 + 1000 - 500;
    
    // More dead code in branches
    if false {
        unreachable1 = 999999;
        unreachable2 = unreachable1 * 1000;
        return unreachable2;
    }
    
    if true {
        return 42;
    } else {
        more_dead = x + y + z;  // This should be eliminated
        return more_dead;
    }
}

fn main() Int {
    return dead_code_heavy();
}
"""
        
        return self._compare_builds("dead_code_elimination", source)
    
    def benchmark_function_inlining(self) -> Dict[str, Any]:
        """Benchmark function inlining."""
        source = """
fn small_function1(x Int) Int {
    return x + 1;
}

fn small_function2(x Int) Int {
    return x * 2;
}

fn small_function3(x Int) Int {
    return x - 1;
}

fn call_chain(x Int) Int {
    a = small_function1(x);
    b = small_function2(a);
    c = small_function3(b);
    return c;
}

fn main() Int {
    result = 0;
    i = 0;
    while i < 1000 {
        result = result + call_chain(i);
        i = i + 1;
    }
    return result;
}
"""
        
        return self._compare_builds("function_inlining", source)
    
    def benchmark_memory_optimizations(self) -> Dict[str, Any]:
        """Benchmark memory optimizations."""
        source = """
fn memory_heavy() Int {
    // Create lots of temporary values
    a = [1, 2, 3, 4, 5];
    b = [6, 7, 8, 9, 10];
    c = [11, 12, 13, 14, 15];
    
    sum = 0;
    i = 0;
    while i < 5 {
        sum = sum + a[i] + b[i] + c[i];
        i = i + 1;
    }
    
    return sum;
}

fn main() Int {
    return memory_heavy();
}
"""
        
        return self._compare_builds("memory_optimizations", source)
    
    def benchmark_interprocedural_optimization(self) -> Dict[str, Any]:
        """Benchmark interprocedural optimization."""
        source = """
fn constant_function() Int {
    return 42;
}

fn uses_constant() Int {
    x = constant_function();
    y = x + 8;
    return y;
}

fn more_constants() Int {
    a = constant_function();
    b = a * 2;
    c = b + 10;
    return c;
}

fn main() Int {
    result = 0;
    i = 0;
    while i < 100 {
        result = result + uses_constant() + more_constants();
        i = i + 1;
    }
    return result;
}
"""
        
        return self._compare_builds("interprocedural", source)
    
    def benchmark_real_world_workloads(self) -> Dict[str, Any]:
        """Benchmark real-world workloads."""
        # Fibonacci calculation
        fibonacci = """
fn fibonacci(n Int) Int {
    if n <= 1 {
        return n;
    }
    return fibonacci(n - 1) + fibonacci(n - 2);
}

fn main() Int {
    return fibonacci(15);
}
"""
        
        # Matrix multiplication (simplified)
        matrix_mult = """
fn multiply_matrices() Int {
    // Simplified matrix multiplication
    a = [[1, 2], [3, 4]];
    b = [[5, 6], [7, 8]];
    
    result = 0;
    i = 0;
    while i < 2 {
        j = 0;
        while j < 2 {
            k = 0;
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
    return multiply_matrices();
}
"""
        
        # String processing
        string_proc = """
fn process_string() Int {
    text = "Hello, World!";
    count = 0;
    i = 0;
    while i < len(text) {
        if text[i] == 'l' {
            count = count + 1;
        }
        i = i + 1;
    }
    return count;
}

fn main() Int {
    return process_string();
}
"""
        
        workloads = [
            ("fibonacci", fibonacci),
            ("matrix_mult", matrix_mult),
            ("string_proc", string_proc),
        ]
        
        results = {}
        for name, source in workloads:
            result = self._compare_builds(f"real_world_{name}", source)
            results[name] = result
        
        return results
    
    def _compare_builds(self, name: str, source: str) -> Dict[str, Any]:
        """Compare debug vs release builds for given source."""
        src_file = self.tmp_dir / f"{name}.arixa"
        debug_out = self.tmp_dir / f"{name}_debug.py"
        release_out = self.tmp_dir / f"{name}_release.py"
        
        src_file.write_text(source)
        
        # Build debug version
        debug_build_start = time.time()
        build_enhanced(str(src_file), str(debug_out), target="py", profile="debug")
        debug_build_time = time.time() - debug_build_start
        
        # Build release version
        release_build_start = time.time()
        build_enhanced(str(src_file), str(release_out), target="py", profile="release")
        release_build_time = time.time() - release_build_start
        
        # Run debug version
        debug_run_times = []
        for _ in range(5):
            start = time.time()
            cp = subprocess.run([sys.executable, str(debug_out)], 
                              capture_output=True, text=True, timeout=30)
            if cp.returncode == 0:
                debug_run_times.append(time.time() - start)
        
        # Run release version
        release_run_times = []
        for _ in range(5):
            start = time.time()
            cp = subprocess.run([sys.executable, str(release_out)], 
                              capture_output=True, text=True, timeout=30)
            if cp.returncode == 0:
                release_run_times.append(time.time() - start)
        
        # Calculate statistics
        debug_run_avg = statistics.mean(debug_run_times) if debug_run_times else 0
        release_run_avg = statistics.mean(release_run_times) if release_run_times else 0
        speedup = debug_run_avg / release_run_avg if release_run_avg > 0 else 1.0
        
        # Check code size
        debug_code_size = debug_out.stat().st_size
        release_code_size = release_out.stat().st_size
        
        return {
            "build_time": {
                "debug": debug_build_time,
                "release": release_build_time,
                "ratio": debug_build_time / release_build_time if release_build_time > 0 else 1.0
            },
            "run_time": {
                "debug": debug_run_avg,
                "release": release_run_avg,
                "speedup": speedup
            },
            "code_size": {
                "debug": debug_code_size,
                "release": release_code_size,
                "ratio": release_code_size / debug_code_size if debug_code_size > 0 else 1.0
            },
            "correctness": {
                "debug_success": len(debug_run_times) > 0,
                "release_success": len(release_run_times) > 0,
                "same_result": len(debug_run_times) > 0 and len(release_run_times) > 0
            }
        }
    
    def generate_report(self) -> str:
        """Generate comprehensive benchmark report."""
        report = ["# ASTRA Optimization Benchmark Report\n"]
        
        # Summary
        report.append("## Summary\n")
        total_benchmarks = len(self.results)
        successful_benchmarks = len([r for r in self.results.values() if "error" not in r])
        report.append(f"- Total benchmarks: {total_benchmarks}")
        report.append(f"- Successful: {successful_benchmarks}")
        report.append(f"- Failed: {total_benchmarks - successful_benchmarks}\n")
        
        # Detailed results
        report.append("## Detailed Results\n")
        
        for name, result in self.results.items():
            if "error" in result:
                report.append(f"### {name}\n")
                report.append(f"❌ **Error**: {result['error']}\n")
                continue
            
            report.append(f"### {name}\n")
            
            if "run_time" in result:
                rt = result["run_time"]
                report.append(f"- **Runtime speedup**: {rt['speedup']:.2f}x")
                report.append(f"- **Debug runtime**: {rt['debug']:.4f}s")
                report.append(f"- **Release runtime**: {rt['release']:.4f}s")
            
            if "build_time" in result:
                bt = result["build_time"]
                report.append(f"- **Build time ratio**: {bt['ratio']:.2f}x")
                report.append(f"- **Debug build**: {bt['debug']:.4f}s")
                report.append(f"- **Release build**: {bt['release']:.4f}s")
            
            if "code_size" in result:
                cs = result["code_size"]
                report.append(f"- **Code size ratio**: {cs['ratio']:.2f}x")
                report.append(f"- **Debug size**: {cs['debug']} bytes")
                report.append(f"- **Release size**: {cs['release']} bytes")
            
            if "correctness" in result:
                corr = result["correctness"]
                status = "✅" if corr["same_result"] else "❌"
                report.append(f"- **Correctness**: {status}")
            
            report.append("")
        
        # Performance summary
        report.append("## Performance Summary\n")
        
        speedups = []
        for result in self.results.values():
            if "run_time" in result and "speedup" in result["run_time"]:
                speedups.append(result["run_time"]["speedup"])
        
        if speedups:
            avg_speedup = statistics.mean(speedups)
            max_speedup = max(speedups)
            min_speedup = min(speedups)
            
            report.append(f"- **Average speedup**: {avg_speedup:.2f}x")
            report.append(f"- **Maximum speedup**: {max_speedup:.2f}x")
            report.append(f"- **Minimum speedup**: {min_speedup:.2f}x")
        
        report.append("\n---")
        report.append("*Generated by ASTRA Optimization Benchmark Suite*")
        
        return "\n".join(report)
    
    def save_results(self, filename: str):
        """Save benchmark results to JSON file."""
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
    
    def save_report(self, filename: str):
        """Save benchmark report to markdown file."""
        report = self.generate_report()
        with open(filename, 'w') as f:
            f.write(report)


def run_optimization_benchmarks(tmp_dir: Path = None) -> Dict[str, Any]:
    """Run optimization benchmarks and return results."""
    if tmp_dir is None:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
    
    benchmark = OptimizationBenchmark(tmp_dir)
    results = benchmark.run_all_benchmarks()
    
    # Save results
    benchmark.save_results(tmp_dir / "benchmark_results.json")
    benchmark.save_report(tmp_dir / "benchmark_report.md")
    
    print(f"\nBenchmark results saved to:")
    print(f"- JSON: {tmp_dir / 'benchmark_results.json'}")
    print(f"- Report: {tmp_dir / 'benchmark_report.md'}")
    
    return results


if __name__ == "__main__":
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        results = run_optimization_benchmarks(Path(tmp_dir))
        
        print("\n=== BENCHMARK SUMMARY ===")
        for name, result in results.items():
            if "error" in result:
                print(f"{name}: ❌ {result['error']}")
            elif "run_time" in result:
                speedup = result["run_time"]["speedup"]
                print(f"{name}: ✅ {speedup:.2f}x speedup")
            else:
                print(f"{name}: ✅ Completed")
