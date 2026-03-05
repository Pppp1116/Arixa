"""Bootstrap script for launching the bundled Astra LSP server copy."""

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
