# Experiments

This directory contains experimental files and outputs from ASTRA compiler development and testing.

## Contents

### LLVM IR Files
- `*.ll` - LLVM Intermediate Representation output files
- `extern_simple.ll` - Simple external function test
- `ptr_test.ll` - Pointer operation test
- `shift_ir*.ll` - Shift operation IR outputs
- `test_shift.ll` - Shift operation test

### Test Binaries
- `extern_simple` - Compiled test binary
- `ptr_test` - Pointer test binary
- `shift_test*` - Shift operation test binaries

## Purpose

These files are generated during:
- Compiler testing and validation
- IR generation verification
- Performance experiments
- Feature development

## Usage

Files in this directory are typically:
- Generated automatically by tests
- Used for manual inspection of compiler output
- Reference implementations for debugging
- Performance benchmarking artifacts

## Note

These files are not part of the core compiler and can be safely regenerated. They are kept here for reference and debugging purposes.
