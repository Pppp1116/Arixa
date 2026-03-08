#!/usr/bin/env python3
"""Simple test runner for ASTRA without pytest dependency."""

import sys
import tempfile
import traceback
from pathlib import Path

# Add the astra module to the path
sys.path.insert(0, str(Path(__file__).parent))

def run_test_file(test_file):
    """Run a single test file."""
    print(f"Running {test_file}...")
    try:
        # Add tests directory to Python path for golden_helpers
        sys.path.insert(0, str(Path(__file__).parent / "tests"))
        
        # Import the test module
        module_name = Path(test_file).stem
        spec = __import__(module_name)
        
        # Get all test functions
        test_functions = [getattr(spec, name) for name in dir(spec) 
                         if name.startswith('test_') and callable(getattr(spec, name))]
        
        passed = 0
        failed = 0
        
        for test_func in test_functions:
            try:
                # Check if function requires tmp_path parameter
                import inspect
                sig = inspect.signature(test_func)
                if 'tmp_path' in sig.parameters:
                    # Create temporary directory
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        tmp_path = Path(tmp_dir)
                        test_func(tmp_path=tmp_path)
                else:
                    test_func()
                print(f"  ✓ {test_func.__name__}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {test_func.__name__}: {e}")
                failed += 1
        
        print(f"Results: {passed} passed, {failed} failed")
        return failed == 0
        
    except Exception as e:
        print(f"Failed to load {test_file}: {e}")
        # traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("ASTRA Test Runner")
    print("=" * 50)
    
    # Find all test files
    test_dir = Path("tests")
    test_files = list(test_dir.glob("test_*.py"))
    
    # Filter out files that require pytest
    basic_tests = []
    for test_file in test_files:
        try:
            content = test_file.read_text()
            # Skip files that import pytest
            if "import pytest" in content:
                print(f"Skipping {test_file.name} (requires pytest)")
                continue
            basic_tests.append(test_file)
        except:
            print(f"Could not read {test_file.name}")
            continue
    
    print(f"Found {len(basic_tests)} basic test files")
    
    # Run tests
    total_passed = 0
    total_failed = 0
    
    for test_file in basic_tests:
        if run_test_file(test_file):
            total_passed += 1
        else:
            total_failed += 1
        print()
    
    print("=" * 50)
    print(f"Summary: {total_passed} test files passed, {total_failed} failed")
    
    if total_failed > 0:
        sys.exit(1)
    else:
        print("All tests passed!")

if __name__ == "__main__":
    main()
