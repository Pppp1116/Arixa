# ASTRA Public Package Publishing System

## Overview

ASTRA now supports comprehensive public module publishing with GitHub integration, similar to Rust's crates.io but with direct GitHub repository linking.

## 🚀 Quick Start

### 1. Create a Package

```bash
# Initialize a new module
python astra/pkg_cli.py init my_awesome_library --description "My awesome ASTRA library"

# Or manually create:
my_library/
├── Astra.toml              # Package manifest
├── src/
│   └── lib.arixa           # Library entry point
├── examples/
│   └── demo.arixa          # Usage examples
└── tests/
    └── test_lib.arixa      # Tests
```

### 2. Package Manifest (Astra.toml)

```toml
[module]
name = "my_awesome_library"
version = "0.1.0"
description = "My awesome ASTRA library for data processing"
authors = ["Your Name <you@example.com>"]
license = "MIT"
homepage = "https://github.com/yourusername/my_awesome_library"
repository = "https://github.com/yourusername/my_awesome_library"
documentation = "https://github.com/yourusername/my_awesome_library#readme"
keywords = ["data", "processing", "algorithms", "utilities"]
categories = ["Data Structures", "Algorithms", "Utilities"]

[dependencies]
std = "1.0.0"
serde_json = "1.0.0"

[dev-dependencies]
test_utils = "0.1.0"

[targets]
freestanding = true
gpu = false

[features]
default = ["core", "serde"]
core = []
serde = ["core", "serde_json"]
advanced = ["serde", "math"]

[module.metadata]
publish = true
auto-publish = false
build-targets = ["x86_64", "arm64"]
minimum-astra-version = "1.0.0"
```

### 3. Publish Your Package

```bash
# Validate module structure
python astra/pkg_cli.py publish --directory . --dry-run

# Publish to GitHub (creates release and uploads module)
python astra/pkg_cli.py publish --directory . --target github --create-release

# Publish to ASTRA registry
python astra/pkg_cli.py publish --directory . --target registry
```

## 📦 Package Discovery

### Search for Packages

```bash
# Search by keyword
python astra/pkg_cli.py search "game development"
python astra/pkg_cli.py search "math"
python astra/pkg_cli.py search "http client"

# Get module information
python astra/pkg_cli.py info raylib
python astra/pkg_cli.py info serde_json
```

### Available Package Categories

- **Mathematics**: Mathematical utilities and algorithms
- **Graphics**: 2D/3D graphics and rendering
- **Games**: Game development libraries
- **Networking**: HTTP clients, TCP/UDP networking
- **Database**: Database connectors and ORMs
- **CLI**: Command-line interface utilities
- **Web**: Web frameworks and HTTP servers
- **Data**: Data structures and serialization
- **System**: System-level utilities and FFI
- **Multimedia**: Audio, video, and image processing
- **Testing**: Testing frameworks and utilities

## 🔧 Package Installation

### Install from Registry

```bash
# Install latest version
python astra/pkg_cli.py install raylib

# Install specific version
python astra/pkg_cli.py install raylib@5.0.0

# Install with custom directory
python astra/pkg_cli.py install serde_json --install-dir ~/my_modules
```

### Install from GitHub

```bash
# Install directly from GitHub repository
python astra/pkg_cli.py install https://github.com/yourusername/your_library
```

### Use Installed Packages

```astra
// In your main.arixa
import serde_json;
import raylib;

fn main() Int {
    // Use functions from installed modules
    data = serialize_to_json(my_data);
    return 0;
}
```

## 📋 Registry Integration

### Package Registry Features

**Enhanced Registry Format**:
```json
{
  "module_name": {
    "repo": "https://github.com/user/module",
    "description": "Package description",
    "version": "1.0.0",
    "license": "MIT",
    "authors": ["Author Name <email@example.com>"],
    "homepage": "https://example.com",
    "keywords": ["keyword1", "keyword2"],
    "categories": ["Category1", "Category2"],
    "dependencies": {
      "std": "1.0.0",
      "other_module": "2.0.0"
    },
    "targets": {
      "freestanding": true,
      "hosted": true,
      "gpu": false
    },
    "features": {
      "default": ["core"],
      "core": [],
      "advanced": ["core", "external_dep"]
    }
  }
}
```

### Registry Statistics

**Current Registry Packages**:
- **11 modules** available across multiple categories
- **Core libraries**: C bindings, OpenGL, SDL2, SQLite
- **Community libraries**: JSON serialization, regex, HTTP client
- **Game development**: Raylib, game engine
- **Utilities**: CLI tools, mathematical functions

## 🌐 GitHub Integration

