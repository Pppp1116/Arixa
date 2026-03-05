const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const vscode = require('vscode');
const { LanguageClient, State, Trace } = require('vscode-languageclient/node');

/** @type {LanguageClient | undefined} */
let client;
/** @type {vscode.OutputChannel | undefined} */
let output;
/** @type {vscode.StatusBarItem | undefined} */
let statusBar;
/** @type {{mode: string, command: string, args: string[]} | undefined} */
let currentServer;
/** @type {{mode: string, command: string, args: string[]} | undefined} */
let currentCompiler;
/** @type {NodeJS.Timeout | undefined} */
let updateTimer;

const DEFAULT_TOOLCHAIN_UPDATE_MANIFEST_URL = 'https://raw.githubusercontent.com/Pppp1116/ASTRA/main/registry/toolchain-updates.json';
const UPDATE_LAST_CHECK_KEY = 'toolchain.update.lastCheckTs';
const UPDATE_LAST_PROMPT_KEY = 'toolchain.update.lastPromptVersion';

const POSIX_LAUNCHER = `#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="\${ASTRA_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi
export PYTHONPATH="$ROOT"
export ASTRA_STDLIB_PATH="$ROOT/astra/stdlib"
export ASTRA_RUNTIME_C_PATH="$ROOT/astra/assets/runtime/llvm_runtime.c"
exec "$PY" -m $MODULE "$@"
`;

function windowsLauncher(moduleName) {
  return `@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
set "ASTRA_STDLIB_PATH=%ROOT%\\astra\\stdlib"
set "ASTRA_RUNTIME_C_PATH=%ROOT%\\astra\\assets\\runtime\\llvm_runtime.c"
"%PY%" -m ${moduleName} %*
`;
}

function getConfig() {
  return vscode.workspace.getConfiguration('astra');
}

function parseVersion(versionText) {
  if (!versionText || typeof versionText !== 'string') {
    return [0, 0, 0];
  }
  const parts = versionText.split('.').slice(0, 3).map((part) => {
    const num = Number.parseInt(String(part).replace(/[^0-9].*$/, ''), 10);
    return Number.isFinite(num) ? num : 0;
  });
  while (parts.length < 3) {
    parts.push(0);
  }
  return parts;
}

function compareVersions(a, b) {
  const av = parseVersion(a);
  const bv = parseVersion(b);
  for (let i = 0; i < 3; i += 1) {
    if (av[i] < bv[i]) {
      return -1;
    }
    if (av[i] > bv[i]) {
      return 1;
    }
  }
  return 0;
}

function fetchJson(urlText) {
  return new Promise((resolve, reject) => {
    const client = urlText.startsWith('https://') ? https : http;
    const req = client.get(urlText, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`request failed with status ${res.statusCode}`));
        return;
      }
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
        } catch (error) {
          reject(error);
        }
      });
    });
    req.setTimeout(10000, () => {
      req.destroy(new Error('request timeout'));
    });
    req.on('error', (error) => reject(error));
  });
}

function getPrimaryWorkspacePath() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return undefined;
  }
  return folders[0].uri.fsPath;
}

function getGlobalToolchainRoot(context) {
  return path.join(context.globalStorageUri.fsPath, 'toolchain');
}

function renderPosixLauncher(moduleName) {
  return POSIX_LAUNCHER.replace('$MODULE', moduleName);
}

function ensureExecutable(filePath) {
  if (process.platform === 'win32') {
    return;
  }
  const mode = fs.statSync(filePath).mode;
  fs.chmodSync(filePath, mode | 0o111);
}

function writeFileIfChanged(filePath, content, executable = false) {
  let prev = undefined;
  if (fs.existsSync(filePath)) {
    prev = fs.readFileSync(filePath, 'utf8');
  } else {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  }
  if (prev !== content) {
    fs.writeFileSync(filePath, content, 'utf8');
  }
  if (executable) {
    ensureExecutable(filePath);
  }
}

