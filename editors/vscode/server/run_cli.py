"""Bootstrap script for launching the Astra CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Use the main project directory
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Set up environment paths for the main project
os.environ.setdefault("ASTRA_STDLIB_PATH", str(ROOT / "stdlib"))
os.environ.setdefault("ASTRA_RUNTIME_C_PATH", str(ROOT / "runtime" / "llvm_runtime.c"))

from astra.cli import main


if __name__ == "__main__":
    main()
