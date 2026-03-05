#!/usr/bin/env python3
"""Refresh the VS Code extension bundled ASTRA server copy."""

from __future__ import annotations

from pathlib import Path

from build_toolchain_bundle import REPO_ROOT, build_bundle


def main() -> int:
    out = (REPO_ROOT / "editors" / "vscode" / "server").resolve()
    build_bundle(out, layout="vscode", compile_bytecode=False, clean=False)
    print(f"vscode bundle ready: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
