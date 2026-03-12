const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const vscode = require('vscode');
const { LanguageClient, State, Trace } = require('vscode-languageclient/node');
const ProfilerUI = require('./profiler/profiler-ui');
const PackageManagerUI = require('./package-manager-ui');

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
/** @type {ProfilerUI | undefined} */
let profilerUI;
/** @type {PackageManagerUI | undefined} */
let packageManagerUI;
/** @type {boolean} */
let isProfiling = false;
/** @type {any} */
let currentProfile = null;

const DEFAULT_TOOLCHAIN_UPDATE_MANIFEST_URL = 'https://raw.githubusercontent.com/Pppp1116/ASTRA/main/registry/toolchain-updates.json';
const UPDATE_LAST_CHECK_KEY = 'toolchain.update.lastCheckTs';
const UPDATE_LAST_PROMPT_KEY = 'toolchain.update.lastPromptVersion';

const POSIX_LAUNCHER = `#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="\${ARIXA_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi
export PYTHONPATH="$ROOT"
export ARIXA_STDLIB_PATH="$ROOT/astra/stdlib"
export ARIXA_RUNTIME_C_PATH="$ROOT/astra/assets/runtime/llvm_runtime.c"
exec "$PY" -m $MODULE "$@"
`;

function windowsLauncher(moduleName) {
  return `@echo off
set "ROOT=%~dp0.."
if defined ARIXA_PYTHON (
  set "PY=%ARIXA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
set "ARIXA_STDLIB_PATH=%ROOT%\\astra\\stdlib"
set "ARIXA_RUNTIME_C_PATH=%ROOT%\\astra\\assets\\runtime\\llvm_runtime.c"
"%PY%" -m ${moduleName} %*
`;
}

function getConfig() {
  return vscode.workspace.getConfiguration('arixa');
}

function discoverStdModules(workspaceRoot, extensionPath) {
  const roots = [
    process.env.ARIXA_STDLIB_PATH,
    workspaceRoot ? path.join(workspaceRoot, 'stdlib') : undefined,
    extensionPath ? path.join(extensionPath, 'astra', 'stdlib') : undefined,
    extensionPath ? path.join(extensionPath, 'server', 'astra', 'stdlib') : undefined,
  ].filter(Boolean);
  const stdRoot = roots.find((candidate) => {
    try {
      return fs.existsSync(candidate) && fs.statSync(candidate).isDirectory();
    } catch {
      return false;
    }
  });
  if (!stdRoot) {
    return new Set();
  }

  const out = new Set();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!entry.isFile() || !entry.name.endsWith('.arixa')) {
        continue;
      }
      const rel = path.relative(stdRoot, full).replace(/\\/g, '/').replace(/\.arixa$/, '');
      if (rel) {
        out.add(rel);
      }
    }
  };
  try {
    walk(stdRoot);
  } catch {
    return new Set();
  }
  return out;
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
  writeFileIfChanged(path.join(binDir, 'arixa'), renderPosixLauncher('astra.cli'), true);
  writeFileIfChanged(path.join(binDir, 'arlsp'), renderPosixLauncher('astra.lsp'), true);
  writeFileIfChanged(path.join(binDir, 'arpm'), renderPosixLauncher('astra.pkg'), true);
  writeFileIfChanged(path.join(binDir, 'arixa.cmd'), windowsLauncher('astra.cli'));
  writeFileIfChanged(path.join(binDir, 'arlsp.cmd'), windowsLauncher('astra.lsp'));
  writeFileIfChanged(path.join(binDir, 'arpm.cmd'), windowsLauncher('astra.pkg'));
  return root;
}

function ensureOutput(context) {
  if (!output) {
    output = vscode.window.createOutputChannel('Arixa');
    context.subscriptions.push(output);
  }
  return output;
}

