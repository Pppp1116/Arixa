# Arixa VS Code Extension

This extension provides:
- Arixa language registration (`.arixa`)
- syntax highlighting and snippets
- diagnostics, hover, completion, and go-to-definition via Arixa LSP
- bundled language server for plug-and-play usage (no repo checkout required)
- bundled compiler command support (`Arixa: Build Current File`)
- marketplace/file icon at `images/arixa.png`

## Union-First Language Model

**Version 0.4.3+ includes the completed union-first migration:**
- **`T?` syntax** for nullable types (`Int?` instead of `Option<Int>`)
- **`is` keyword** for flow-sensitive type narrowing (`if result is String { ... }`)
- **Union types** (`Value | ErrorType` instead of `Result<T, E>`)
- **`??` operator** for null coalescing
- **`!` operator** for error propagation
- **Exhaustiveness checking** for match statements
- **Option/Result removed** from stdlib in favor of union model

## Plug-and-play install

1. Install the `.vsix` file in VS Code (`Extensions: Install from VSIX...`).
2. Ensure Python 3.11+ is available on your system (`python3`/`python`, or `py -3` on Windows).
3. Open any `.arixa` file.
4. Run `Arixa: Build Current File` from the command palette to compile immediately.

By default, the extension runs its bundled server.
On first run it auto-provisions a private ARIXA toolchain in VS Code storage, so you do not need a repo checkout.
If `dist/toolchain/bin/arlsp` exists in the opened workspace, it is used automatically first.
The status bar shows server health (`Arixa: ready`/`Arixa: failed`).

## Optional external server mode

If you prefer your own `arlsp` binary:
- set `arixa.languageServer.mode` to `external`
- set `arixa.languageServer.command` (for example `arlsp`)
- optionally set `arixa.languageServer.args`

## Development setup (repo)

1. Install project dependencies and Arixa in editable mode from repo root:

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

- `arixa.languageServer.mode`: `bundled` (default) or `external`
  - bundled mode auto-provisions a private toolchain on first launch
  - bundled mode auto-prefers workspace `dist/toolchain/bin/arixa` when available
- `arixa.languageServer.command`: executable for external mode
- `arixa.languageServer.pythonPath`: optional Python path override for bundled mode
- `arixa.languageServer.args`: extra CLI args for external mode
- `arixa.trace.server`: LSP trace level (`off`, `messages`, `verbose`)
- editor defaults are scoped to `[arixa]` (tabs/spaces/ruler/wrap/whitespace/ligatures)

Use `Arixa: Restart Language Server` after changing server settings.
Use `Arixa: Show Language Server Status` or `Arixa: Open Extension Log` for troubleshooting.
Use `Arixa: Build Current File` to run `arixa build` from VS Code.

Compiler-related settings:
- `arixa.compiler.mode`: `bundled` (default) or `external`
  - bundled mode auto-prefers workspace `dist/toolchain/bin/arixa` when available
- `arixa.compiler.command`: executable for external compiler mode
- `arixa.compiler.pythonPath`: optional Python path override for bundled compiler mode
- `arixa.compiler.args`: extra args inserted before compiler subcommand in external mode
- `arixa.compiler.target`: build target for `Arixa: Build Current File` (`native`, `llvm`, `py`)
- `arixa.compiler.outputDir`: output directory for generated artifacts
- `arixa.compiler.buildArgs`: extra args appended to `arixa build`
- `arixa.toolchain.autoUpdateCheck`: periodic online update checks (enabled by default)
- `arixa.toolchain.checkIntervalHours`: update polling interval
- `arixa.toolchain.updateChannel`: `stable` or `prerelease`
- `arixa.toolchain.updateManifestUrl`: remote manifest URL for update metadata

## Packaging

```bash
cd editors/vscode
npm install
npm run package
```

This creates a `.vsix` package you can install in VS Code.
`npm run package` automatically refreshes the bundled compiler/server copy before building VSIX.

## One-Click Publish (latest syntax + LSP)

From repo root:

```bash
python scripts/release_vscode_extension.py --publish --npm-update
```

This always runs syntax/LSP sync checks, rebuilds the bundled server, updates extension npm deps, and publishes.
Set `VSCE_PAT` in your environment before running.