function ensureGlobalToolchain(context) {
  const root = getGlobalToolchainRoot(context);
  const srcAstra = path.join(context.extensionPath, 'server', 'astra');
  const dstAstra = path.join(root, 'astra');
  if (!fs.existsSync(srcAstra)) {
    return undefined;
  }
  fs.mkdirSync(root, { recursive: true });
  const markerPath = path.join(root, '.toolchain-version');
  const bundledVersion = String((context.extension && context.extension.packageJSON && context.extension.packageJSON.version) || '0.0.0');
  let installedVersion = '0.0.0';
  if (fs.existsSync(markerPath)) {
    installedVersion = fs.readFileSync(markerPath, 'utf8').trim() || '0.0.0';
  }
  if (!fs.existsSync(dstAstra) || compareVersions(installedVersion, bundledVersion) < 0) {
    fs.cpSync(srcAstra, dstAstra, { recursive: true, force: true });
    fs.writeFileSync(markerPath, `${bundledVersion}\n`, 'utf8');
  }

  const binDir = path.join(root, 'bin');
  fs.mkdirSync(binDir, { recursive: true });
  writeFileIfChanged(path.join(binDir, 'astra'), renderPosixLauncher('astra.cli'), true);
  writeFileIfChanged(path.join(binDir, 'astlsp'), renderPosixLauncher('astra.lsp'), true);
  writeFileIfChanged(path.join(binDir, 'astpm'), renderPosixLauncher('astra.pkg'), true);
  writeFileIfChanged(path.join(binDir, 'astra.cmd'), windowsLauncher('astra.cli'));
  writeFileIfChanged(path.join(binDir, 'astlsp.cmd'), windowsLauncher('astra.lsp'));
  writeFileIfChanged(path.join(binDir, 'astpm.cmd'), windowsLauncher('astra.pkg'));
  return root;
}

function ensureOutput(context) {
  if (!output) {
    output = vscode.window.createOutputChannel('Astra');
    context.subscriptions.push(output);
  }
  return output;
}

function ensureStatusBar(context) {
  if (!statusBar) {
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 40);
    statusBar.name = 'Astra Language Server';
    statusBar.command = 'astra.showLanguageServerStatus';
    statusBar.text = '$(sync~spin) Astra: starting';
    statusBar.tooltip = 'Astra language server';
    statusBar.show();
    context.subscriptions.push(statusBar);
  }
  return statusBar;
}

function setStatus(text, tooltip) {
  if (!statusBar) {
    return;
  }
  statusBar.text = text;
  statusBar.tooltip = tooltip;
}

function mapTrace(value) {
  if (value === 'verbose') {
    return Trace.Verbose;
  }
  if (value === 'messages') {
    return Trace.Messages;
  }
  return Trace.Off;
}

function checkCommand(command, args) {
  const probe = spawnSync(command, [...args, '--version'], { encoding: 'utf8' });
  return probe.status === 0;
}

function findPython(overridePath) {
  if (overridePath) {
    return { command: overridePath, prefixArgs: [] };
  }

  const candidates = process.platform === 'win32'
    ? [
        { command: 'py', prefixArgs: ['-3'] },
        { command: 'python', prefixArgs: [] },
        { command: 'python3', prefixArgs: [] }
      ]
    : [
        { command: 'python3', prefixArgs: [] },
        { command: 'python', prefixArgs: [] }
      ];

  for (const candidate of candidates) {
    if (checkCommand(candidate.command, candidate.prefixArgs)) {
      return candidate;
    }
  }
  return undefined;
}

function bundledServer(context) {
  const config = getConfig();
  const override = config.get('languageServer.pythonPath', '').trim();
  const python = findPython(override);
  if (!python) {
    return undefined;
  }

  const script = path.join(context.extensionPath, 'server', 'run_lsp.py');
  const stdlibPath = path.join(context.extensionPath, 'server', 'astra', 'stdlib');
  if (!fs.existsSync(script) || !fs.existsSync(stdlibPath)) {
    return undefined;
  }

  return {
    command: python.command,
    args: [...python.prefixArgs, script],
    options: {
      env: {
        ...process.env,
        ASTRA_STDLIB_PATH: stdlibPath
      }
    }
  };
}