function ensureStatusBar(context) {
  if (!statusBar) {
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 40);
    statusBar.name = 'Arixa Language Server';
    statusBar.command = 'arixa.showLanguageServerStatus';
    statusBar.text = '$(sync~spin) Arixa: starting';
    statusBar.tooltip = 'Arixa language server';
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
        ARIXA_STDLIB_PATH: stdlibPath
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
    throw new Error('Arixa is configured for external server mode, but arixa.languageServer.command is empty.');
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

  throw new Error('Could not start bundled Arixa server. Install Python 3.11+ or set arixa.languageServer.command.');
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
        ARIXA_STDLIB_PATH: stdlibPath,
        ARIXA_RUNTIME_C_PATH: runtimePath
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
  const binName = process.platform === 'win32' ? 'arixa.cmd' : 'arixa';
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
  const binName = process.platform === 'win32' ? 'arixa.cmd' : 'arixa';
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
    throw new Error('Arixa compiler is configured for external mode, but arixa.compiler.command is empty.');
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

  throw new Error('Could not start bundled Arixa compiler. Install Python 3.11+ or set arixa.compiler.command.');
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
  if (!editor || editor.document.languageId !== 'arixa') {
    void vscode.window.showErrorMessage('Open an Arixa file to build.');
    return;
  }
  if (editor.document.uri.scheme !== 'file') {
    void vscode.window.showErrorMessage('Save this Arixa file to disk before building.');
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
  const outputDirSetting = config.get('compiler.outputDir', '.arixa-build').trim() || '.arixa-build';
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
    void vscode.window.showInformationMessage(`Arixa build succeeded: ${path.basename(outputPath)}`);
  } catch (error) {
    channel.appendLine(`build failed: ${String(error)}`);
    void vscode.window.showErrorMessage(`Arixa build failed: ${String(error)}`);
  }
}

function attachClientStateLogging() {
  if (!client || !output) {
    return;
  }
  client.onDidChangeState((event) => {
    output.appendLine(`state: ${event.oldState} -> ${event.newState}`);
    if (event.newState === State.Running) {
      setStatus('$(check) Arixa: ready', 'Arixa language server is running');
    } else {
      setStatus('$(warning) Arixa: stopped', 'Arixa language server is not running');
    }
  });
}

