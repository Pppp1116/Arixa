from pathlib import Path
from astra.build import build


def test_build_py(tmp_path: Path):
    src = tmp_path / 'a.astra'
    src.write_text('fn main() -> Int { print("ok"); return 0; }')
    out = tmp_path / 'a.py'
    st = build(str(src), str(out), 'py')
    assert st in {'built','cached'}
    assert out.exists()