function externalServer() {
  const config = getConfig();
  const command = config.get('languageServer.command', '').trim();
  const args = config.get('languageServer.args', []);
  if (!command) {
    return undefined;
  }
  return { command, args };
}

function workspaceToolchainServer() {
  const root = getPrimaryWorkspacePath();
  if (!root) {
    return undefined;
  }
  const binName = process.platform === 'win32' ? 'astlsp.cmd' : 'astlsp';
  const exe = path.join(root, 'dist', 'toolchain', 'bin', binName);
  if (!fs.existsSync(exe)) {
    return undefined;
  }
  return { command: exe, args: [] };
}

function globalToolchainServer(context) {
  const root = ensureGlobalToolchain(context);
  if (!root) {
    return undefined;
  }
  const binName = process.platform === 'win32' ? 'astlsp.cmd' : 'astlsp';
  const exe = path.join(root, 'bin', binName);
  if (!fs.existsSync(exe)) {
    return undefined;
  }
  return { command: exe, args: [] };
}

function resolveServer(context) {
  const config = getConfig();
  const mode = config.get('languageServer.mode', 'bundled');

  if (mode === 'external') {
    const external = externalServer();
    if (external) {
      currentServer = { mode: 'external', command: external.command, args: external.args || [] };
      return external;
    }
    throw new Error('Astra is configured for external server mode, but astra.languageServer.command is empty.');
  }

  const globalServer = globalToolchainServer(context);
  if (globalServer) {
    currentServer = { mode: 'global-toolchain', command: globalServer.command, args: globalServer.args || [] };
    return globalServer;
  }

  const workspaceServer = workspaceToolchainServer();
  if (workspaceServer) {
    currentServer = { mode: 'workspace-toolchain', command: workspaceServer.command, args: workspaceServer.args || [] };
    return workspaceServer;
  }

  const bundled = bundledServer(context);
  if (bundled) {
    currentServer = { mode: 'bundled', command: bundled.command, args: bundled.args || [] };
    return bundled;
  }

  const external = externalServer();
  if (external) {
    currentServer = { mode: 'external-fallback', command: external.command, args: external.args || [] };
    return external;
  }

  throw new Error('Could not start bundled Astra server. Install Python 3.11+ or set astra.languageServer.command.');
}

function bundledCompiler(context) {
  const config = getConfig();
  const override = config.get('compiler.pythonPath', '').trim() || config.get('languageServer.pythonPath', '').trim();
  const python = findPython(override);
  if (!python) {
    return undefined;
  }

  const script = path.join(context.extensionPath, 'server', 'run_cli.py');
  const stdlibPath = path.join(context.extensionPath, 'server', 'astra', 'stdlib');
  const runtimePath = path.join(context.extensionPath, 'server', 'astra', 'assets', 'runtime', 'llvm_runtime.c');
  if (!fs.existsSync(script) || !fs.existsSync(stdlibPath)) {
    return undefined;
  }

  return {
    command: python.command,
    args: [...python.prefixArgs, script],
    options: {
      env: {
        ...process.env,
        ASTRA_STDLIB_PATH: stdlibPath,
        ASTRA_RUNTIME_C_PATH: runtimePath
      }
    }
  };
}

function externalCompiler() {
  const config = getConfig();
  const command = config.get('compiler.command', '').trim();
  const args = config.get('compiler.args', []);
  if (!command) {
    return undefined;
  }
  return { command, args };
}

function workspaceToolchainCompiler() {
  const root = getPrimaryWorkspacePath();
  if (!root) {
    return undefined;
  }
  const binName = process.platform === 'win32' ? 'astra.cmd' : 'astra';
  const exe = path.join(root, 'dist', 'toolchain', 'bin', binName);
  if (!fs.existsSync(exe)) {
    return undefined;
  }
  return { command: exe, args: [] };
}