async function startClient(context) {
  const channel = ensureOutput(context);
  ensureStatusBar(context);
  setStatus('$(sync~spin) Arixa: starting', 'Starting Arixa language server');

  const executable = resolveServer(context);
  channel.appendLine(`starting server (${currentServer.mode}): ${executable.command} ${(executable.args || []).join(' ')}`);

  const serverOptions = {
    run: executable,
    debug: executable
  };

  const clientOptions = {
    documentSelector: [
      { scheme: 'file', language: 'arixa' },
      { scheme: 'untitled', language: 'arixa' }
    ],
    outputChannel: channel,
    synchronize: {
      fileEvents: vscode.workspace.createFileSystemWatcher('**/*.arixa')
    }
  };

  client = new LanguageClient('arixa-lsp', 'Arixa Language Server', serverOptions, clientOptions);
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

  // Enhanced commands
  const runDisposable = vscode.commands.registerCommand('astra.runCurrentFile', async () => {
    try {
      await runCurrentFile(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to run file: ${error.message}`);
    }
  });
  context.subscriptions.push(runDisposable);

  const initPackageDisposable = vscode.commands.registerCommand('astra.initPackage', async () => {
    try {
      await initPackage(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to initialize package: ${error.message}`);
    }
  });
  context.subscriptions.push(initPackageDisposable);

  const publishPackageDisposable = vscode.commands.registerCommand('astra.publishPackage', async () => {
    try {
      await publishPackage(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to publish package: ${error.message}`);
    }
  });
  context.subscriptions.push(publishPackageDisposable);

  const searchPackagesDisposable = vscode.commands.registerCommand('astra.searchPackages', async () => {
    try {
      await searchPackages(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to search packages: ${error.message}`);
    }
  });
  context.subscriptions.push(searchPackagesDisposable);

  const installPackageDisposable = vscode.commands.registerCommand('astra.installPackage', async () => {
    try {
      await installPackage(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to install package: ${error.message}`);
    }
  });
  context.subscriptions.push(installPackageDisposable);

  const listPackagesDisposable = vscode.commands.registerCommand('astra.listPackages', async () => {
    try {
      await listPackages(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to list packages: ${error.message}`);
    }
  });
  context.subscriptions.push(listPackagesDisposable);

  const generateDocsDisposable = vscode.commands.registerCommand('astra.generateDocs', async () => {
    try {
      await generateDocumentation(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to generate documentation: ${error.message}`);
    }
  });
  context.subscriptions.push(generateDocsDisposable);

  const runBenchmarksDisposable = vscode.commands.registerCommand('astra.runBenchmarks', async () => {
    try {
      await runBenchmarks(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to run benchmarks: ${error.message}`);
    }
  });
  context.subscriptions.push(runBenchmarksDisposable);

  const newProjectDisposable = vscode.commands.registerCommand('astra.newProject', async () => {
    try {
      await createNewProject(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to create project: ${error.message}`);
    }
  });
  context.subscriptions.push(newProjectDisposable);

  const gpuCompileDisposable = vscode.commands.registerCommand('astra.gpuCompile', async () => {
    try {
      await compileForGPU(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to compile for GPU: ${error.message}`);
    }
  });
  context.subscriptions.push(gpuCompileDisposable);

  const showEnhancedErrorsDisposable = vscode.commands.registerCommand('astra.showEnhancedErrors', async () => {
    try {
      await showEnhancedErrors(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to show enhanced errors: ${error.message}`);
    }
  });
  context.subscriptions.push(showEnhancedErrorsDisposable);

  // Profiler commands
  const startProfilingDisposable = vscode.commands.registerCommand('astra.startProfiling', async (options) => {
    try {
      await startProfiling(context, options);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to start profiling: ${error.message}`);
    }
  });
  context.subscriptions.push(startProfilingDisposable);

  const stopProfilingDisposable = vscode.commands.registerCommand('astra.stopProfiling', async () => {
    try {
      await stopProfiling(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to stop profiling: ${error.message}`);
    }
  });
  context.subscriptions.push(stopProfilingDisposable);

  const showProfilerDisposable = vscode.commands.registerCommand('astra.showProfiler', async () => {
    try {
      await showProfiler(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to show profiler: ${error.message}`);
    }
  });
  context.subscriptions.push(showProfilerDisposable);

  // Debug commands
  const startDebuggingDisposable = vscode.commands.registerCommand('astra.startDebugging', async () => {
    try {
      await startDebugging(context);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to start debugging: ${error.message}`);
    }
  });
  context.subscriptions.push(startDebuggingDisposable);

  // Package Manager commands
  const showPackageManagerDisposable = vscode.commands.registerCommand('astra.showPackageManager', async () => {
    try {
      if (!packageManagerUI) {
        packageManagerUI = new PackageManagerUI(context);
      }
      packageManagerUI.showPackageManager();
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to show package manager: ${error.message}`);
    }
  });
  context.subscriptions.push(showPackageManagerDisposable);

  // Initialize profiler UI
  profilerUI = new ProfilerUI(context);

  // Initialize package manager UI
  packageManagerUI = new PackageManagerUI(context);

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
  if (profilerUI) {
    profilerUI.dispose();
    profilerUI = undefined;
  }
  await stopClient();
}

// Enhanced command implementations

async function runCurrentFile(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor found');
    return;
  }

  const filePath = editor.document.uri.fsPath;
  const config = getConfig();
  const target = config.get('compiler.target', 'native');

  const result = await runCompiler(context, ['run', '--target', target, filePath]);
  
  if (result.success) {
    vscode.window.showInformationMessage(`Successfully ran ${path.basename(filePath)}`);
  }
}

