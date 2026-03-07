#!/usr/bin/env python3
"""Test script to verify ASTRA compiler correctness fixes."""

import subprocess
import tempfile
import os
from pathlib import Path

def run_astra_code(source_code, expect_error=False):
    """Run Astra compiler on source code and return result."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.arixa', delete=False) as f:
        f.write(source_code)
        f.flush()
        
        try:
            result = subprocess.run(
                ['python', '-m', 'astra', 'check', f.name],
                capture_output=True,
                text=True
            )
            
            if expect_error:
                return result.returncode != 0, result.stdout, result.stderr
            else:
                return result.returncode == 0, result.stdout, result.stderr
        finally:
            os.unlink(f.name)

def test_boolean_coercion():
    """Test that int->bool implicit conversions are rejected."""
    print("=== Testing Boolean Coercion Rules ===")
    
    # This should fail - int in if condition
    test1 = """
    fn main() Int {
        if 5 {
            return 0
        }
        return 1
    }
    """
    
    success, stdout, stderr = run_astra_code(test1, expect_error=True)
    print(f"Int in if condition rejected: {success}")
    if success:
        print("✓ PASS: int->bool coercion correctly rejected")
    else:
        print("✗ FAIL: int->bool coercion not rejected")
        print(f"stderr: {stderr}")
    
    # This should fail - int in while condition  
    test2 = """
    fn main() Int {
        while 1 {
            return 0
        }
        return 1
    }
    """
    
    success, stdout, stderr = run_astra_code(test2, expect_error=True)
    print(f"Int in while condition rejected: {success}")
    if success:
        print("✓ PASS: int->bool coercion correctly rejected")
    else:
        print("✗ FAIL: int->bool coercion not rejected")
        print(f"stderr: {stderr}")
    
    # This should pass - bool in if condition
    test3 = """
    fn main() Int {
        if true {
            return 0;
        }
        return 1;
    }
    """
    
    success, stdout, stderr = run_astra_code(test3, expect_error=False)
    print(f"Bool in if condition accepted: {success}")
    if success:
        print("✓ PASS: bool condition correctly accepted")
    else:
        print("✗ FAIL: bool condition not accepted")
        print(f"stderr: {stderr}")

def test_shift_operations():
    """Test shift operation codegen."""
    print("\n=== Testing Shift Operations ===")
    
    # Test signed right shift
    test1 = """
    fn main() Int {
        x: i32 = -8;
        result = x >> 1;
        return result as Int;
    }
    """
    
    success, stdout, stderr = run_astra_code(test1, expect_error=False)
    print(f"Signed right shift compiles: {success}")
    if success:
        print("✓ PASS: signed shift compiles")
    else:
        print("✗ FAIL: signed shift compilation failed")
        print(f"stderr: {stderr}")
    
    # Test unsigned right shift
    test2 = """
    fn main() Int {
        x: u32 = 8;
        result = x >> 1;
        return result as Int;
    }
    """
    
    success, stdout, stderr = run_astra_code(test2, expect_error=False)
    print(f"Unsigned right shift compiles: {success}")
    if success:
        print("✓ PASS: unsigned shift compiles")
    else:
        print("✗ FAIL: unsigned shift compilation failed")
        print(f"stderr: {stderr}")

def test_extern_abi():
    """Test extern function ABI attributes."""
    print("\n=== Testing Extern ABI ===")
    
    test1 = """
    extern fn foo(x i8) i8;
    
    fn main() Int {
        x: i8 = 42;
        result = foo(x);
        return result as Int;
    }
    """
    
    success, stdout, stderr = run_astra_code(test1, expect_error=False)
    print(f"Extern function compiles: {success}")
    if success:
        print("✓ PASS: extern function compiles")
    else:
        print("✗ FAIL: extern function compilation failed")
        print(f"stderr: {stderr}")

def test_float_semantics():
    """Test float comparison semantics."""
    print("\n=== Testing Float Semantics ===")
    
    test1 = """
    fn main() Int {
        x = 0.0/0.0; // NaN
        if x != x {
            return 1;
        }
        return 0;
    }
    """
    
    success, stdout, stderr = run_astra_code(test1, expect_error=False)
    print(f"NaN comparison compiles: {success}")
    if success:
        print("✓ PASS: NaN comparison compiles")
    else:
        print("✗ FAIL: NaN comparison compilation failed")
        print(f"stderr: {stderr}")

if __name__ == "__main__":
    test_boolean_coercion()
    test_shift_operations()
    test_extern_abi()
    test_float_semantics()
    print("\n=== Test Summary Complete ===")