function globalToolchainCompiler(context) {
  const root = ensureGlobalToolchain(context);
  if (!root) {
    return undefined;
  }
  const binName = process.platform === 'win32' ? 'astra.cmd' : 'astra';
  const exe = path.join(root, 'bin', binName);
  if (!fs.existsSync(exe)) {
    return undefined;
  }
  return { command: exe, args: [] };
}

function resolveCompiler(context) {
  const config = getConfig();
  const mode = config.get('compiler.mode', 'bundled');
  if (mode === 'external') {
    const external = externalCompiler();
    if (external) {
      currentCompiler = { mode: 'external', command: external.command, args: external.args || [] };
      return external;
    }
    throw new Error('Astra compiler is configured for external mode, but astra.compiler.command is empty.');
  }

  const globalCompiler = globalToolchainCompiler(context);
  if (globalCompiler) {
    currentCompiler = { mode: 'global-toolchain', command: globalCompiler.command, args: globalCompiler.args || [] };
    return globalCompiler;
  }

  const workspaceCompiler = workspaceToolchainCompiler();
  if (workspaceCompiler) {
    currentCompiler = { mode: 'workspace-toolchain', command: workspaceCompiler.command, args: workspaceCompiler.args || [] };
    return workspaceCompiler;
  }

  const bundled = bundledCompiler(context);
  if (bundled) {
    currentCompiler = { mode: 'bundled', command: bundled.command, args: bundled.args || [] };
    return bundled;
  }

  const external = externalCompiler();
  if (external) {
    currentCompiler = { mode: 'external-fallback', command: external.command, args: external.args || [] };
    return external;
  }

  throw new Error('Could not start bundled Astra compiler. Install Python 3.11+ or set astra.compiler.command.');
}

function spawnAndCapture(executable, args, cwd, channel) {
  return new Promise((resolve, reject) => {
    const mergedEnv = {
      ...process.env,
      ...((executable.options && executable.options.env) || {})
    };
    const proc = spawn(
      executable.command,
      [...(executable.args || []), ...args],
      {
        cwd,
        env: mergedEnv
      }
    );

    proc.stdout.on('data', (chunk) => {
      channel.append(chunk.toString());
    });
    proc.stderr.on('data', (chunk) => {
      channel.append(chunk.toString());
    });
    proc.on('error', (error) => reject(error));
    proc.on('close', (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`process exited with status ${code}`));
    });
  });
}

function defaultBuildOutput(srcPath, target, outputDir) {
  const stem = path.parse(srcPath).name;
  if (target === 'py') {
    return path.join(outputDir, `${stem}.py`);
  }
  if (target === 'llvm') {
    return path.join(outputDir, `${stem}.ll`);
  }
  const ext = process.platform === 'win32' ? '.exe' : '';
  return path.join(outputDir, `${stem}${ext}`);
}