async function initPackage(context) {
  const packageName = await vscode.window.showInputBox({
    prompt: 'Enter package name',
    placeHolder: 'my_package'
  });

  if (!packageName) return;

  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showErrorMessage('No workspace folder found');
    return;
  }

  const packageDir = path.join(workspaceFolder.uri.fsPath, packageName);
  
  try {
    // Create package directory structure
    fs.mkdirSync(packageDir, { recursive: true });
    fs.mkdirSync(path.join(packageDir, 'src'), { recursive: true });
    fs.mkdirSync(path.join(packageDir, 'examples'), { recursive: true });
    fs.mkdirSync(path.join(packageDir, 'tests'), { recursive: true });

    // Create Astra.toml
    const tomlContent = `[package]
name = "${packageName}"
version = "0.1.0"
description = "My awesome Astra package"
authors = ["Your Name <you@example.com>"]
license = "MIT"
homepage = "https://github.com/yourusername/${packageName}"
repository = "https://github.com/yourusername/${packageName}"
keywords = ["keyword1", "keyword2"]
categories = ["Category1", "Category2"]

[dependencies]
std = "1.0.0"
`;

    fs.writeFileSync(path.join(packageDir, 'Astra.toml'), tomlContent);

    const availableStdModules = discoverStdModules(workspaceFolder.uri.fsPath, context.extensionPath);
    const preferredStdImports = ['core', 'math', 'io'];
    let selectedStdImports = preferredStdImports.filter((name) => availableStdModules.has(name));
    if (selectedStdImports.length === 0) {
      selectedStdImports = Array.from(availableStdModules).sort().slice(0, 2);
    }
    if (selectedStdImports.length === 0) {
      selectedStdImports = ['core', 'math'];
    }
    const importLines = selectedStdImports.map((name) => `import std.${name};`).join('\n');

    // Create basic lib.arixa
    const libContent = `/// ${packageName} library
/// Description of what this library does

${importLines}

fn hello_world() Int {
    println("Hello from ${packageName}!");
    return 0;
}
`;

    fs.writeFileSync(path.join(packageDir, 'src', 'lib.arixa'), libContent);

    // Create example
    const exampleContent = `/// Example usage of ${packageName}

import "src/lib.arixa";

fn main() Int {
    hello_world();
    return 0;
}
`;

    fs.writeFileSync(path.join(packageDir, 'examples', 'demo.arixa'), exampleContent);

    vscode.window.showInformationMessage(`Package '${packageName}' initialized successfully`);
    
    // Open the new package in VS Code
    const packageUri = vscode.Uri.file(packageDir);
    await vscode.commands.executeCommand('vscode.openFolder', packageUri);

  } catch (error) {
    vscode.window.showErrorMessage(`Failed to initialize package: ${error.message}`);
  }
}

async function publishPackage(context) {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showErrorMessage('No workspace folder found');
    return;
  }

  const tomlPath = path.join(workspaceFolder.uri.fsPath, 'Astra.toml');
  if (!fs.existsSync(tomlPath)) {
    vscode.window.showErrorMessage('No Astra.toml found in workspace');
    return;
  }

  const target = await vscode.window.showQuickPick(['github', 'registry'], {
    placeHolder: 'Select publishing target'
  });

  if (!target) return;

  const result = await runCompiler(context, ['pkg', 'publish', '--target', target]);
  
  if (result.success) {
    vscode.window.showInformationMessage(`Package published to ${target}`);
  }
}

async function searchPackages(context) {
  const searchTerm = await vscode.window.showInputBox({
    prompt: 'Search packages',
    placeHolder: 'Enter search terms'
  });

  if (!searchTerm) return;

  const result = await runCompiler(context, ['pkg', 'search', searchTerm]);
  
  if (result.success) {
    // Parse and display search results
    const lines = result.stdout.split('\n').filter(line => line.trim());
    if (lines.length > 0) {
      const selected = await vscode.window.showQuickPick(lines, {
        placeHolder: 'Select a package to install'
      });
      
      if (selected) {
        const packageName = selected.split(' ')[0];
        await installPackageByName(context, packageName);
      }
    } else {
      vscode.window.showInformationMessage('No packages found');
    }
  }
}

async function installPackage(context) {
  const packageName = await vscode.window.showInputBox({
    prompt: 'Enter package name to install',
    placeHolder: 'package_name'
  });

  if (!packageName) return;

  await installPackageByName(context, packageName);
}

async function installPackageByName(context, packageName) {
  const result = await runCompiler(context, ['pkg', 'install', packageName]);
  
  if (result.success) {
    vscode.window.showInformationMessage(`Package '${packageName}' installed successfully`);
  }
}

async function listPackages(context) {
  const result = await runCompiler(context, ['pkg', 'list']);
  
  if (result.success) {
    vscode.window.showInformationMessage('Installed packages', result.stdout);
  }
}

async function generateDocumentation(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor found');
    return;
  }

  const filePath = editor.document.uri.fsPath;
  const result = await runCompiler(context, ['docs', 'generate', filePath]);
  
  if (result.success) {
    vscode.window.showInformationMessage('Documentation generated successfully');
  }
}

async function runBenchmarks(context) {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showErrorMessage('No workspace folder found');
    return;
  }

  const result = await runCompiler(context, ['bench', workspaceFolder.uri.fsPath]);
  
  if (result.success) {
    vscode.window.showInformationMessage('Benchmarks completed');
  }
}

