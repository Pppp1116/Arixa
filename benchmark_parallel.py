#!/usr/bin/env python3
"""
Comprehensive benchmark for ASTRA parallel compilation.

Tests speedup with different thread counts and project sizes.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Any


def run_benchmark(input_file: str, threads: int, runs: int = 3) -> Dict[str, Any]:
    """Run benchmark for specific input file and thread count"""
    print(f"Running benchmark: {input_file} with {threads} threads...")
    
    results = []
    for i in range(runs):
        try:
            # Clear cache first
            cache_file = Path(".astra-cache.json")
            if cache_file.exists():
                cache_file.unlink()
            
            # Run build with profiling
            cmd = [
                sys.executable, "-m", "astra", "build",
                input_file,
                "-o", f"/tmp/benchmark_output.py",
                "--target", "py",
                "--profile-compile",
                "--threads", str(threads)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent
            )
            
            if result.returncode != 0:
                print(f"Error running benchmark: {result.stderr}")
                continue
            
            # Extract profile information from output
            output_lines = result.stdout.split('\n')
            profile_data = {}
            
            for line in output_lines:
                if line.startswith('  ') and ':' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        phase = parts[0].strip()
                        time_str = parts[-1]
                        try:
                            time_val = float(time_str)
                            profile_data[phase] = time_val
                        except ValueError:
                            pass
            
            results.append(profile_data)
            
        except Exception as e:
            print(f"Error in run {i}: {e}")
            continue
    
    if not results:
        return {"error": "No successful runs"}
    
    # Compute medians
    def median(values):
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 1:
            return sorted_vals[n // 2]
        return 0.5 * (sorted_vals[n // 2 - 1] + sorted_vals[n // 2])
    
    # Aggregate results
    all_phases = set()
    for result in results:
        all_phases.update(result.keys())
    
    medians = {}
    for phase in all_phases:
        values = [r.get(phase, 0.0) for r in results if phase in r]
        if values:
            medians[phase] = median(values)
    
    return {
        "input_file": input_file,
        "threads": threads,
        "runs": len(results),
        "phase_times": medians,
        "total_time": medians.get("total", 0.0)
    }


def create_large_test_project(size: int = 50) -> str:
    """Create a large test project with multiple modules"""
    project_dir = Path("benchmark_project")
    project_dir.mkdir(exist_ok=True)
    
    # Create main file
    main_content = f"""
// Main file for benchmark project with {size} modules

"""
    
    for i in range(size):
        main_content += f'import "module{i}.astra"\n'
    
    main_content += """
fn main() -> Int {
    let mut sum = 0;
"""
    
    for i in range(size):
        main_content += f"    sum = sum + compute{i}();\n"
    
    main_content += """
    return sum;
}
"""
    
    (project_dir / "main.astra").write_text(main_content)
    
    # Create module files
    for i in range(size):
        module_content = f"""
// Module {i} for benchmark project

pub fn compute{i}() -> Int {{
    let mut result = {i};
    let mut j = 0;
    while j < 10 {{
        result = result + j;
        j = j + 1;
    }}
    return result;
}}

fn helper{i}(x: Int) -> Int {{
    return x * 2;
}}
"""
        (project_dir / f"module{i}.astra").write_text(module_content)
    
    return str(project_dir / "main.astra")


def run_comprehensive_benchmark():
    """Run comprehensive benchmark suite"""
    print("ASTRA Parallel Compilation Benchmark")
    print("=" * 50)
    
    # Test cases
    test_cases = [
        ("examples/hello.astra", "Single file, simple"),
        ("test_parallel.astra", "Multi-file, medium"),
    ]
    
    # Create large test project
    large_project = create_large_test_project(20)
    test_cases.append((large_project, "Multi-file, large"))
    
    thread_counts = [1, 2, 4, 8]
    
    all_results = []
    
    for input_file, description in test_cases:
        print(f"\nBenchmarking: {description}")
        print(f"Input: {input_file}")
        print("-" * 40)
        
        file_results = {}
        
        for threads in thread_counts:
            result = run_benchmark(input_file, threads)
            if "error" not in result:
                file_results[threads] = result
                print(f"  {threads:2d} threads: {result['total_time']:.4f}s total")
                
                # Show breakdown for 1 thread and max threads
                if threads == 1 or threads == max(thread_counts):
                    print(f"    Phases: {result['phase_times']}")
        
        all_results.append({
            "description": description,
            "input_file": input_file,
            "results": file_results
        })
    
    # Calculate speedups
    print("\nSpeedup Analysis")
    print("=" * 50)
    
    for case in all_results:
        description = case["description"]
        results = case["results"]
        
        print(f"\n{description}:")
        
        if 1 in results:
            baseline_time = results[1]["total_time"]
            print(f"  Baseline (1 thread): {baseline_time:.4f}s")
            
            for threads in [2, 4, 8]:
                if threads in results:
                    speedup = baseline_time / results[threads]["total_time"]
                    efficiency = speedup / threads * 100
                    print(f"  {threads} threads: {speedup:.2f}x speedup ({efficiency:.1f}% efficiency)")
        
        # Show phase speedups for 4 threads
        if 4 in results and 1 in results:
            print(f"  Phase speedups (4 threads):")
            for phase in ["parallel_parse", "semantic_parallel", "ir_optimize_parallel"]:
                if phase in results[4]["phase_times"] and phase in results[1]["phase_times"]:
                    baseline = results[1]["phase_times"][phase]
                    parallel = results[4]["phase_times"][phase]
                    if baseline > 0:
                        speedup = baseline / parallel
                        print(f"    {phase}: {speedup:.2f}x")
    
    # Save detailed results
    output_file = "benchmark_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")
    
    # Cleanup
    import shutil
    if Path("benchmark_project").exists():
        shutil.rmtree("benchmark_project")
    
    cache_file = Path(".astra-cache.json")
    if cache_file.exists():
        cache_file.unlink()


if __name__ == "__main__":
    run_comprehensive_benchmark()
