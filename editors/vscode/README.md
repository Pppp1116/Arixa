# Astra VS Code Extension

This extension provides:
- Astra language registration (`.astra`)
- syntax highlighting and snippets
- diagnostics, hover, completion, and go-to-definition via Astra LSP
- bundled language server for plug-and-play usage (no repo checkout required)
- bundled compiler command support (`Astra: Build Current File`)
- marketplace/file icon at `images/astra.png`

## Plug-and-play install

1. Install the `.vsix` in VS Code (`Extensions: Install from VSIX...`).
2. Ensure Python 3.11+ is available on your system (`python3`/`python`, or `py -3` on Windows).
3. Open any `.astra` file.
4. Run `Astra: Build Current File` from the command palette to compile immediately.

By default, the extension runs its bundled server.
On first run it auto-provisions a private ASTRA toolchain in VS Code storage, so you do not need a repo checkout.
If `dist/toolchain/bin/astlsp` exists in the opened workspace, it is used automatically first.
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
  - bundled mode auto-provisions a private toolchain on first launch
- `astra.languageServer.command`: executable for external mode
- `astra.languageServer.pythonPath`: optional Python path override for bundled mode
- `astra.languageServer.args`: extra CLI args for external mode
- `astra.trace.server`: LSP trace level (`off`, `messages`, `verbose`)
- editor defaults are scoped to `[astra]` (tabs/spaces/ruler/wrap/whitespace/ligatures)

Use `Astra: Restart Language Server` after changing server settings.
Use `Astra: Show Language Server Status` or `Astra: Open Extension Log` for troubleshooting.
Use `Astra: Build Current File` to run `astra build` from VS Code.
Use `Astra: Check Toolchain Updates` for a manual online update check.

Compiler-related settings:

- `astra.compiler.mode`: `bundled` (default) or `external`
  - bundled mode auto-prefers workspace `dist/toolchain/bin/astra` when available
- `astra.compiler.command`: executable for external compiler mode
- `astra.compiler.pythonPath`: optional Python path override for bundled compiler mode
- `astra.compiler.args`: extra args inserted before the compiler subcommand in external mode
- `astra.compiler.target`: build target for `Astra: Build Current File` (`native`, `llvm`, `py`)
- `astra.compiler.outputDir`: output directory for generated artifacts
- `astra.compiler.buildArgs`: extra args appended to `astra build`
- `astra.toolchain.autoUpdateCheck`: periodic online update checks (enabled by default)
- `astra.toolchain.checkIntervalHours`: update polling interval
- `astra.toolchain.updateChannel`: `stable` or `prerelease`
- `astra.toolchain.updateManifestUrl`: remote manifest URL for update metadata

## Packaging

```bash
cd editors/vscode
npm install
npm run package
```

This creates a `.vsix` package you can install in VS Code.
`npm run package` automatically refreshes the bundled compiler/server copy before building the VSIX.
