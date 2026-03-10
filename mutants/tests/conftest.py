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


def _find_import_root(start: Path) -> Path:
    for base in [start, *start.parents]:
        if (base / "astra" / "ast.py").is_file():
            return base
    return start


IMPORT_ROOT = _find_import_root(Path(__file__).resolve().parent)
if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))
_prepend_pythonpath(IMPORT_ROOT)
