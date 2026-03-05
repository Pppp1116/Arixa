# Astra VS Code Extension

This extension provides:
- Astra language registration (`.astra`)
- syntax highlighting and snippets
- diagnostics, hover, completion, and go-to-definition via Astra LSP
- bundled language server for plug-and-play usage (no repo checkout required)
- marketplace/file icon at `images/astra.png`

## Plug-and-play install

1. Install the `.vsix` in VS Code (`Extensions: Install from VSIX...`).
2. Ensure Python 3.11+ is available on your system (`python3`/`python`, or `py -3` on Windows).
3. Open any `.astra` file.

By default, the extension runs its bundled server.
The status bar shows server health (`Astra: ready`/`Astra: failed`).

## Optional external server mode

If you prefer your own `astlsp` binary:
- set `astra.languageServer.mode` to `external`
- set `astra.languageServer.command` (for example `astlsp`)
- optionally set `astra.languageServer.args`

## Development setup (repo)

1. Install project dependencies and Astra in editable mode from repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Install extension dependencies:

```bash
cd editors/vscode
npm install
```

3. Open `editors/vscode` in VS Code and press `F5` to launch an Extension Development Host.

## Configuration

- `astra.languageServer.mode`: `bundled` (default) or `external`
- `astra.languageServer.command`: executable for external mode
- `astra.languageServer.pythonPath`: optional Python path override for bundled mode
- `astra.languageServer.args`: extra CLI args for external mode
- `astra.trace.server`: LSP trace level (`off`, `messages`, `verbose`)
- editor defaults are scoped to `[astra]` (tabs/spaces/ruler/wrap/whitespace/ligatures)

Use `Astra: Restart Language Server` after changing server settings.
Use `Astra: Show Language Server Status` or `Astra: Open Extension Log` for troubleshooting.

## Packaging

```bash
cd editors/vscode
npm install
npm run package
```

This creates a `.vsix` package you can install in VS Code.
