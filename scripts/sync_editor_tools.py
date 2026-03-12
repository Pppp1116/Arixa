#!/usr/bin/env python3
"""
Sync script for editor tools (LSP and VS Code extension).
Run this script to automatically synchronize editor tools with language changes.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sync_language_definitions import update_lsp_server, update_syntax_file, update_ast_imports

def main():
    """Main sync function."""
    print("🔄 Synchronizing editor tools with language definitions...")
    
    success = True
    success &= update_lsp_server()
    success &= update_syntax_file() 
    success &= update_ast_imports()
    
    if success:
        print("✅ Editor tools synchronized successfully!")
        return 0
    else:
        print("❌ Some synchronization steps failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
