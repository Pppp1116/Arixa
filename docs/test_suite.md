# ASTRA Test Suite Documentation

This document provides comprehensive information about the ASTRA test suite, including structure, coverage, and best practices for running and writing tests.

## Overview

The ASTRA test suite is designed to ensure the reliability, correctness, and performance of the ASTRA compiler and language features. It provides comprehensive coverage across all compiler components and language constructs.

## Test Structure

### Test Categories

#### 1. Unit Tests
- **Lexer Tests**: Test tokenization, keyword recognition, and error handling
- **Parser Tests**: Test AST generation, expression parsing, and error recovery
- **Semantic Tests**: Test type checking, scope resolution, and ownership analysis
- **Codegen Tests**: Test Python and LLVM code generation
- **Error Reporting Tests**: Test enhanced error formatting and suggestions

#### 2. Integration Tests
- **End-to-End Compilation**: Test complete compilation pipeline
- **Real-World Programs**: Test compilation of complex programs
- **Tool Integration**: Test CLI, LSP, and build system integration
- **Cross-Language Tests**: Test FFI and interoperability

#### 3. Performance Tests
- **Compilation Speed**: Test large program compilation performance
- **Memory Usage**: Test memory consumption during compilation
- **Concurrent Compilation**: Test multiple program compilation

### Test Files

```
tests/
├── test_lexer_comprehensive.py          # Comprehensive lexer tests
├── test_parser_comprehensive.py         # Comprehensive parser tests
├── test_semantic_comprehensive.py       # Comprehensive semantic tests
├── test_codegen_comprehensive.py        # Comprehensive codegen tests
├── test_error_reporting_comprehensive.py # Error reporting tests
├── test_integration_comprehensive.py    # Integration tests
├── test_lexer.py                         # Original lexer tests
├── test_parser.py                        # Original parser tests
├── test_semantic.py                      # Original semantic tests
├── gpu/                                  # GPU-specific tests
│   ├── test_gpu_cuda_bridge_codegen.py
│   ├── test_gpu_examples_integration.py
│   └── ...
└── [other test files]                    # Additional specialized tests
```

## Running Tests

### Prerequisites

Make sure you have the required dependencies installed:

```bash
pip install pytest pytest-cov pytest-benchmark
```

### Basic Test Commands

#### Run All Tests
```bash
pytest tests/
```

#### Run Specific Test Categories
```bash
# Run comprehensive lexer tests
pytest tests/test_lexer_comprehensive.py

# Run comprehensive parser tests
pytest tests/test_parser_comprehensive.py

# Run comprehensive semantic tests
pytest tests/test_semantic_comprehensive.py

# Run comprehensive codegen tests
pytest tests/test_codegen_comprehensive.py

# Run error reporting tests
pytest tests/test_error_reporting_comprehensive.py

# Run integration tests
pytest tests/test_integration_comprehensive.py
```

#### Run with Coverage
```bash
pytest tests/ --cov=astra --cov-report=html --cov-report=term
```

#### Run Performance Tests
```bash
pytest tests/ --benchmark-only
```

#### Run with Verbose Output
```bash
pytest tests/ -v
```

#### Run Specific Test Methods
```bash
pytest tests/test_lexer_comprehensive.py::TestLexerBasics::test_empty_input
```

### Test Configuration

#### pytest.ini Configuration
```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    --strict-markers
    --strict-config
    --verbose
    --tb=short
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    performance: marks tests as performance tests
    gpu: marks tests as GPU-specific tests
```

## Test Coverage

### Coverage Areas

#### 1. Lexer Coverage (95%+)
- ✅ Token recognition and classification
- ✅ Keyword and identifier handling
- ✅ Literal parsing (int, float, string, char, bool)
- ✅ Operator and punctuation recognition
- ✅ Comment handling (line, block, doc)
- ✅ Position tracking (line, column)
- ✅ Error token generation
- ✅ Unicode support
- ✅ Edge cases and performance

#### 2. Parser Coverage (90%+)
- ✅ Expression parsing with precedence
- ✅ Statement parsing (bindings, if, while, for, etc.)
- ✅ Declaration parsing (fn, struct, enum, etc.)
- ✅ Pattern matching
- ✅ Error recovery
- ✅ Complex constructs
- ✅ Performance testing

#### 3. Semantic Analysis Coverage (85%+)
- ✅ Type checking and inference
- ✅ Scope resolution
- ✅ Ownership and borrowing analysis
- ✅ Memory safety checks
- ✅ Function resolution
- ✅ Generic type analysis
- ✅ Module system
- ✅ Async/await analysis

