from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from astra.build import build
from astra.formatter import fmt
from astra.parser import parse


def _normalize(node):
    if dataclasses.is_dataclass(node):
        out = {"__type__": type(node).__name__}
        for f in dataclasses.fields(node):
            if f.name in {"pos", "line", "col"}:
                continue
            out[f.name] = _normalize(getattr(node, f.name))
        return out
    if isinstance(node, list):
        return [_normalize(x) for x in node]
    if isinstance(node, tuple):
        return tuple(_normalize(x) for x in node)
    return node


@pytest.mark.parametrize(
    "src",
    [
        "fn main() -> Int { return (1 + 2) * 3; }",
        "fn main() -> Int { return 10 - (7 - 1); }",
        "fn main() -> Int { return 1 + (2 * (3 + 4)); }",
        "fn main() -> Int { return a ?? (b ?? c); }",
        "fn main() -> Int { return -(1 + 2); }",
        "fn main() -> Int { return await (a + b); }",
        'fn main() -> Int { defer print("bye"); return 0; }',
        "fn main() -> Int { comptime { let x = 1; } return 0; }",
    ],
)
def test_formatter_idempotent_and_structural_for_precedence_cases(src: str):
    first = fmt(src)
    assert "/* unsupported */" not in first
    second = fmt(first)
    assert second == first

    original = parse(src)
    reparsed = parse(first)
    assert _normalize(reparsed) == _normalize(original)


@pytest.mark.parametrize(
    ("src", "expected_rc"),
    [
        ("fn main() -> Int { return (1 + 2) * 3; }", 9),
        ("fn main() -> Int { return 10 - (7 - 1); }", 4),
        ("fn main() -> Int { return -(1 + 2); }", 253),
    ],
)
def test_formatter_preserves_runtime_meaning_py_backend(tmp_path: Path, src: str, expected_rc: int):
    src_file = tmp_path / "prog.astra"
    out_file = tmp_path / "prog.py"
    src_file.write_text(src)

    build(str(src_file), str(out_file), target="py")
    cp_original = subprocess.run([sys.executable, str(out_file)])

    src_file.write_text(fmt(src))
    build(str(src_file), str(out_file), target="py")
    cp_formatted = subprocess.run([sys.executable, str(out_file)])

    assert cp_original.returncode == expected_rc
    assert cp_formatted.returncode == expected_rc
