#!/usr/bin/env python3
"""Update Python and VS Code extension dependencies to newest compatible versions."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "editors" / "vscode"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True)


def main() -> int:
    run(["python", "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run(["python", "-m", "pip", "install", "--upgrade", "llvmlite", "pytest", "pytest-cov", "hypothesis", "mutmut", "tomli"])
    run(["npm", "install"], cwd=EXT_DIR)
    run(["npm", "update"], cwd=EXT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