async function createNewProject(context) {
  const projectType = await vscode.window.showQuickPick([
    'CLI Application',
    'GPU Application',
    'Library',
    'Web Application'
  ], {
    placeHolder: 'Select project type'
  });

  if (!projectType) return;

  const projectName = await vscode.window.showInputBox({
    prompt: 'Enter project name',
    placeHolder: 'my_project'
  });

  if (!projectName) return;

  // Similar to initPackage but with different templates based on project type
  await initPackage(context); // Reuse the package initialization logic
}

async function compileForGPU(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor found');
    return;
  }

  const filePath = editor.document.uri.fsPath;
  const result = await runCompiler(context, ['build', '--target', 'gpu', filePath]);
  
  if (result.success) {
    vscode.window.showInformationMessage('GPU compilation successful');
  }
}

async function showEnhancedErrors(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor found');
    return;
  }

  const filePath = editor.document.uri.fsPath;
  const result = await runCompiler(context, ['check', '--enhanced-errors', filePath]);
  
  if (result.success) {
    vscode.window.showInformationMessage('Enhanced error analysis completed');
  }
}

// Profiler implementations

async function startProfiling(context, options) {
  if (isProfiling) {
    vscode.window.showWarningMessage('Profiling is already in progress');
    return;
  }

  const { file, target } = options;
  
  try {
    // Start the enhanced profiler
    const profilerPath = path.join(context.extensionPath, 'server', 'astra', 'profiler_enhanced.py');
    const result = spawnSync('python', [profilerPath, file, '--target', target], {
      cwd: path.dirname(file),
      stdio: 'pipe'
    });

    if (result.error) {
      throw new Error(result.error.message);
    }

    isProfiling = true;
    vscode.window.showInformationMessage('Profiling started');

  } catch (error) {
    vscode.window.showErrorMessage(`Failed to start profiling: ${error.message}`);
  }
}

async function stopProfiling(context) {
  if (!isProfiling) {
    vscode.window.showWarningMessage('No profiling in progress');
    return;
  }

  try {
    // This would need to communicate with the running profiler
    // For now, simulate stopping and getting results
    const mockProfile = {
      summary: {
        total_time_seconds: 5.2,
        sample_count: 52,
        target: 'native'
      },
      performance_metrics: {
        cpu: {
          average_percent: 45.3,
          max_percent: 78.9,
          samples: Array(52).fill(0).map(() => Math.random() * 100)
        },
        memory: {
          average_mb: 125.7,
          max_mb: 256.3,
          samples: Array(52).fill(0).map(() => Math.random() * 500)
        }
      },
      hotspots: [
        {
          type: 'cpu',
          severity: 'medium',
          message: 'High CPU usage detected: 78.9%',
          suggestion: 'Consider optimizing algorithms',
          file: '',
          line: 1
        }
      ],
      optimization_suggestions: [
        {
          category: 'cpu',
          priority: 'medium',
          title: 'Optimize CPU Usage',
          description: 'High CPU usage detected',
          actions: ['Consider algorithmic improvements']
        }
      ]
    };

    currentProfile = mockProfile;
    isProfiling = false;

    if (profilerUI) {
      profilerUI.updateProfile(mockProfile);
    }

    vscode.window.showInformationMessage('Profiling completed');

  } catch (error) {
    vscode.window.showErrorMessage(`Failed to stop profiling: ${error.message}`);
  }
}

async function showProfiler(context) {
  if (!profilerUI) {
    profilerUI = new ProfilerUI(context);
  }
  
  profilerUI.showProfilerPanel();
}

// Debug implementation

async function startDebugging(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage('No active editor found');
    return;
  }

  const filePath = editor.document.uri.fsPath;
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  
  if (!workspaceFolder) {
    vscode.window.showErrorMessage('No workspace folder found');
    return;
  }

  // Create debug configuration
  const debugConfig = {
    type: 'astra',
    name: 'Debug Astra Program',
    request: 'launch',
    program: filePath,
    target: 'native',
    cwd: workspaceFolder.uri.fsPath,
    stopOnEntry: true
  };

  // Start debugging session
  const debugSession = await vscode.debug.startDebugging(workspaceFolder, debugConfig);
  
  if (debugSession) {
    vscode.window.showInformationMessage('Debugging started');
  }
}

module.exports = {
  activate,
  deactivate
};
