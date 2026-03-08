#!/bin/bash

echo "=== ASTRA Performance Benchmark: Python vs Native (fibonacci 35) ==="
echo "This will show significant performance differences"
echo ""

# Test Python target
echo "1. Python Target (fibonacci 35):"
time python3 intensive_benchmark.py
echo ""

# Test Native target  
echo "2. Native Target (fibonacci 35):"
time ./intensive_benchmark_native
echo ""

echo "=== Multiple Runs for Statistical Significance ==="
echo "Python (3 runs):"
for i in {1..3}; do
    echo "Run $i:"
    time python3 intensive_benchmark.py >/dev/null
    echo ""
done

echo "Native (3 runs):"
for i in {1..3}; do
    echo "Run $i:"
    time ./intensive_benchmark_native >/dev/null
    echo ""
done

echo "=== Performance Analysis Complete ==="
