#!/bin/bash

echo "=== ASTRA Performance Benchmark: Python vs LLVM vs Native ==="
echo "Testing fibonacci(10) across all backends"
echo ""

# Python target
echo "1. Python Target:"
time python3 fib_benchmark.py
echo ""

# Native target  
echo "2. Native Target:"
time ./fib_benchmark_native
echo ""

echo "=== Additional Test: Multiple Runs for Average ==="
echo "Python (5 runs):"
for i in {1..5}; do
    time python3 fib_benchmark.py >/dev/null
done

echo ""
echo "Native (5 runs):"
for i in {1..5}; do
    time ./fib_benchmark_native >/dev/null
done

echo ""
echo "=== Benchmark Complete ==="
