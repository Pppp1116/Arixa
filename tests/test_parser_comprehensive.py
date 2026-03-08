"""Comprehensive parser tests for ASTRA language.

Tests all parser functionality including:
- Expression parsing with precedence
- Statement parsing
- Declaration parsing
- Error recovery
- Edge cases and complex constructs
- Performance tests
"""

import pytest
from astra.parser import ParseError, parse
from astra.ast import *


class TestExpressionParsing:
    """Test expression parsing functionality."""
    
    def test_literal_expressions(self):
        """Test parsing of literal expressions."""
        test_cases = [
            ("42", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("3.14", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("\"hello\"", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("'a'", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("true", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("false", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
            ("none", lambda prog: isinstance(prog.items[0].body[0].expr, Literal)),
        ]
        
        for source, validator in test_cases:
            prog = parse(f"fn main() Int {{ let x = {source}; return 0; }}")
            assert validator(prog)
    
    def test_identifier_expressions(self):
        """Test parsing of identifier expressions."""
        prog = parse("fn main() Int { let x = variable; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Name)
        assert expr.value == "variable"
    
    def test_binary_expressions(self):
        """Test parsing of binary expressions."""
        prog = parse("fn main() Int { let x = 1 + 2 * 3; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Binary)
        assert expr.op == "+"
        assert isinstance(expr.right, Binary)
        assert expr.right.op == "*"
    
    def test_unary_expressions(self):
        """Test parsing of unary expressions."""
        test_cases = [
            ("-x", "-"),
            ("!x", "!"),
            ("~x", "~"),
            ("*x", "*"),
            ("&x", "&"),
        ]
        
        for source, op in test_cases:
            prog = parse(f"fn main() Int {{ let x = {source}; return 0; }}")
            expr = prog.items[0].body[0].expr
            assert isinstance(expr, Unary)
            assert expr.op == op
    
    def test_parenthesized_expressions(self):
        """Test parsing of parenthesized expressions."""
        prog = parse("fn main() Int { let x = (1 + 2) * 3; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Binary)
        assert expr.op == "*"
        assert isinstance(expr.left, Binary)
        assert expr.left.op == "+"
    
    def test_operator_precedence(self):
        """Test operator precedence parsing."""
        prog = parse("fn main() Int { let x = 1 + 2 * 3 / 4 - 5; return 0; }")
        expr = prog.items[0].body[0].expr
        
        # Should parse as: ((1 + ((2 * 3) / 4)) - 5)
        assert isinstance(expr, Binary)
        assert expr.op == "-"
        assert isinstance(expr.left, Binary)
        assert expr.left.op == "+"
        assert isinstance(expr.left.right, Binary)
        assert expr.left.right.op == "/"
        assert isinstance(expr.left.right.left, Binary)
        assert expr.left.right.left.op == "*"
    
    def test_associativity(self):
        """Test operator associativity."""
        # Left associative
        prog = parse("fn main() Int { let x = 1 - 2 - 3; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Binary)
        assert expr.op == "-"
        assert isinstance(expr.left, Binary)
        assert expr.left.op == "-"
        
        # Right associative (assignment)
        prog = parse("fn main() Int { let x = y = z = 1; return 0; }")
        # Assignment chaining should work
    
    def test_call_expressions(self):
        """Test parsing of function call expressions."""
        prog = parse("fn main() Int { let x = func(1, 2, 3); return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Call)
        assert expr.fn.value == "func"
        assert len(expr.args) == 3
    
    def test_index_expressions(self):
        """Test parsing of array indexing expressions."""
        prog = parse("fn main() Int { let x = arr[0]; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, IndexExpr)
        assert expr.obj.value == "arr"
        assert isinstance(expr.index, Literal)
    
    def test_field_expressions(self):
        """Test parsing of field access expressions."""
        prog = parse("fn main() Int { let x = obj.field; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, FieldExpr)
        assert expr.obj.value == "obj"
        assert expr.field == "field"
    
    def test_cast_expressions(self):
        """Test parsing of cast expressions."""
        prog = parse("fn main() Int { let x = value as Int; return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, CastExpr)
        assert expr.expr.value == "value"
        assert expr.target_type == "Int"


class TestStatementParsing:
    """Test statement parsing functionality."""
    
    def test_let_statements(self):
        """Test parsing of let statements."""
        prog = parse("fn main() Int { let x = 42; return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, LetStmt)
        assert stmt.name == "x"
        assert stmt.mutable == False
    
    def test_mutable_let_statements(self):
        """Test parsing of mutable let statements."""
        prog = parse("fn main() Int { let mut x = 42; return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, LetStmt)
        assert stmt.name == "x"
        assert stmt.mutable == True
    
    def test_assign_statements(self):
        """Test parsing of assignment statements."""
        prog = parse("fn main() Int { x = 42; return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, AssignStmt)
        assert stmt.target.value == "x"
        assert stmt.op == "="
    
    def test_set_statements(self):
        """Test parsing of set statements."""
        prog = parse("fn main() Int { set x = 42; return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, AssignStmt)
        assert stmt.target.value == "x"
        assert stmt.op == "="
        assert stmt.explicit_set == True
    
    def test_return_statements(self):
        """Test parsing of return statements."""
        prog = parse("fn main() Int { return 42; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, ReturnStmt)
        assert stmt.expr.value == 42
    
    def test_void_return_statements(self):
        """Test parsing of void return statements."""
        prog = parse("fn main() Void { return; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, ReturnStmt)
        assert stmt.expr is None
    
    def test_if_statements(self):
        """Test parsing of if statements."""
        prog = parse("fn main() Int { if true { return 1; } return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, IfStmt)
        assert isinstance(stmt.cond, Literal)
        assert len(stmt.then_body) == 1
        assert stmt.else_body == []
    
    def test_if_else_statements(self):
        """Test parsing of if-else statements."""
        prog = parse("fn main() Int { if true { return 1; } else { return 0; } }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, IfStmt)
        assert len(stmt.then_body) == 1
        assert len(stmt.else_body) == 1
    
    def test_while_statements(self):
        """Test parsing of while statements."""
        prog = parse("fn main() Int { while true { break; } return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, WhileStmt)
        assert isinstance(stmt.cond, Literal)
        assert len(stmt.body) == 1
    
    def test_enhanced_while_statements(self):
        """Test parsing of enhanced while statements."""
        prog = parse("fn main() Int { while mut x = 0; x < 10 { x += 1; } return x; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, EnhancedWhileStmt)
        assert stmt.var_decl.name == "x"
    
    def test_for_statements(self):
        """Test parsing of for statements."""
        prog = parse("fn main() Int { for item in collection { print(item); } return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, IteratorForStmt)
        assert stmt.ident == "item"
        assert stmt.iterable.value == "collection"
    
    def test_break_statements(self):
        """Test parsing of break statements."""
        prog = parse("fn main() Int { while true { break; } return 0; }")
        stmt = prog.items[0].body[0].body[0]
        assert isinstance(stmt, BreakStmt)
    
    def test_continue_statements(self):
        """Test parsing of continue statements."""
        prog = parse("fn main() Int { while true { continue; } return 0; }")
        stmt = prog.items[0].body[0].body[0]
        assert isinstance(stmt, ContinueStmt)
    
    def test_match_statements(self):
        """Test parsing of match statements."""
        prog = parse("fn main() Int { match x { 1 => return 1, _ => return 0 } }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, MatchStmt)
        assert len(stmt.arms) == 2
    
    def test_unsafe_statements(self):
        """Test parsing of unsafe statements."""
        prog = parse("fn main() Int { unsafe { dangerous_operation(); } return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, UnsafeStmt)
        assert len(stmt.body) == 1
    
    def test_comptime_statements(self):
        """Test parsing of comptime statements."""
        prog = parse("fn main() Int { comptime { const_val = 42; } return 0; }")
        stmt = prog.items[0].body[0]
        assert isinstance(stmt, ComptimeStmt)
        assert len(stmt.body) == 1


class TestDeclarationParsing:
    """Test declaration parsing functionality."""
    
    def test_function_declarations(self):
        """Test parsing of function declarations."""
        prog = parse("fn example() Int { return 42; }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert fn_decl.name == "example"
        assert fn_decl.return_type == "Int"
        assert len(fn_decl.params) == 0
        assert len(fn_decl.body) == 1
    
    def test_function_with_parameters(self):
        """Test parsing of function declarations with parameters."""
        prog = parse("fn example(x: Int, y: String) Bool { return true; }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert len(fn_decl.params) == 2
        assert fn_decl.params[0][1] == "Int"
        assert fn_decl.params[1][1] == "String"
    
    def test_public_function_declarations(self):
        """Test parsing of public function declarations."""
        prog = parse("pub fn example() Int { return 42; }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert fn_decl.pub == True
    
    def test_unsafe_function_declarations(self):
        """Test parsing of unsafe function declarations."""
        prog = parse("unsafe fn example() Int { return 42; }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert fn_decl.unsafe == True
    
    def test_async_function_declarations(self):
        """Test parsing of async function declarations."""
        prog = parse("async fn example() Int { return 42; }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert fn_decl.async_fn == True
    
    def test_extern_function_declarations(self):
        """Test parsing of extern function declarations."""
        prog = parse("extern fn example(x: Int) Int;")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, ExternFnDecl)
        assert fn_decl.name == "example"
        assert len(fn_decl.params) == 1
    
    def test_struct_declarations(self):
        """Test parsing of struct declarations."""
        prog = parse("struct Point { x: Int, y: Int }")
        struct_decl = prog.items[0]
        assert isinstance(struct_decl, StructDecl)
        assert struct_decl.name == "Point"
        assert len(struct_decl.fields) == 2
        assert struct_decl.fields[0][1] == "Int"
    
    def test_public_struct_declarations(self):
        """Test parsing of public struct declarations."""
        prog = parse("pub struct Point { x: Int, y: Int }")
        struct_decl = prog.items[0]
        assert isinstance(struct_decl, StructDecl)
        assert struct_decl.pub == True
    
    def test_enum_declarations(self):
        """Test parsing of enum declarations."""
        prog = parse("enum Color { Red, Green, Blue }")
        enum_decl = prog.items[0]
        assert isinstance(enum_decl, EnumDecl)
        assert enum_decl.name == "Color"
        assert len(enum_decl.variants) == 3
    
    def test_enum_with_values(self):
        """Test parsing of enum declarations with values."""
        prog = parse("enum Status { Ok = 200, Error = 400 }")
        enum_decl = prog.items[0]
        assert isinstance(enum_decl, EnumDecl)
        assert len(enum_decl.variants) == 2
    
    def test_type_alias_declarations(self):
        """Test parsing of type alias declarations."""
        prog = parse("type UserId = Int;")
        type_alias = prog.items[0]
        assert isinstance(type_alias, TypeAliasDecl)
        assert type_alias.name == "UserId"
        assert type_alias.target_type == "Int"
    
    def test_const_declarations(self):
        """Test parsing of const declarations."""
        prog = parse("const MAX_SIZE: Int = 100;")
        const_decl = prog.items[0]
        assert isinstance(const_decl, ConstDecl)
        assert const_decl.name == "MAX_SIZE"
        assert const_decl.type_annotation == "Int"
    
    def test_trait_declarations(self):
        """Test parsing of trait declarations."""
        prog = parse("trait Display { fn display(self) String; }")
        trait_decl = prog.items[0]
        assert isinstance(trait_decl, TraitDecl)
        assert trait_decl.name == "Display"
        assert len(trait_decl.methods) == 1
    
    def test_import_declarations(self):
        """Test parsing of import declarations."""
        prog = parse('import "std.collections";')
        import_decl = prog.items[0]
        assert isinstance(import_decl, ImportDecl)
        assert import_decl.module_path == "std.collections"


class TestErrorHandling:
    """Test parser error handling and recovery."""
    
    def test_missing_semicolon_error(self):
        """Test error handling for missing semicolons."""
        with pytest.raises(ParseError):
            parse("fn main() Int { let x = 42 return 0; }")
    
    def test_mismatched_brackets_error(self):
        """Test error handling for mismatched brackets."""
        with pytest.raises(ParseError):
            parse("fn main() Int { let x = [1, 2, 3; return 0; }")
    
    def test_invalid_syntax_error(self):
        """Test error handling for invalid syntax."""
        with pytest.raises(ParseError):
            parse("fn main() Int { let x = ; return 0; }")
    
    def test_unclosed_string_error(self):
        """Test error handling for unclosed strings."""
        with pytest.raises(ParseError):
            parse('fn main() Int { let x = "unclosed; return 0; }')
    
    def test_error_recovery(self):
        """Test parser error recovery."""
        # Parser should be able to recover from some errors
        # This test depends on the specific error recovery implementation
        pass


class TestComplexConstructs:
    """Test parsing of complex language constructs."""
    
    def test_nested_expressions(self):
        """Test parsing of deeply nested expressions."""
        prog = parse("fn main() Int { let x = (a + (b * (c / (d - (e + f)))); return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Binary)
    
    def test_complex_function_signatures(self):
        """Test parsing of complex function signatures."""
        prog = parse("fn complex<T>(x: T, y: List<T>) String where T: Display { }")
        fn_decl = prog.items[0]
        assert isinstance(fn_decl, FnDecl)
        assert fn_decl.name == "complex"
    
    def test_generic_structs(self):
        """Test parsing of generic struct declarations."""
        prog = parse("struct Container<T> { value: T }")
        struct_decl = prog.items[0]
        assert isinstance(struct_decl, StructDecl)
        assert struct_decl.name == "Container"
    
    def test_complex_match_expressions(self):
        """Test parsing of complex match expressions."""
        prog = parse("""
        fn main() Int {
            match value {
                Some(x) if x > 0 => x,
                Some(x) => 0,
                None => -1
            }
        }
        """)
        match_stmt = prog.items[0].body[0]
        assert isinstance(match_stmt, MatchStmt)
        assert len(match_stmt.arms) == 3
    
    def test_chained_method_calls(self):
        """Test parsing of chained method calls."""
        prog = parse("fn main() Int { let x = obj.method1().method2().method3(); return 0; }")
        expr = prog.items[0].body[0].expr
        assert isinstance(expr, Call)
    
    def test_complex_lambdas(self):
        """Test parsing of complex lambda expressions."""
        prog = parse("fn main() Int { let f = |x, y| x + y; return f(1, 2); }")
        # This test depends on lambda syntax support
        pass


class TestPerformance:
    """Test parser performance."""
    
    def test_large_file_parsing(self):
        """Test parsing of large source files."""
        # Generate a large source file
        lines = ["fn main() Int {"]
        for i in range(1000):
            lines.append(f"    let x{i} = {i};")
        lines.append("    return 0;")
        lines.append("}")
        source = "\n".join(lines)
        
        prog = parse(source)
        assert len(prog.items) == 1
        assert len(prog.items[0].body) > 1000
    
    def test_deeply_nested_structures(self):
        """Test parsing of deeply nested structures."""
        # Create deeply nested if statements
        lines = ["fn main() Int {"]
        for i in range(100):
            lines.append("    if true {")
        lines.append("        return 42;")
        for i in range(100):
            lines.append("    }")
        lines.append("}")
        source = "\n".join(lines)
        
        prog = parse(source)
        assert len(prog.items) == 1


class TestIntegration:
    """Test parser integration with other components."""
    
    def test_parser_lexer_integration(self):
        """Test parser-lexer integration."""
        # Parser should work correctly with lexer output
        source = "fn main() Int { return 42; }"
        prog = parse(source)
        assert isinstance(prog, Program)
        assert len(prog.items) == 1
    
    def test_parser_semantic_integration(self):
        """Test parser-semantic analyzer integration."""
        from astra.semantic import analyze
        
        source = "fn main() Int { return 42; }"
        prog = parse(source)
        # Semantic analyzer should be able to process parser output
        analyze(prog)


if __name__ == "__main__":
    pytest.main([__file__])
