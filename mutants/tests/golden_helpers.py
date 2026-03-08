from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pytest

from astra.build import build


@dataclass
class RunResult:
    backend: str
    returncode: int
    stdout: str
    stderr: str


def compile_and_run_program(
    tmp_path: Path,
    name: str,
    src_text: str,
    backends: Sequence[str] = ("py", "native"),
    timeout: float = 3.0,
) -> list[RunResult]:
    """
    Compile `src_text` under the given `name` for each requested backend and run it.

    This helper is intended for golden tests that assert consistent behavior
    across the Python and LLVM/native backends.
    """
    src = tmp_path / f"{name}.arixa"
    src.write_text(src_text)

    results: list[RunResult] = []

    if "py" in backends:
        out_py = tmp_path / f"{name}.py"
        state = build(str(src), str(out_py), "py")
        assert state in {"built", "cached"}
        cp = subprocess.run(
            [sys.executable, str(out_py)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        results.append(
            RunResult(
                backend="py",
                returncode=cp.returncode,
                stdout=cp.stdout,
                stderr=cp.stderr,
            )
        )

    if "native" in backends:
        if shutil.which("clang") is None:
            pytest.skip("native target requires clang")
        out_exe = tmp_path / f"{name}.exe"
        state = build(str(src), str(out_exe), "native")
        assert state in {"built", "cached"}
        cp = subprocess.run(
            [str(out_exe)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        results.append(
            RunResult(
                backend="native",
                returncode=cp.returncode,
                stdout=cp.stdout,
                stderr=cp.stderr,
            )
        )

    if "llvm" in backends:
        # For LLVM we currently treat stdout as the textual IR, which allows
        # CODEGEN-phase golden tests and IR invariants without requiring `lli`.
        out_ll = tmp_path / f"{name}.ll"
        state = build(str(src), str(out_ll), "llvm")
        assert state in {"built", "cached"}
        ir_text = out_ll.read_text()
        results.append(
            RunResult(
                backend="llvm",
                returncode=0,
                stdout=ir_text,
                stderr="",
            )
        )

    return results


def assert_same_stdout_and_exit(
    results: Iterable[RunResult],
    expected_stdout: str,
    expected_returncode: int = 0,
) -> None:
    """
    Assert that all backends produced the expected stdout and return code.
    """
    for rr in results:
        assert rr.returncode == expected_returncode, (
            f"backend {rr.backend} returned {rr.returncode}, "
            f"expected {expected_returncode}"
        )
        assert rr.stdout == expected_stdout, (
            f"backend {rr.backend} stdout mismatch:\n"
            f"got: {rr.stdout!r}\nexpected: {expected_stdout!r}"
        )

