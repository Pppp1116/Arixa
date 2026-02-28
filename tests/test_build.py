from pathlib import Path
from astra.build import build


def test_build_py(tmp_path: Path):
    src = tmp_path / 'a.astra'
    src.write_text('fn main() -> Int { print("ok"); return 0; }')
    out = tmp_path / 'a.py'
    st = build(str(src), str(out), 'py')
    assert st in {'built','cached'}
    assert out.exists()


def test_build_emit_ir(tmp_path: Path):
    src = tmp_path / "a.astra"
    src.write_text("fn main() -> Int { let x = 1 + 2; return x; }")
    out = tmp_path / "a.py"
    ir = tmp_path / "a.ir.json"
    st = build(str(src), str(out), "py", emit_ir=str(ir))
    assert st in {"built", "cached"}
    assert ir.exists()
    assert '"name": "main"' in ir.read_text()