#### 4. Code Generation Coverage (80%+)
- ✅ Python code generation
- ✅ LLVM IR generation
- ✅ GPU code generation
- ✅ Optimization passes
- ✅ Backend-specific features
- ✅ Error handling

#### 5. Error Reporting Coverage (95%+)
- ✅ Error message formatting
- ✅ Context extraction
- ✅ Suggestion generation
- ✅ Error code assignment
- ✅ Multiple error handling
- ✅ Performance testing

#### 6. Integration Coverage (75%+)
- ✅ End-to-end compilation
- ✅ Real-world programs
- ✅ Tool integration
- ✅ Performance benchmarks
- ✅ Cross-language integration

### Coverage Reports

Generate detailed coverage reports:

```bash
# HTML coverage report
pytest tests/ --cov=astra --cov-report=html

# Terminal coverage report
pytest tests/ --cov=astra --cov-report=term

# Coverage by module
pytest tests/ --cov=astra --cov-report=term-missing
```

## Writing Tests

### Test Structure Guidelines

#### 1. Test Class Organization
```python
class TestComponentName:
    """Test component functionality."""
    
    def test_specific_feature(self):
        """Test specific feature with clear description."""
        # Arrange
        # Act
        # Assert
        pass
```

#### 2. Test Naming Conventions
- Use descriptive test names: `test_function_name_scenario`
- Group related tests in classes
- Use clear docstrings for complex tests

#### 3. Test Organization
```python
class TestLexerBasics:
    """Test basic lexer functionality."""
    
    def test_empty_input(self):
        """Test lexing empty input."""
        tokens = lex("")
        assert len(tokens) == 0
    
    def test_single_tokens(self):
        """Test individual token recognition."""
        test_cases = [
            (";", "SEMICOLON"),
            (":", "COLON"),
            (",", "COMMA"),
        ]
        
        for char, expected_kind in test_cases:
            tokens = lex(char)
            assert len(tokens) == 1
            assert tokens[0].kind == expected_kind
```

### Best Practices

#### 1. Use Fixtures for Common Setup
```python
@pytest.fixture
def sample_program():
    """Provide a sample ASTRA program for testing."""
    return """
    fn main() -> Int {
        return 42;
    }
    """

def test_program_compilation(sample_program):
    """Test program compilation using fixture."""
    prog = parse(sample_program)
    assert len(prog.items) == 1
```

#### 2. Use Parametrized Tests
```python
@pytest.mark.parametrize("input,expected", [
    ("42", "INT"),
    ("3.14", "FLOAT"),
    ("\"hello\"", "STR"),
    ("true", "BOOL"),
])
def test_literal_recognition(input, expected):
    """Test literal recognition with multiple inputs."""
    tokens = lex(input)
    assert len(tokens) == 1
    assert tokens[0].kind == expected
```

#### 3. Test Error Cases
```python
def test_type_mismatch_error():
    """Test type mismatch error detection."""
    src = """
    fn main() -> Int {
        x = "hello";  // Type mismatch
        return x;
    }
    """
    
    prog = parse(src)
    with pytest.raises(SemanticError) as exc_info:
        analyze(prog)
    assert "type" in str(exc_info.value).lower()
```

#### 4. Test Performance
```python
@pytest.mark.performance
def test_large_program_compilation_speed():
    """Test compilation speed for large programs."""
    # Generate large program
    lines = ["fn main() -> Int {"]
    for i in range(1000):
        lines.append(f"    x{i} = {i};")
    lines.append("    return 0;")
    lines.append("}")
    src = "\n".join(lines)
    
    # Measure compilation time
    start_time = time.time()
    prog = parse(src)
    analyze(prog)
    python_code = to_python(analyzed_prog)
    end_time = time.time()
    
    assert end_time - start_time < 10.0
```

### Test Data Management

#### 1. Use Temporary Files for I/O Tests
```python
def test_file_compilation(tmp_path):
    """Test compilation from file."""
    src = """
    fn main() -> Int {
        return 42;
    }
    """
    
    src_file = tmp_path / "test.arixa"
    src_file.write_text(src)
    
    prog = parse(src_file.read_text(), filename=str(src_file))
    analyze(prog)
```

#### 2. Use Mock Objects for External Dependencies
```python
from unittest.mock import Mock, patch

def test_external_integration():
    """Test integration with external systems."""
    with patch('astra.external.api_call') as mock_api:
        mock_api.return_value = {"result": "success"}
        # Test code that uses external API
```

## Test Categories in Detail

### Lexer Tests (`test_lexer_comprehensive.py`)