### GitHub Publishing Workflow

1. **Repository Setup**:
   - Create GitHub repository
   - Add repository URL to `Astra.toml`
   - Ensure proper versioning with Git tags

2. **Release Creation**:
   ```bash
   # Create Git tag
   git tag v0.1.0
   git push origin v0.1.0
   
   # Publish with GitHub release
   python astra/pkg_cli.py publish --target github --create-release
   ```

3. **Automatic Features**:
   - GitHub release creation with module archive
   - Automatic checksum generation
   - Download links in registry
   - Version management through Git tags

### GitHub Repository Structure

```
your_library/
├── .github/
│   └── workflows/
│       └── publish.yml     # CI/CD for publishing
├── src/
│   └── lib.arixa
├── examples/
├── tests/
├── Astra.toml
├── README.md              # Used as documentation
├── LICENSE                # License file
└── CHANGELOG.md           # Version history
```

## 📊 Package Management Commands

### Complete CLI Reference

```bash
# Package Management
astra-pkg init <name>                 # Initialize new module
astra-pkg publish [--target TARGET]   # Publish module
astra-pkg search <query>              # Search modules
astra-pkg install <module>          # Install module
astra-pkg list                        # List installed modules
astra-pkg info <module>             # Package information

# Publishing Options
--target github                       # Publish to GitHub releases
--target registry                     # Publish to ASTRA registry
--create-release                     # Create GitHub release
--directory <path>                    # Package directory
--install-dir <path>                 # Installation directory
--limit <number>                      # Search result limit
```

## 🎯 Best Practices

### Package Development

1. **Semantic Versioning**:
   - Follow MAJOR.MINOR.PATCH format
   - Increment MAJOR for breaking changes
   - Increment MINOR for new features
   - Increment PATCH for bug fixes

2. **Documentation**:
   - Comprehensive README.md
   - API documentation in code
   - Usage examples in examples/
   - Changelog in CHANGELOG.md

3. **Testing**:
   - Include tests in tests/
   - Test multiple target platforms
   - Test feature combinations

4. **Dependencies**:
   - Minimize external dependencies
   - Specify version ranges
   - Document optional dependencies

### Publishing Workflow

1. **Pre-Publish Checklist**:
   ```bash
   # Validate module
   astra-pkg publish --directory . --dry-run
   
   # Run tests
   astra-pkg test
   
   # Check documentation
   astra-pkg docs --check
   ```

2. **Release Process**:
   ```bash
   # Update version in Astra.toml
   # Update CHANGELOG.md
   # Commit changes
   git add .
   git commit -m "Release v0.1.0"
   
   # Create and push tag
   git tag v0.1.0
   git push origin main --tags
   
   # Publish
   astra-pkg publish --target github --create-release
   astra-pkg publish --target registry
   ```

## 🔄 CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/publish.yml
name: Publish Package

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    
    - name: Setup Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install ASTRA
      run: pip install astra-lang
    
    - name: Validate Package
      run: astra-pkg publish --directory . --dry-run
    
    - name: Publish to GitHub
      run: astra-pkg publish --directory . --target github --create-release
    
    - name: Publish to Registry
      run: astra-pkg publish --directory . --target registry
```

## 📈 Package Analytics

### Tracking Package Usage

**Registry Analytics**:
- Download counts per version
- Dependency graphs
- Popular modules by category
- Trending modules

**GitHub Integration**:
- Stars and forks
- Issue tracking
- Pull request workflow
- Release statistics

## 🔮 Future Enhancements

### Planned Features

1. **Advanced Package Management**:
   - Dependency resolution with version conflicts
   - Private module registries
   - Package signing and verification

2. **Enhanced Registry**:
   - Web interface for browsing modules
   - Package quality metrics
   - Automated testing integration
   - Documentation hosting

3. **Development Tools**:
   - IDE integration for module management
   - Automatic dependency updates
   - Package templates and scaffolding
   - Performance benchmarking

## 📞 Support and Community

### Getting Help

- **Documentation**: https://docs.astra-lang.org
- **GitHub Discussions**: https://github.com/astralang/registry/discussions
- **Issues**: https://github.com/astralang/registry/issues
- **Community Chat**: [Discord/Slack link]

### Contributing

1. Fork the registry repository
2. Add your module to `modules.json`
3. Submit a pull request
4. Join the community discussions

## 🎉 Conclusion

The ASTRA public module publishing system provides a complete ecosystem for creating, sharing, and discovering libraries. With GitHub integration, comprehensive registry features, and developer-friendly tools, it offers a modern module management experience similar to the best language ecosystems.

Start publishing your modules today and join the growing ASTRA community!