async function buildCurrentFile(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== 'astra') {
    void vscode.window.showErrorMessage('Open an Astra file to build.');
    return;
  }
  if (editor.document.uri.scheme !== 'file') {
    void vscode.window.showErrorMessage('Save this Astra file to disk before building.');
    return;
  }
  if (editor.document.isDirty) {
    const saved = await editor.document.save();
    if (!saved) {
      void vscode.window.showErrorMessage('Build cancelled because the file could not be saved.');
      return;
    }
  }

  const config = getConfig();
  const target = config.get('compiler.target', 'native');
  const outputDirSetting = config.get('compiler.outputDir', '.astra-build').trim() || '.astra-build';
  const extraArgsRaw = config.get('compiler.buildArgs', []);
  const extraArgs = Array.isArray(extraArgsRaw) ? extraArgsRaw.filter((arg) => typeof arg === 'string') : [];
  const sourcePath = editor.document.uri.fsPath;
  const workspace = vscode.workspace.getWorkspaceFolder(editor.document.uri);
  const baseDir = workspace ? workspace.uri.fsPath : path.dirname(sourcePath);
  const outputDir = path.isAbsolute(outputDirSetting) ? outputDirSetting : path.join(baseDir, outputDirSetting);
  fs.mkdirSync(outputDir, { recursive: true });
  const outputPath = defaultBuildOutput(sourcePath, target, outputDir);
  const compiler = resolveCompiler(context);

  const channel = ensureOutput(context);
  channel.show(true);
  channel.appendLine(`building ${sourcePath}`);
  channel.appendLine(`output: ${outputPath}`);
  channel.appendLine(`target: ${target}`);
  channel.appendLine(`compiler (${currentCompiler.mode}): ${compiler.command} ${(compiler.args || []).join(' ')}`);

  const args = ['build', sourcePath, '-o', outputPath, '--target', target, ...extraArgs];
  try {
    await spawnAndCapture(compiler, args, baseDir, channel);
    channel.appendLine('build finished successfully');
    void vscode.window.showInformationMessage(`Astra build succeeded: ${path.basename(outputPath)}`);
  } catch (error) {
    channel.appendLine(`build failed: ${String(error)}`);
    void vscode.window.showErrorMessage(`Astra build failed: ${String(error)}`);
  }
}

function attachClientStateLogging() {
  if (!client || !output) {
    return;
  }
  client.onDidChangeState((event) => {
    output.appendLine(`state: ${event.oldState} -> ${event.newState}`);
    if (event.newState === State.Running) {
      setStatus('$(check) Astra: ready', 'Astra language server is running');
    } else {
      setStatus('$(warning) Astra: stopped', 'Astra language server is not running');
    }
  });
}

async function startClient(context) {
  const channel = ensureOutput(context);
  ensureStatusBar(context);
  setStatus('$(sync~spin) Astra: starting', 'Starting Astra language server');

  const executable = resolveServer(context);
  channel.appendLine(`starting server (${currentServer.mode}): ${executable.command} ${(executable.args || []).join(' ')}`);

  const serverOptions = {
    run: executable,
    debug: executable
  };

  const clientOptions = {
    documentSelector: [
      { scheme: 'file', language: 'astra' },
      { scheme: 'untitled', language: 'astra' }
    ],
    outputChannel: channel,
    synchronize: {
      fileEvents: vscode.workspace.createFileSystemWatcher('**/*.astra')
    }
  };

  client = new LanguageClient('astra-lsp', 'Astra Language Server', serverOptions, clientOptions);
  client.setTrace(mapTrace(getConfig().get('trace.server', 'off')));
  attachClientStateLogging();
  context.subscriptions.push(client.start());
}

async function stopClient() {
  if (!client) {
    return;
  }
  const current = client;
  client = undefined;
  await current.stop();
}

async function restartClient(context) {
  await stopClient();
  await startClient(context);
  void vscode.window.showInformationMessage('Astra language server restarted.');
}

function formatServerStatus() {
  if (!currentServer && !currentCompiler) {
    return 'Astra server/compiler: not started yet';
  }
  const lines = [];
  if (currentServer) {
    lines.push(`Server mode: ${currentServer.mode}`);
    lines.push(`Server command: ${currentServer.command}`);
    lines.push(`Server args: ${currentServer.args.join(' ') || '(none)'}`);
  } else {
    lines.push('Server mode: not started');
  }
  if (currentCompiler) {
    lines.push(`Compiler mode: ${currentCompiler.mode}`);
    lines.push(`Compiler command: ${currentCompiler.command}`);
    lines.push(`Compiler args: ${currentCompiler.args.join(' ') || '(none)'}`);
  } else {
    lines.push('Compiler mode: not resolved yet');
  }
  return lines.join('\n');
}

function selectUpdateEntry(manifest, channel) {
  if (!manifest || typeof manifest !== 'object') {
    return undefined;
  }
  const preferred = manifest[channel];
  if (preferred && typeof preferred === 'object') {
    return preferred;
  }
  if (manifest.stable && typeof manifest.stable === 'object') {
    return manifest.stable;
  }
  return undefined;
}

