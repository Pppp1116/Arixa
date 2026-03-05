const path = require('path');
const { spawnSync } = require('child_process');

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const script = path.join(repoRoot, 'scripts', 'build_vscode_bundle.py');

const candidates = process.platform === 'win32'
  ? [['py', ['-3']], ['python', []], ['python3', []]]
  : [['python3', []], ['python', []]];

for (const [cmd, baseArgs] of candidates) {
  const run = spawnSync(cmd, [...baseArgs, script], {
    cwd: repoRoot,
    stdio: 'inherit'
  });
  if (run.status === 0) {
    process.exit(0);
  }
}

console.error('failed to refresh bundled VS Code server; install Python 3.11+');
process.exit(1);
