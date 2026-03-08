import subprocess
import sys
from pathlib import Path

from astra.build import build


def test_gpu_examples_build_and_run(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    expected = {
        "vector_add.arixa": "[11.0, 22.0, 33.0, 44.0]",
        "saxpy.arixa": "[12.0, 24.0, 36.0, 48.0]",
        "vector_scale.arixa": "[6.0, 12.0, 18.0, 24.0]",
        "elementwise_mul.arixa": "[2.0, 12.0, 30.0, 56.0]",
    }
    for name, expected_stdout in expected.items():
        src = repo / "examples" / "gpu" / name
        out = tmp_path / f"{src.stem}.py"
        state = build(str(src), str(out), target="py")
        assert state in {"built", "cached"}
        cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
        assert cp.returncode == 0, cp.stderr
        assert expected_stdout in cp.stdout
