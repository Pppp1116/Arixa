#!/usr/bin/env python3
"""Test the std.bytes module functionality."""

import subprocess
import tempfile
import os
import sys

def test_bytes_module():
    """Test basic bytes module operations."""
    
    # Test code for bytes module
    test_code = '''
import std.bytes as bytes;

fn test_basic_operations() {
    // Test data
    data = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]) as Bytes;  // "Hello"
    pattern = vec_from([0x6C, 0x6C]) as Bytes;  // "ll"
    prefix = vec_from([0x48, 0x65]) as Bytes;  // "He"
    suffix = vec_from([0x6C, 0x6F]) as Bytes;  // "lo"
    
    // Test len
    assert bytes.len(data) == 5;
    
    // Test is_empty
    assert !bytes.is_empty(data);
    assert bytes.is_empty(vec_new() as Bytes);
    
    // Test slice
    slice_result = bytes.slice(data, 1, 3);
    assert bytes.len(slice_result) == 3;
    
    // Test find
    assert bytes.find(data, pattern) == 2;
    assert bytes.find(data, vec_from([0xFF]) as Bytes) == -1;
    
    // Test contains
    assert bytes.contains(data, pattern);
    assert !bytes.contains(data, vec_from([0xFF]) as Bytes);
    
    // Test starts_with/ends_with
    assert bytes.starts_with(data, prefix);
    assert !bytes.starts_with(data, suffix);
    assert bytes.ends_with(data, suffix);
    assert !bytes.ends_with(data, prefix);
    
    // Test get
    first_byte = bytes.get(data, 0);
    assert first_byte != none && (first_byte as u8) == 0x48;
    assert bytes.get(data, 10) == none;
    
    // Test concat
    more_data = vec_from([0x20, 0x57, 0x6F, 0x72, 0x6C, 0x64]) as Bytes;  // " World"
    concatenated = bytes.concat(data, more_data);
    assert bytes.len(concatenated) == 11;
    
    // Test repeat
    repeated = bytes.repeat(data, 3);
    assert bytes.len(repeated) == 15;
    
    // Test compare
    same_data = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]) as Bytes;
    assert bytes.compare(data, same_data) == 0;
    assert bytes.compare(data, more_data) < 0;
    assert bytes.compare(more_data, data) > 0;
    
    return 0;
}

fn test_join() {
    parts = vec_from([
        vec_from([0x48, 0x69]) as Bytes,  // "Hi"
        vec_from([0x54, 0x68, 0x65, 0x72, 0x65]) as Bytes,  // "There"
        vec_from([0x57, 0x6F, 0x72, 0x6C, 0x64]) as Bytes  // "World"
    ]);
    delimiter = vec_from([0x2C, 0x20]) as Bytes;  // ", "
    
    joined = bytes.join(parts, delimiter);
    assert bytes.len(joined) > 0;
    
    return 0;
}

fn main() Int {
    test_basic_operations();
    test_join();
    return 0;
}
'''
    
    # Write test code to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.arixa', delete=False) as f:
        f.write(test_code)
        test_file = f.name
    
    try:
        # Create output file path
        output_file = test_file.replace('.arixa', '.py')
        
        # Compile and run the test
        result = subprocess.run([
            '.venv/bin/arixa', 'build', '-o', output_file, '--target', 'py', test_file
        ], capture_output=True, text=True, cwd='/home/pedro/rust-projects/language/ASTRA')
        
        print("Build STDOUT:", result.stdout)
        print("Build STDERR:", result.stderr)
        print("Build Return code:", result.returncode)
        
        if result.returncode != 0:
            return False
            
        # Run the compiled Python code
        result = subprocess.run([
            'python3', output_file
        ], capture_output=True, text=True, cwd='/home/pedro/rust-projects/language/ASTRA')
        
        print("Run STDOUT:", result.stdout)
        print("Run STDERR:", result.stderr)
        print("Run Return code:", result.returncode)
        
        return result.returncode == 0
        
    finally:
        # Clean up
        os.unlink(test_file)
        output_file = test_file.replace('.arixa', '.py')
        if os.path.exists(output_file):
            os.unlink(output_file)

def test_encoding_module():
    """Test basic encoding module operations."""
    
    test_code = '''
import std.encoding;
import std.bytes as bytes;

fn test_utf8_operations() {
    // Test UTF-8 encoding/decoding
    text = "Hello, 世界";
    utf8_bytes = encoding.utf8_encode(text);
    
    assert bytes.len(utf8_bytes) > 0;
    
    decoded = encoding.utf8_decode(utf8_bytes);
    // Note: We can't easily test the decoded string value in this test setup
    // but we can test that it doesn't return an error
    match decoded {
        String => {},  // Success case
        Utf8Error => { assert false; }  // Should not error
    }
    
    return 0;
}

fn test_hex_operations() {
    data = vec_from([0xDE, 0xAD, 0xBE, 0xEF]) as Bytes;
    
    // Test hex encoding
    hex_str = encoding.hex_encode(data);
    assert str.length(hex_str) == 8;
    
    // Test hex decoding
    decoded = encoding.hex_decode(hex_str);
    match decoded {
        Bytes => {
            assert bytes.len(decoded as Bytes) == 4;
        },
        DecodeError => { assert false; }
    }
    
    return 0;
}

fn main() Int {
    test_utf8_operations();
    test_hex_operations();
    return 0;
}
'''
    
    # Write test code to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.arixa', delete=False) as f:
        f.write(test_code)
        test_file = f.name
    
    try:
        # Create output file path
        output_file = test_file.replace('.arixa', '.py')
        
        # Compile and run the test
        result = subprocess.run([
            '.venv/bin/arixa', 'build', '-o', output_file, '--target', 'py', test_file
        ], capture_output=True, text=True, cwd='/home/pedro/rust-projects/language/ASTRA')
        
        print("Build STDOUT:", result.stdout)
        print("Build STDERR:", result.stderr)
        print("Build Return code:", result.returncode)
        
        if result.returncode != 0:
            return False
            
        # Run the compiled Python code
        result = subprocess.run([
            'python3', output_file
        ], capture_output=True, text=True, cwd='/home/pedro/rust-projects/language/ASTRA')
        
        print("Run STDOUT:", result.stdout)
        print("Run STDERR:", result.stderr)
        print("Run Return code:", result.returncode)
        
        return result.returncode == 0
        
    finally:
        # Clean up
        os.unlink(test_file)
        output_file = test_file.replace('.arixa', '.py')
        if os.path.exists(output_file):
            os.unlink(output_file)

if __name__ == "__main__":
    print("Testing std.bytes module...")
    bytes_success = test_bytes_module()
    
    print("\nTesting std.encoding module...")
    encoding_success = test_encoding_module()
    
    if bytes_success and encoding_success:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
