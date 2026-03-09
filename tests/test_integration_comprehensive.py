"""Comprehensive integration tests for the current ASTRA toolchain."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from astra.build import build
from astra.codegen import to_python
from astra.error_reporting import enhance_error_message
from astra.lexer import lex
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def test_full_pipeline_simple_program() -> None:
    src = "fn main() Int{ return 42; }"
    toks = lex(src)
    assert toks and toks[-1].kind == "EOF"
    prog = parse(src)
    analyzed = analyze(prog)
    py = to_python(analyzed)
    assert "def main():" in py
    assert "return 42" in py


def test_full_pipeline_with_control_flow_and_match() -> None:
    src = """
fn main() Int{
  mut x = 0;
  while x < 3 { x += 1; }
  match x {
    3 => { return 1; },
    _ => { return 0; }
  }
  return 0;
}
"""
    analyzed = analyze(parse(src))
    py = to_python(analyzed)
    assert "while" in py
    assert "__match_value" in py


def test_parser_error_can_be_enhanced() -> None:
    src = "fn main() Int{ x = 1 return 0; }"
    with pytest.raises(ParseError) as exc:
        parse(src)
    enhanced = enhance_error_message(str(exc.value), "syntax_error", "bad.arixa", 1, 21, src)
    assert "syntax_error" in enhanced
    assert "bad.arixa:1:21" in enhanced


def test_semantic_error_can_be_enhanced() -> None:
    src = 'fn main() Int{ return "x"; }'
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    enhanced = enhance_error_message(str(exc.value), "type_mismatch", "bad.arixa", 1, 19, src)
    assert "type_mismatch" in enhanced
    assert "bad.arixa:1:19" in enhanced


def test_build_python_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "p.arixa"
    out = tmp_path / "p.py"
    src.write_text("fn main() Int{ return 9; }")
    assert build(str(src), str(out), target="py") in {"built", "cached"}
    run = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 9


@pytest.mark.skipif(shutil.which("clang") is None, reason="native target requires clang")
def test_build_native_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "n.arixa"
    out = tmp_path / "n.exe"
    src.write_text("fn main() Int{ return 13; }")
    assert build(str(src), str(out), target="native") in {"built", "cached"}
    run = subprocess.run([str(out)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 13


def test_cli_check_integration(tmp_path: Path) -> None:
    src = tmp_path / "ok.arixa"
    src.write_text("fn main() Int{ return 0; }")
    proc = subprocess.run(
        [sys.executable, "-m", "astra.cli", "check", str(src)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0


def test_pipeline_perf_smoke() -> None:
    lines = ["fn main() Int{"]
    for i in range(300):
        lines.append(f"  x{i} = {i};")
    lines.append("  return 0;")
    lines.append("}")
    src = "\n".join(lines)

    start = time.time()
    analyze(parse(src))
    elapsed = time.time() - start
    assert elapsed < 5.0
