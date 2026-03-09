from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepend_pythonpath(path: Path) -> None:
    root = str(path)
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if root in parts:
        return
    os.environ["PYTHONPATH"] = os.pathsep.join([root, *parts]) if parts else root


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_prepend_pythonpath(REPO_ROOT)
