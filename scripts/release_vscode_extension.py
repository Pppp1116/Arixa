#!/usr/bin/env python3
"""One-command VS Code extension package/publish flow.

Always refreshes syntax + bundled server before packaging/publishing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "editors" / "vscode"
PACKAGE_JSON = EXT_DIR / "package.json"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def bump_patch_version() -> str:
    """Bump extension version by the smallest SemVer increment (patch)."""
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    current = str(pkg.get("version", "")).strip()
    parts = current.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"unsupported extension version format in {PACKAGE_JSON}: {current!r}")
    major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    new_version = f"{major}.{minor}.{patch + 1}"
    pkg["version"] = new_version
    PACKAGE_JSON.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
    print(f"+ bump extension version: {current} -> {new_version}")
    return new_version


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="Publish to VS Code Marketplace (requires VSCE_PAT).")
    ap.add_argument("--npm-update", action="store_true", help="Run npm update before package/publish.")
    args = ap.parse_args()

    run(["python", "scripts/sync_editor_tools.py"])
    run(["python", "scripts/verify_editor_sync.py"])
    run(["python", "scripts/build_vscode_bundle.py"])
    bump_patch_version()

    run(["npm", "install"], cwd=EXT_DIR)
    if args.npm_update:
        run(["npm", "update"], cwd=EXT_DIR)

    if args.publish:
        pat = os.environ.get("VSCE_PAT", "").strip()
        if not pat:
            raise SystemExit("VSCE_PAT is required for --publish")
        run(["npx", "@vscode/vsce", "publish", "--allow-missing-repository", "--pat", pat], cwd=EXT_DIR)
    else:
        run(["npx", "@vscode/vsce", "package", "--allow-missing-repository"], cwd=EXT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
