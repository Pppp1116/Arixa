"""Tests for standard IEEE float types (f16, f32, f64, f80, f128)."""

import pytest
from astra.parser import parse
from astra.semantic import analyze


def test_f16_type_recognition():
    """Test that f16 type is recognized and parsed correctly."""
    src = """
    fn test() {
        x: f16 = 3.14;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_f32_type_recognition():
    """Test that f32 type is recognized and parsed correctly."""
    src = """
    fn test() {
        x: f32 = 2.718;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_f64_type_recognition():
    """Test that f64 type is recognized and parsed correctly."""
    src = """
    fn test() {
        x: f64 = 1.414;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_f80_type_recognition():
    """Test that f80 type is recognized and parsed correctly."""
    src = """
    fn test() {
        x: f80 = 0.577;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_f128_type_recognition():
    """Test that f128 type is recognized and parsed correctly."""
    src = """
    fn test() {
        x: f128 = 2.302;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_all_float_types_together():
    """Test that all standard float types can be used together."""
    src = """
    fn test() {
        a: f16 = 1.0;
        b: f32 = 2.0;
        c: f64 = 3.0;
        d: f80 = 4.0;
        e: f128 = 5.0;
        return;  // Don't return value from Void function
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_float_type_as_return_type():
    """Test that float types can be used as return types."""
    src = """
    fn get_f16() f16 {
        return 1.5;
    }
    
    fn get_f80() f80 {
        return 2.5;
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors


def test_float_type_parameters():
    """Test that float types can be used as function parameters."""
    src = """
    fn process_f16(x: f16) f16 {
        return x;
    }
    
    fn process_f128(x: f128) f128 {
        return x;
    }
    """
    prog = parse(src)
    analyze(prog)
    # Should not raise any errors
