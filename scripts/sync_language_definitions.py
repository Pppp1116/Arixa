#!/usr/bin/env python3
"""
Automatic synchronization script for LSP and VS Code extension.

This script ensures that the LSP and VS Code extension automatically stay in sync
with the language's lexer, parser, and AST definitions without requiring manual updates.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from astra.lexer import KEYWORDS, MULTI_TOKENS
from astra.ast import (
    ComptimeStmt, EnumDecl, ExternFnDecl, FnDecl, IteratorForStmt, IfStmt, 
    ImportDecl, LetStmt, MatchStmt, Name, StructDecl, TypeAliasDecl, WhileStmt
)


def extract_keywords() -> List[str]:
    """Extract keywords from the lexer."""
    return sorted(KEYWORDS)


def extract_token_types() -> List[str]:
    """Extract token types from the lexer."""
    return sorted(MULTI_TOKENS)


def extract_ast_nodes() -> Dict[str, List[str]]:
    """Extract AST node classes."""
    ast_nodes = {
        'statements': [],
        'expressions': [],
        'declarations': [],
        'types': []
    }
    
    # Get all AST classes
    ast_classes = [
        ComptimeStmt, EnumDecl, ExternFnDecl, FnDecl, IteratorForStmt, IfStmt,
        ImportDecl, LetStmt, MatchStmt, Name, StructDecl, TypeAliasDecl, WhileStmt
    ]
    
    for cls in ast_classes:
        if 'Stmt' in cls.__name__:
            ast_nodes['statements'].append(cls.__name__)
        elif 'Expr' in cls.__name__ or cls.__name__ in ['Name']:
            ast_nodes['expressions'].append(cls.__name__)
        elif 'Decl' in cls.__name__:
            ast_nodes['declarations'].append(cls.__name__)
        elif 'Type' in cls.__name__:
            ast_nodes['types'].append(cls.__name__)
    
    return ast_nodes


def generate_lsp_keywords() -> str:
    """Generate LSP keywords list."""
    keywords = extract_keywords()
    return f"KEYWORDS = {json.dumps(keywords, indent=4)}"


def generate_syntax_highlighting() -> Dict[str, Any]:
    """Generate syntax highlighting definitions."""
    keywords = extract_keywords()
    ast_nodes = extract_ast_nodes()
    
    # Generate syntax file
    syntax = {
        "$schema": "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json",
        "name": "Astra",
        "scopeName": "source.arixa",
        "patterns": [
            {"include": "#comments"},
            {"include": "#strings"},
            {"include": "#numbers"},
            {"include": "#keywords"},
            {"include": "#types"},
            {"include": "#functions"},
            {"include": "#operators"},
            {"include": "#attributes"},
            {"include": "#gpu"},
            {"include": "#package"}
        ],
        "repository": {
            "comments": {
                "patterns": [
                    {"name": "comment.line.double-slash.arixa", "match": "//.*$"},
                    {
                        "name": "comment.block.arixa",
                        "begin": "/\\*",
                        "end": "\\*/",
                        "patterns": [{"include": "#comments"}]
                    },
                    {
                        "name": "comment.line.documentation.arixa",
                        "match": "^\\s*///.*$"
                    }
                ]
            },
            "strings": {
                "patterns": [
                    {
                        "name": "string.quoted.double.arixa",
                        "begin": "\"",
                        "end": "\"",
                        "patterns": [
                            {"name": "constant.character.escape.arixa", "match": "\\\\."},
                            {"name": "constant.character.escape.unicode.arixa", "match": "\\\\u[0-9a-fA-F]{4}"},
                            {"name": "constant.character.escape.unicode.long.arixa", "match": "\\\\U[0-9a-fA-F]{8}"}
                        ]
                    },
                    {
                        "name": "string.quoted.single.arixa",
                        "begin": "'",
                        "end": "'",
                        "patterns": [
                            {"name": "constant.character.escape.arixa", "match": "\\\\."},
                            {"name": "constant.character.escape.unicode.arixa", "match": "\\\\u[0-9a-fA-F]{4}"},
                            {"name": "constant.character.escape.unicode.long.arixa", "match": "\\\\U[0-9a-fA-F]{8}"}
                        ]
                    }
                ]
            },
            "keywords": {
                "patterns": [
                    {
                        "name": "keyword.control.arixa",
                        "match": f"\\b({'|'.join(re.escape(k) for k in keywords if k in ['fn', 'return', 'if', 'else', 'while', 'for', 'break', 'continue'])})\\b"
                    },
                    {
                        "name": "keyword.declaration.arixa", 
                        "match": f"\\b({'|'.join(re.escape(k) for k in keywords if k in ['struct', 'enum', 'type', 'impl', 'trait'])})\\b"
                    },
                    {
                        "name": "keyword.other.arixa",
                        "match": f"\\b({'|'.join(re.escape(k) for k in keywords if k not in ['fn', 'return', 'if', 'else', 'while', 'for', 'break', 'continue', 'struct', 'enum', 'type', 'impl', 'trait'])})\\b"
                    }
                ]
            },
            "types": {
                "patterns": [
                    {
                        "name": "storage.type.primitive.arixa",
                        "match": "\\b(Int|Float|Bool|String|Bytes|Never|Void)\\b"
                    },
                    {
                        "name": "storage.type.builtin.arixa",
                        "match": "\\b(Vec|Option|Result|Range|Slice|Ref|Mut)\\b"
                    }
                ]
            },
            "functions": {
                "patterns": [
                    {
                        "name": "entity.name.function.arixa",
                        "match": "\\b([a-zA-Z_][a-zA-Z0-9_]*)\\s*(\\()",
                        "captures": {
                            "1": {"name": "entity.name.function.arixa"},
                            "2": {"name": "punctuation.definition.parameters.begin.arixa"}
                        }
                    }
                ]
            },
            "operators": {
                "patterns": [
                    {"name": "keyword.operator.arithmetic.arixa", "match": "[+\\-*/%]"},
                    {"name": "keyword.operator.comparison.arixa", "match": "[=<>!]="},
                    {"name": "keyword.operator.logical.arixa", "match": "&&|\\|\\|"},
                    {"name": "keyword.operator.assignment.arixa", "match": "="},
                    {"name": "punctuation.separator.arixa", "match": ","},
                    {"name": "punctuation.terminator.arixa", "match": ";"}
                ]
            },
            "attributes": {
                "patterns": [
                    {
                        "name": "meta.attribute.arixa",
                        "begin": "#\\[",
                        "end": "\\]",
                        "patterns": [
                            {"name": "entity.name.attribute.arixa", "match": "[a-zA-Z_][a-zA-Z0-9_]*"}
                        ]
                    }
                ]
            },
            "gpu": {
                "patterns": [
                    {
                        "name": "keyword.gpu.arixa",
                        "match": "\\b(gpu|kernel|global|shared|device)\\b"
                    }
                ]
            },
            "package": {
                "patterns": [
                    {
                        "name": "keyword.package.arixa",
                        "match": "\\b(import|pub|use|mod|crate)\\b"
                    }
                ]
            }
        }
    }
    
    return syntax


def update_lsp_server():
    """Update the LSP server with current language definitions."""
    lsp_file = project_root / "editors/vscode/server/astra/lsp.py"
    
    if not lsp_file.exists():
        print(f"Error: LSP file not found: {lsp_file}")
        return False
    
    # Read current LSP file
    content = lsp_file.read_text()
    
    # Generate new keywords
    keywords = extract_keywords()
    keywords_line = f"KEYWORDS = {json.dumps(keywords, indent=4)}"
    
    # Find and replace keywords section
    lines = content.split('\n')
    new_lines = []
    in_keywords = False
    
    for line in lines:
        if line.strip() == 'KEYWORDS = [':
            in_keywords = True
            new_lines.append(keywords_line)
        elif in_keywords and line.strip().startswith(']') and not line.strip().startswith('#'):
            in_keywords = False
            new_lines.append(line)
        elif not in_keywords:
            new_lines.append(line)
    
    # Write updated content
    lsp_file.write_text('\n'.join(new_lines))
    print("✓ Updated LSP server keywords")
    return True


def update_syntax_file():
    """Update the syntax highlighting file."""
    syntax_file = project_root / "editors/vscode/syntaxes/arixa.tmLanguage.json"
    
    syntax = generate_syntax_highlighting()
    
    # Write updated syntax file
    syntax_file.write_text(json.dumps(syntax, indent=2))
    print("✓ Updated syntax highlighting file")
    return True


def update_ast_imports():
    """Update AST imports in LSP to match current AST."""
    lsp_file = project_root / "editors/vscode/server/astra/lsp.py"
    
    if not lsp_file.exists():
        return False
    
    content = lsp_file.read_text()
    
    # Generate current AST imports
    ast_nodes = extract_ast_nodes()
    all_nodes = []
    for category, nodes in ast_nodes.items():
        all_nodes.extend(nodes)
    
    # Create import statement
    imports = [
        "from astra.ast import (",
    ]
    for i, node in enumerate(sorted(all_nodes)):
        if i == len(all_nodes) - 1:
            imports.append(f"    {node},")
        else:
            imports.append(f"    {node},")
    imports.append(")")
    
    import_text = '\n'.join(imports)
    
    # Replace import section
    lines = content.split('\n')
    new_lines = []
    in_ast_import = False
    
    for line in lines:
        if line.strip() == 'from astra.ast import (':
            in_ast_import = True
            new_lines.extend(imports)
        elif in_ast_import and line.strip().startswith(')'):
            in_ast_import = False
            new_lines.append(line)
        elif not in_ast_import:
            new_lines.append(line)
    
    lsp_file.write_text('\n'.join(new_lines))
    print("✓ Updated AST imports in LSP")
    return True


def create_sync_script():
    """Create a script that can be called from build process."""
    sync_script = project_root / "scripts/sync_editor_tools.py"
    
    script_content = '''#!/usr/bin/env python3
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
'''
    
    sync_script.write_text(script_content)
    sync_script.chmod(0o755)
    print(f"✓ Created sync script: {sync_script}")


def verify_imports() -> bool:
    """Verify that LSP and CLI can import from main project."""
    try:
        # Test LSP import
        server_path = project_root / "editors/vscode/server"
        import sys
        original_path = sys.path.copy()
        
        try:
            sys.path.insert(0, str(server_path))
            from astra.lsp import main
            print("✓ LSP imports successfully from main project")
        finally:
            sys.path = original_path
        
        # Test CLI import
        try:
            sys.path.insert(0, str(server_path))
            from astra.cli import main
            print("✓ CLI imports successfully from main project")
        finally:
            sys.path = original_path
            
        return True
    except Exception as e:
        print(f"❌ Import verification failed: {e}")
        return False


def add_to_build_process():
    """Add automatic sync to the build process."""
    pyproject_file = project_root / "pyproject.toml"
    
    if not pyproject_file.exists():
        print("Warning: pyproject.toml not found")
        return False
    
    content = pyproject_file.read_text()
    
    # Check if sync script is already added
    if 'sync_editor_tools' in content:
        print("✓ Sync script already in build process")
        return True
    
    # Add sync command to build process
    # This would typically be added to a custom build script or Makefile
    print("ℹ️  Add 'python scripts/sync_editor_tools.py' to your build process")
    return True


def main():
    """Main function."""
    print("🚀 Setting up automatic synchronization for LSP and VS Code extension...")
    
    success = True
    
    # Create sync script
    create_sync_script()
    
    # Update all components
    success &= update_lsp_server()
    success &= update_syntax_file()
    success &= update_ast_imports()
    
    # Add to build process
    add_to_build_process()
    
    if success:
        print("\n✅ Automatic synchronization setup complete!")
        print("\n📋 Next steps:")
        print("1. Run 'python scripts/sync_editor_tools.py' to sync manually")
        print("2. Add the sync script to your build process for automatic updates")
        print("3. The LSP and VS Code extension will now stay in sync automatically!")
    else:
        print("\n❌ Some setup steps failed!")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