async function checkForToolchainUpdates(context, force = false) {
  const config = getConfig();
  const enabled = Boolean(config.get('toolchain.autoUpdateCheck', false));
  if (!enabled && !force) {
    return;
  }

  const intervalHoursRaw = Number(config.get('toolchain.checkIntervalHours', 24));
  const intervalHours = Number.isFinite(intervalHoursRaw) && intervalHoursRaw > 0 ? intervalHoursRaw : 24;
  const now = Date.now();
  const lastCheck = Number(context.globalState.get(UPDATE_LAST_CHECK_KEY, 0));
  if (!force && now - lastCheck < intervalHours * 60 * 60 * 1000) {
    return;
  }

  await context.globalState.update(UPDATE_LAST_CHECK_KEY, now);
  const channel = ensureOutput(context);
  const manifestUrl = String(config.get('toolchain.updateManifestUrl', DEFAULT_TOOLCHAIN_UPDATE_MANIFEST_URL)).trim();
  const updateChannel = String(config.get('toolchain.updateChannel', 'stable')).trim() || 'stable';
  if (!manifestUrl) {
    channel.appendLine('toolchain update check skipped: manifest URL is empty');
    return;
  }

  let manifest;
  try {
    manifest = await fetchJson(manifestUrl);
  } catch (error) {
    channel.appendLine(`toolchain update check failed: ${String(error)}`);
    return;
  }

  const entry = selectUpdateEntry(manifest, updateChannel);
  if (!entry || typeof entry.version !== 'string') {
    channel.appendLine('toolchain update check: no compatible entry in manifest');
    return;
  }

  const currentVersion = String((context.extension && context.extension.packageJSON && context.extension.packageJSON.version) || '0.0.0');
  if (compareVersions(entry.version, currentVersion) <= 0) {
    if (force) {
      void vscode.window.showInformationMessage(`Astra toolchain is up to date (${currentVersion}).`);
    }
    return;
  }

  if (entry.minExtensionVersion && compareVersions(currentVersion, String(entry.minExtensionVersion)) < 0) {
    channel.appendLine(
      `toolchain update ${entry.version} requires extension >= ${entry.minExtensionVersion}; current is ${currentVersion}`
    );
    return;
  }

  const lastPrompted = String(context.globalState.get(UPDATE_LAST_PROMPT_KEY, ''));
  if (!force && lastPrompted === entry.version) {
    return;
  }

  await context.globalState.update(UPDATE_LAST_PROMPT_KEY, entry.version);
  const message = `A new Astra toolchain version is available: ${entry.version} (current ${currentVersion}).`;
  const action = await vscode.window.showInformationMessage(message, 'Open Download', 'Release Notes', 'Later');
  if (action === 'Open Download' && entry.downloadUrl) {
    await vscode.env.openExternal(vscode.Uri.parse(String(entry.downloadUrl)));
  } else if (action === 'Release Notes' && entry.notesUrl) {
    await vscode.env.openExternal(vscode.Uri.parse(String(entry.notesUrl)));
  }
}

function scheduleToolchainUpdateChecks(context) {
  if (updateTimer) {
    clearInterval(updateTimer);
    updateTimer = undefined;
  }
  const config = getConfig();
  if (!Boolean(config.get('toolchain.autoUpdateCheck', false))) {
    return;
  }
  const intervalHoursRaw = Number(config.get('toolchain.checkIntervalHours', 24));
  const intervalHours = Number.isFinite(intervalHoursRaw) && intervalHoursRaw > 0 ? intervalHoursRaw : 24;
  const intervalMs = intervalHours * 60 * 60 * 1000;
  updateTimer = setInterval(() => {
    void checkForToolchainUpdates(context, false);
  }, intervalMs);
  context.subscriptions.push({
    dispose() {
      if (updateTimer) {
        clearInterval(updateTimer);
        updateTimer = undefined;
      }
    }
  });
}

