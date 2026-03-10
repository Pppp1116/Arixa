# Astra VS Code Language Server

## ⚠️ IMPORTANT: DO NOT EDIT MANUALLY ⚠️

This directory contains **automatically generated files** from the main Astra compiler source.

## Source of Truth

All files in this directory are copied from `/astra/` in the repository root by the build system:

```bash
# From repository root:
python scripts/build_vscode_bundle.py
```

## Generated Files

- `run_lsp.py` - Bootstrap script for LSP server
- `run_cli.py` - Bootstrap script for CLI
- `astra/` - Complete copy of the main compiler source

## Build Process

The VS Code extension build process automatically runs the bundling:

```bash
cd editors/vscode
npm run bundle-server  # Calls the Python bundler
npm run package        # Creates the final .vsix
```

## Manual Changes Will Be Lost

Any manual edits to files in this directory will be **overwritten** during the next build.

If you need to modify the language server behavior:

1. **Edit the source files** in `/astra/` (repository root)
2. **Run the bundler** to update this directory
3. **Test the extension** with the updated files

## Architecture

The extension uses a "bundled server" approach where the complete compiler is embedded in the extension package. This ensures:

- Consistent behavior between standalone compiler and extension
- No external dependencies for users
- Single source of truth for language semantics

## Troubleshooting

If the extension shows outdated behavior:

1. Ensure you've built the latest changes: `python scripts/build_vscode_bundle.py`
2. Rebuild the extension: `cd editors/vscode && npm run package`
3. Install the updated extension in VS Code
