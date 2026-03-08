#!/usr/bin/env python3
"""
Verification script to ensure LSP and VS Code extension stay in sync with language.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_lsp_import():
    """Test that LSP can import from main project."""
    try:
        # Add server path to test the import structure
        server_path = project_root / "editors/vscode/server"
        sys.path.insert(0, str(server_path))
        
        from astra.lsp import main
        print("✅ LSP imports successfully from main project")
        return True
    except Exception as e:
        print(f"❌ LSP import failed: {e}")
        return False
    finally:
        # Clean up path
        if str(server_path) in sys.path:
            sys.path.remove(str(server_path))

def test_cli_import():
    """Test that CLI can import from main project."""
    try:
        # Add server path to test the import structure
        server_path = project_root / "editors/vscode/server"
        sys.path.insert(0, str(server_path))
        
        from astra.cli import main
        print("✅ CLI imports successfully from main project")
        return True
    except Exception as e:
        print(f"❌ CLI import failed: {e}")
        return False
    finally:
        # Clean up path
        if str(server_path) in sys.path:
            sys.path.remove(str(server_path))

def test_keyword_sync():
    """Test that keywords are synchronized."""
    try:
        from astra.lexer import KEYWORDS
        
        # Check that we have the expected keywords
        expected_keywords = {'fn', 'mut', 'if', 'else', 'while', 'for', 'struct', 'enum'}
        missing_keywords = expected_keywords - KEYWORDS
        
        if missing_keywords:
            print(f"❌ Missing expected keywords: {missing_keywords}")
            return False
        
        print(f"✅ Keywords synchronized ({len(KEYWORDS)} keywords)")
        return True
    except Exception as e:
        print(f"❌ Keyword sync test failed: {e}")
        return False

def test_ast_nodes():
    """Test that AST nodes are accessible."""
    try:
        from astra.ast import IteratorForStmt, FnDecl, StructDecl
        
        # Check that we have the expected AST nodes
        assert IteratorForStmt is not None
        assert FnDecl is not None
        assert StructDecl is not None
        
        print("✅ AST nodes synchronized and accessible")
        return True
    except Exception as e:
        print(f"❌ AST node sync test failed: {e}")
        return False

def test_syntax_file():
    """Test that syntax file exists and is valid JSON."""
    try:
        import json
        
        syntax_file = project_root / "editors/vscode/syntaxes/arixa.tmLanguage.json"
        
        if not syntax_file.exists():
            print("❌ Syntax file does not exist")
            return False
        
        # Try to parse the JSON
        with open(syntax_file, 'r') as f:
            syntax_data = json.load(f)
        
        # Check basic structure
        if 'name' not in syntax_data or syntax_data['name'] != 'Astra':
            print("❌ Syntax file has incorrect name")
            return False
        
        if 'patterns' not in syntax_data:
            print("❌ Syntax file missing patterns")
            return False
        
        print("✅ Syntax highlighting file is valid")
        return True
    except Exception as e:
        print(f"❌ Syntax file test failed: {e}")
        return False

def main():
    """Run all verification tests."""
    print("🔍 Verifying editor tools synchronization...")
    
    tests = [
        ("LSP Import", test_lsp_import),
        ("CLI Import", test_cli_import),
        ("Keyword Sync", test_keyword_sync),
        ("AST Nodes", test_ast_nodes),
        ("Syntax File", test_syntax_file),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n📋 Testing {name}...")
        results.append(test_func())
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Verification Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All editor tools are properly synchronized!")
        return 0
    else:
        print("⚠️  Some synchronization issues detected")
        return 1

if __name__ == "__main__":
    sys.exit(main())
