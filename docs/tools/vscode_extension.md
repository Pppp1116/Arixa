# VS Code Extension

The ASTRA VS Code extension provides comprehensive language support with advanced features for GPU development, module management, and intelligent coding assistance.

## Features

### Enhanced Syntax Highlighting
- **GPU Development**: `gpu fn`, kernel syntax, CUDA builtins
- **Advanced Types**: Pointers (`*Type`), references (`&Type`), collections (`Vec<T>`)
- **Attributes**: `#[derive]`, `#[link]`, `#[packed]`
- **Enhanced Literals**: Binary (`0b1010`), hex (`0xFF`), octal (`0o755`), underscores (`1_000_000`)
- **Documentation Comments**: `///` doc comments

### IntelliSense & Completion
- Context-aware suggestions
- Type-aware completions
- Import suggestions for unresolved symbols
- GPU-specific completions
- Method chaining support

### Snippets (60+)

#### Core Language
- `fn` - Basic function
- `fnr` - Function with explicit return type
- `kernel` - GPU kernel function
- `extern` - External function
- `unsafe` - Unsafe block
- `comptime` - Compile-time block

#### Control Flow
- `if`, `ife` - If/else patterns
- `for`, `forr` - For loops
- `while` - While loop
- `match`, `matchopt`, `matchres` - Match expressions

#### Type System
- `struct`, `structd` - Struct declarations
- `enum`, `enumv` - Enum declarations
- `option`, `result` - Option/Result types
- `vec`, `ptr`, `ref`, `array` - Collection types

#### Package Management
- `pkg` - Package manifest template
- `impstd`, `imp`, `impfile`, `impgpu` - Import variations

#### GPU Development
- `gputemplate` - Complete GPU kernel template
- GPU memory management patterns

### Commands

#### Core Development
- `Astra: Build Current File` - Compile current file
- `Astra: Run Current File` - Execute current file
- `Astra: Restart Language Server` - Restart LSP
- `Astra: Show Language Server Status` - Show server status

#### Package Management
- `Astra: Initialize Package` - Create new module
- `Astra: Publish Package` - Publish to registry
- `Astra: Search Packages` - Search module registry
- `Astra: Install Package` - Install module
- `Astra: List Installed Packages` - Show installed modules

#### Advanced Features
- `Astra: Generate Documentation` - Generate docs
- `Astra: Run Benchmarks` - Performance testing
- `Astra: New Project` - Create new project
- `Astra: Compile for GPU` - GPU compilation

## Configuration

### Enhanced Error System
```json
{
  "arixa.enhancedErrors.enabled": true,
  "arixa.enhancedErrors.showSuggestions": true,
  "arixa.enhancedErrors.showNotes": true
}
```

### Package Management
```json
{
  "arixa.moduleManager.autoInstall": false,
  "arixa.moduleManager.registryUrl": "https://registry.astra-lang.org"
}
```

### GPU Development
```json
{
  "arixa.gpu.enabled": true,
  "arixa.gpu.defaultBackend": "cuda"
}
```

### Formatting & Linting
```json
{
  "arixa.formatting.enabled": true,
  "arixa.formatting.indentSize": 4,
  "arixa.linting.enabled": true,
  "arixa.linting.warningsAsErrors": false
}
```

## Key Bindings

- `Ctrl+Shift+B` - Build current file
- `Ctrl+Shift+R` - Run current file
- `Ctrl+Shift+P` - Publish module
- `Ctrl+Shift+S` - Search modules
- `F5` - Run current file (debug style)

## Installation

```bash
# Install from VS Code Marketplace
ext install arixa-lang.astra-language

# Or install from file
code --install-extension astra-language-0.5.0.vsix
```

## Quick Start

1. Open an `.arixa` file
2. Use `Ctrl+Shift+P` → "Astra: New Project"
3. Start coding with enhanced IntelliSense
4. Use snippets for rapid development
5. Build and run with `Ctrl+Shift+B` / `Ctrl+Shift+R`

## GPU Development Features

### CUDA Integration
- GPU kernel syntax highlighting
- CUDA builtins and functions
- Thread indexing patterns
- Memory space qualifiers

### GPU Templates
- Complete kernel templates
- Vector operations
- Matrix operations
- Memory management patterns

## Language Server Integration

The extension includes a comprehensive Language Server Protocol implementation with:

- Enhanced completion providers
- Advanced semantic analysis
- Performance analysis
- Security analysis
- GPU optimization suggestions
- Dead code detection

## Debug Adapter

Full Debug Adapter Protocol support including:

- Multi-target debugging (Native, LLVM, GPU)
- Breakpoint management
- Variable inspection
- Expression evaluation
- Call stack navigation
- Exception handling

## Performance Profiler

Enhanced profiling capabilities:

- Function-level performance analysis
- Memory usage tracking
- GPU kernel profiling
- Optimization suggestions

For detailed implementation notes and development history, see `docs/internal/development_summaries/vscode_implementation.md`.