#### Coverage Areas:
- **Basic Functionality**: Empty input, whitespace, single tokens
- **Keywords**: All ASTRA keywords recognition
- **Literals**: Integer, float, string, character, boolean literals
- **Identifiers**: Simple and Unicode identifiers
- **Comments**: Line, block, doc comments, nested comments
- **Position Tracking**: Line and column accuracy
- **Error Handling**: Invalid characters, unclosed strings
- **Edge Cases**: Very long identifiers, mixed whitespace
- **Performance**: Large file lexing, complex expressions

#### Key Test Classes:
- `TestLexerBasics`: Basic lexer functionality
- `TestKeywords`: Keyword recognition
- `TestLiterals`: Literal parsing
- `TestIdentifiers`: Identifier handling
- `TestComments`: Comment processing
- `TestPositionTracking`: Position accuracy
- `TestErrorHandling`: Error token generation
- `TestEdgeCases`: Edge case handling
- `TestPerformance`: Performance testing

### Parser Tests (`test_parser_comprehensive.py`)

#### Coverage Areas:
- **Expression Parsing**: Literals, identifiers, binary/unary operations
- **Statement Parsing**: Let, assign, return, if, while, for, match
- **Declaration Parsing**: Functions, structs, enums, traits, imports
- **Error Handling**: Syntax errors, error recovery
- **Complex Constructs**: Nested expressions, generics, lambdas
- **Performance**: Large programs, deeply nested structures

#### Key Test Classes:
- `TestExpressionParsing`: Expression parsing
- `TestStatementParsing`: Statement parsing
- `TestDeclarationParsing`: Declaration parsing
- `TestErrorHandling`: Parser error handling
- `TestComplexConstructs`: Complex language features
- `TestPerformance`: Parser performance

### Semantic Tests (`test_semantic_comprehensive.py`)

#### Coverage Areas:
- **Type Checking**: Basic inference, annotations, function types
- **Scope Resolution**: Local scope, shadowing, function scope
- **Ownership**: Basic ownership, borrowing, lifetime analysis
- **Struct/Enum Analysis**: Field access, pattern matching
- **Generic Analysis**: Generic functions, structs, trait bounds
- **Memory Safety**: Null checks, array bounds
- **Control Flow**: Return analysis, loop control
- **Module System**: Import resolution, circular imports
- **Async Analysis**: Async functions, await context

#### Key Test Classes:
- `TestTypeChecking`: Type system
- `TestScopeResolution`: Name resolution
- `TestOwnershipAndBorrowing`: Ownership system
- `TestStructAndEnumAnalysis`: Data structures
- `TestGenericAnalysis`: Generics
- `TestMemorySafety`: Memory safety
- `TestControlFlowAnalysis`: Control flow
- `TestModuleSystem`: Module system
- `TestAsyncAnalysis`: Async features

### Codegen Tests (`test_codegen_comprehensive.py`)

#### Coverage Areas:
- **Python Codegen**: Functions, variables, control flow, data structures
- **LLVM Codegen**: Basic functions, arithmetic, control flow
- **GPU Codegen**: Kernel functions, builtin operations
- **Optimization**: Constant folding, dead code elimination
- **Backend Features**: Freestanding mode, extern functions
- **Error Handling**: Unsupported operations, error recovery
- **Performance**: Large programs, complex expressions
- **Integration**: End-to-end execution, quality checks

#### Key Test Classes:
- `TestPythonCodegen`: Python code generation
- `TestLLVMCodegen`: LLVM IR generation
- `TestGPUCodegen`: GPU code generation
- `TestOptimizationPasses`: Optimization
- `TestBackendSpecificFeatures`: Backend features
- `TestErrorHandling`: Codegen errors
- `TestPerformance`: Codegen performance
- `TestIntegration`: End-to-end integration
- `TestCodegenQuality`: Code quality

### Error Reporting Tests (`test_error_reporting_comprehensive.py`)

#### Coverage Areas:
- **ErrorReporter**: Core error reporting functionality
- **EnhancedError**: Enhanced error data structures
- **ErrorSuggestion**: Suggestion generation
- **ErrorContext**: Context extraction
- **ErrorEnhancement**: Message enhancement
- **Integration**: Component integration
- **Performance**: Large context, multiple errors
- **Edge Cases**: Empty sources, out of bounds, Unicode

#### Key Test Classes:
- `TestErrorReporter`: Error reporter functionality
- `TestEnhancedError`: Enhanced error structure
- `TestErrorSuggestion`: Suggestion system
- `TestErrorContext`: Context extraction
- `TestErrorEnhancement`: Message enhancement
- `TestErrorPatterns`: Error patterns
- `TestErrorReportingIntegration`: Component integration
- `TestErrorReportingPerformance`: Performance testing
- `TestErrorReportingEdgeCases`: Edge cases

