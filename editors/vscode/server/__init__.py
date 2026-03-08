"""
VS Code extension server module.

This module automatically imports from the main ASTRA project to ensure
the LSP and extension always stay in sync with the language implementation.
"""

import sys
from pathlib import Path

# Add the project root to Python path to import from main astra module
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Re-export everything from the main astra module
from astra import *  # noqa: F401,F403
