# Editor Setup

## Recommended

Use the VS Code extension under `editors/vscode/` for syntax and LSP integration.

## Language Server

`astlsp` implements stdio LSP and powers diagnostics, hover, completions, formatting, and symbol search.

## VS Code Quick Setup

1. Install the local extension from `editors/vscode/`.
2. Ensure `astlsp` is installed in your Python environment.
3. Open Astra files (`*.astra`) and verify diagnostics appear.

## Formatter Integration

Format from CLI or configure editor save hooks to run `astra fmt`.

## Fonts and Rendering

The recommended defaults are documented in `docs/EDITOR_SETUP.md`.