### Integration Tests (`test_integration_comprehensive.py`)

#### Coverage Areas:
- **End-to-End**: Complete compilation pipeline
- **Error Reporting**: Integration with compiler components
- **Real-World Programs**: Calculator, string processing, data structures
- **Performance**: Speed, memory, concurrent compilation
- **Tool Integration**: CLI, LSP, build system
- **Standard Library**: Import resolution, function calls
- **Cross-Language**: C FFI, Python interop
- **Error Recovery**: Partial compilation, error accumulation

#### Key Test Classes:
- `TestEndToEndCompilation`: Complete pipeline
- `TestErrorReportingIntegration`: Error integration
- `TestRealWorldPrograms`: Real programs
- `TestPerformanceBenchmarks`: Performance testing
- `TestToolIntegration`: Tool integration
- `TestStandardLibraryIntegration`: Stdlib integration
- `TestCrossLanguageIntegration`: Cross-language
- `TestErrorRecoveryIntegration`: Error recovery

## Continuous Integration

### GitHub Actions Configuration

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11]

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v3
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install pytest pytest-cov pytest-benchmark
    
    - name: Run tests
      run: |
        pytest tests/ --cov=astra --cov-report=xml
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
```

### Test Matrix

Run tests across different configurations:

```bash
# Different Python versions
for py in 3.9 3.10 3.11; do
    python$py -m pytest tests/
done

# Different optimization levels
for opt in debug release; do
    pytest tests/ --env OPT_LEVEL=$opt
done

# Different backends
for backend in python llvm; do
    pytest tests/ --env BACKEND=$backend
done
```

## Test Metrics and KPIs

### Coverage Targets
- **Overall Coverage**: 85%+
- **Lexer Coverage**: 95%+
- **Parser Coverage**: 90%+
- **Semantic Coverage**: 85%+
- **Codegen Coverage**: 80%+
- **Error Reporting Coverage**: 95%+

### Performance Targets
- **Small Program Compilation**: <100ms
- **Medium Program Compilation**: <1s
- **Large Program Compilation**: <10s
- **Memory Usage**: <100MB for typical programs
- **Test Suite Runtime**: <5 minutes

### Quality Targets
- **Test Success Rate**: 100% for all tests
- **Flaky Test Rate**: <1%
- **Test Documentation**: 100% coverage
- **Code Coverage**: Consistently above targets

## Troubleshooting

### Common Issues

#### 1. Test Failures Due to Missing Dependencies
```bash
# Install missing dependencies
pip install -r requirements-test.txt
```

#### 2. GPU Tests Not Available
```bash
# Skip GPU tests if CUDA is not available
pytest tests/ -m "not gpu"
```

#### 3. Performance Tests Failing
```bash
# Run performance tests with higher tolerance
pytest tests/ --benchmark-only --benchmark-sort=mean
```

#### 4. Integration Tests Failing
```bash
# Check if required tools are available
which arixa
which clang
```

### Debugging Tests

#### 1. Run Tests with Debug Output
```bash
pytest tests/ -v -s --tb=long
```

#### 2. Run Single Test
```bash
pytest tests/test_lexer_comprehensive.py::TestLexerBasics::test_empty_input -v -s
```

#### 3. Run Tests with Debugger
```bash
pytest tests/ --pdb
```

#### 4. Generate Test Reports
```bash
pytest tests/ --html=reports/test-report.html --self-contained-html
```

## Contributing to Tests

### Adding New Tests

1. **Identify Coverage Gaps**: Use coverage reports to find untested code
2. **Write Test Cases**: Follow the established patterns and conventions
3. **Add Documentation**: Include clear docstrings and comments
4. **Update Coverage**: Ensure new tests improve coverage metrics
5. **Run Tests**: Verify all tests pass locally

### Test Review Process

1. **Code Review**: Ensure tests follow conventions
2. **Coverage Review**: Verify tests improve coverage
3. **Performance Review**: Ensure tests don't slow down the suite
4. **Integration Review**: Verify tests work with existing test suite

### Test Maintenance

1. **Regular Updates**: Keep tests updated with language changes
2. **Refactoring**: Refactor tests when language features change
3. **Cleanup**: Remove obsolete tests and fix broken ones
4. **Documentation**: Keep test documentation up to date

## Conclusion

The ASTRA test suite provides comprehensive coverage of all language features and compiler components. By following the guidelines and best practices outlined in this document, developers can effectively write, maintain, and extend the test suite to ensure the continued reliability and quality of the ASTRA language.

For more information about specific test areas, refer to the individual test files and their inline documentation.