async function activate(context) {
  ensureOutput(context);
  ensureStatusBar(context);

  const restartDisposable = vscode.commands.registerCommand('astra.restartLanguageServer', async () => {
    try {
      await restartClient(context);
    } catch (error) {
      setStatus('$(error) Astra: failed', 'Astra language server failed to start');
      void vscode.window.showErrorMessage(`Astra restart failed: ${String(error)}`);
    }
  });
  context.subscriptions.push(restartDisposable);

  const statusDisposable = vscode.commands.registerCommand('astra.showLanguageServerStatus', async () => {
    const choice = await vscode.window.showInformationMessage(formatServerStatus(), 'Restart', 'Open Log', 'Check Updates');
    if (choice === 'Restart') {
      await vscode.commands.executeCommand('astra.restartLanguageServer');
      return;
    }
    if (choice === 'Open Log' && output) {
      output.show(true);
      return;
    }
    if (choice === 'Check Updates') {
      await vscode.commands.executeCommand('astra.checkForToolchainUpdates');
    }
  });
  context.subscriptions.push(statusDisposable);

  const openLogDisposable = vscode.commands.registerCommand('astra.openExtensionLog', async () => {
    if (output) {
      output.show(true);
    }
  });
  context.subscriptions.push(openLogDisposable);

  const buildDisposable = vscode.commands.registerCommand('astra.buildCurrentFile', async () => {
    try {
      await buildCurrentFile(context);
    } catch (error) {
      void vscode.window.showErrorMessage(`Astra build command failed: ${String(error)}`);
    }
  });
  context.subscriptions.push(buildDisposable);

  const updatesDisposable = vscode.commands.registerCommand('astra.checkForToolchainUpdates', async () => {
    await checkForToolchainUpdates(context, true);
  });
  context.subscriptions.push(updatesDisposable);

  const configDisposable = vscode.workspace.onDidChangeConfiguration(async (event) => {
    if (
      event.affectsConfiguration('astra.languageServer.mode') ||
      event.affectsConfiguration('astra.languageServer.command') ||
      event.affectsConfiguration('astra.languageServer.pythonPath') ||
      event.affectsConfiguration('astra.languageServer.args') ||
      event.affectsConfiguration('astra.trace.server') ||
      event.affectsConfiguration('astra.toolchain.autoUpdateCheck') ||
      event.affectsConfiguration('astra.toolchain.checkIntervalHours') ||
      event.affectsConfiguration('astra.toolchain.updateManifestUrl') ||
      event.affectsConfiguration('astra.toolchain.updateChannel')
    ) {
      try {
        await restartClient(context);
        if (
          event.affectsConfiguration('astra.toolchain.autoUpdateCheck') ||
          event.affectsConfiguration('astra.toolchain.checkIntervalHours') ||
          event.affectsConfiguration('astra.toolchain.updateManifestUrl') ||
          event.affectsConfiguration('astra.toolchain.updateChannel')
        ) {
          scheduleToolchainUpdateChecks(context);
          void checkForToolchainUpdates(context, false);
        }
      } catch (error) {
        setStatus('$(error) Astra: failed', 'Astra language server failed to start');
        void vscode.window.showErrorMessage(`Astra configuration update failed: ${String(error)}`);
      }
    }
  });
  context.subscriptions.push(configDisposable);

  try {
    ensureGlobalToolchain(context);
    await startClient(context);
    scheduleToolchainUpdateChecks(context);
    void checkForToolchainUpdates(context, false);
  } catch (error) {
    setStatus('$(error) Astra: failed', 'Astra language server failed to start');
    void vscode.window.showErrorMessage(`Astra language server failed to start: ${String(error)}`);
  }
}

async function deactivate() {
  if (updateTimer) {
    clearInterval(updateTimer);
    updateTimer = undefined;
  }
  await stopClient();
}

module.exports = {
  activate,
  deactivate
};
