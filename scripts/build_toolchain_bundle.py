#!/usr/bin/env python3
"""Build a portable ASTRA toolchain bundle for distribution or VS Code embedding."""

from __future__ import annotations

import argparse
import compileall
import shutil
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_PACKAGE = REPO_ROOT / "astra"


RUN_LSP_PY = '''"""Bootstrap script for launching the bundled Astra LSP server copy."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ASTRA_STDLIB_PATH", str(ROOT / "astra" / "stdlib"))
os.environ.setdefault("ASTRA_RUNTIME_C_PATH", str(ROOT / "astra" / "assets" / "runtime" / "llvm_runtime.c"))

from astra.lsp import main


if __name__ == "__main__":
    main()
'''


RUN_CLI_PY = '''"""Bootstrap script for launching the bundled Astra CLI copy."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ASTRA_STDLIB_PATH", str(ROOT / "astra" / "stdlib"))
os.environ.setdefault("ASTRA_RUNTIME_C_PATH", str(ROOT / "astra" / "assets" / "runtime" / "llvm_runtime.c"))

from astra.cli import main


if __name__ == "__main__":
    main()
'''


ASTRA_SH = """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ASTRA_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi
export PYTHONPATH="$ROOT"
export ASTRA_STDLIB_PATH="$ROOT/astra/stdlib"
export ASTRA_RUNTIME_C_PATH="$ROOT/astra/assets/runtime/llvm_runtime.c"
exec "$PY" -m astra.cli "$@"
"""

ASTLSP_SH = """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ASTRA_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi
export PYTHONPATH="$ROOT"
export ASTRA_STDLIB_PATH="$ROOT/astra/stdlib"
export ASTRA_RUNTIME_C_PATH="$ROOT/astra/assets/runtime/llvm_runtime.c"
exec "$PY" -m astra.lsp "$@"
"""

ASTPM_SH = """#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ASTRA_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi
export PYTHONPATH="$ROOT"
exec "$PY" -m astra.pkg "$@"
"""

ASTRA_CMD = r"""@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
set "ASTRA_STDLIB_PATH=%ROOT%\\astra\\stdlib"
set "ASTRA_RUNTIME_C_PATH=%ROOT%\\astra\\assets\\runtime\\llvm_runtime.c"
"%PY%" -m astra.cli %*
"""

ASTLSP_CMD = r"""@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
set "ASTRA_STDLIB_PATH=%ROOT%\\astra\\stdlib"
set "ASTRA_RUNTIME_C_PATH=%ROOT%\\astra\\assets\\runtime\\llvm_runtime.c"
"%PY%" -m astra.lsp %*
"""

ASTPM_CMD = r"""@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
"%PY%" -m astra.pkg %*
"""


PORTABLE_README = """# Astra Toolchain Bundle

This directory contains a portable ASTRA compiler toolchain bundle.

Usage:
- Linux/macOS: `bin/astra`, `bin/astlsp`, `bin/astpm`
- Windows: `bin\\astra.cmd`, `bin\\astlsp.cmd`, `bin\\astpm.cmd`

If Python is not in PATH, set `ASTRA_PYTHON` to a Python 3.11+ executable.
"""


IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _copy_package(dst_root: Path) -> Path:
    dst_pkg = dst_root / "astra"
    if dst_pkg.exists():
        shutil.rmtree(dst_pkg)
    shutil.copytree(SRC_PACKAGE, dst_pkg, ignore=IGNORE_PATTERNS)
    return dst_pkg


def _write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _compile_bytecode(pkg_dir: Path) -> None:
    compileall.compile_dir(str(pkg_dir), quiet=1, force=True)


def build_bundle(output: Path, layout: str, compile_bytecode: bool, clean: bool) -> None:
    if clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    pkg_dir = _copy_package(output)
    if compile_bytecode:
        _compile_bytecode(pkg_dir)

    if layout == "portable":
        _write_file(output / "bin" / "astra", ASTRA_SH, executable=True)
        _write_file(output / "bin" / "astlsp", ASTLSP_SH, executable=True)
        _write_file(output / "bin" / "astpm", ASTPM_SH, executable=True)
        _write_file(output / "bin" / "astra.cmd", ASTRA_CMD)
        _write_file(output / "bin" / "astlsp.cmd", ASTLSP_CMD)
        _write_file(output / "bin" / "astpm.cmd", ASTPM_CMD)
        _write_file(output / "README.txt", PORTABLE_README)
        return

    if layout == "vscode":
        _write_file(output / "run_lsp.py", RUN_LSP_PY)
        _write_file(output / "run_cli.py", RUN_CLI_PY)
        return

    raise ValueError(f"unsupported layout: {layout}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build ASTRA distribution bundles")
    p.add_argument("--output", type=Path, required=True, help="destination directory")
    p.add_argument(
        "--layout",
        choices=["portable", "vscode"],
        default="portable",
        help="bundle layout type",
    )
    p.add_argument("--no-bytecode", action="store_true", help="skip precompiling Python bytecode")
    p.add_argument("--clean", action="store_true", help="remove output directory before bundling")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    out = ns.output.expanduser().resolve()
    build_bundle(out, ns.layout, compile_bytecode=not ns.no_bytecode, clean=ns.clean)
    print(f"bundle ready: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
