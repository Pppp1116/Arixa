"""Tests for CFG construction and optimization infrastructure.

These tests verify the correctness of the foundation components
that enable real optimizations in the ASTRA compiler.
"""

import pytest
from typing import List, Any

from astra.ast import *
from astra.optimizer.cfg import CFGBuilder, ControlFlowGraph, BasicBlock, BlockType, build_cfg_for_function
from astra.optimizer.effects import EffectAnalyzer, EffectType, create_effect_analyzer
from astra.optimizer.expressions import ExpressionKeyManager, create_expression_key_manager
from astra.optimizer.pass_manager import PassManager, OptimizationPass, PassContext, PassResult, create_pass_manager


class TestCFGConstruction:
    """Test CFG construction from various ASTRA constructs."""
    
    def test_simple_function_cfg(self) -> None:
        """Test CFG construction for a simple function."""
        # Build AST: fn test() { let x = 1; return x; }
        body = [
            LetStmt(name="x", expr=Literal(value=1), mut=False),
            ReturnStmt(expr=Name(value="x"))
        ]
        
        cfg = build_cfg_for_function("test", body)
        
        # Verify CFG structure - single block with return is correct
        assert len(cfg.blocks) == 1  # Single block with return
        
        entry_block = cfg.get_block(cfg.entry_block)
        assert entry_block is not None
        assert entry_block.block_type == BlockType.ENTRY
        assert len(entry_block.statements) == 1  # let x = 1
        assert isinstance(entry_block.terminator, ReturnStmt)
        
        # Check exit block
        exit_blocks = cfg.exit_blocks
        assert len(exit_blocks) == 1
        assert cfg.entry_block in exit_blocks  # Entry block is also exit block
        
        # Validate CFG
        issues = cfg.validate()
        assert not issues, f"CFG validation failed: {issues}"
    
    def test_if_statement_cfg(self) -> None:
        """Test CFG construction for if statements."""
        # Build AST: fn test(x) { if (x > 0) { return 1; } else { return 0; } }
        body = [
            IfStmt(
                cond=Binary(op=">", left=Name(value="x"), right=Literal(value=0)),
                then_body=[ReturnStmt(expr=Literal(value=1))],
                else_body=[ReturnStmt(expr=Literal(value=0))]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        
        # Should have: entry, then, else, merge blocks
        assert len(cfg.blocks) >= 4
        
        # Verify branch structure
        entry_block = cfg.get_block(cfg.entry_block)
        assert entry_block is not None
        assert isinstance(entry_block.terminator, IfStmt)
        
        # Check successors
        successors = cfg.get_successors(cfg.entry_block)
        assert len(successors) == 2  # then and else branches
        
        # Validate CFG
        issues = cfg.validate()
        assert not issues, f"CFG validation failed: {issues}"
    
    def test_while_loop_cfg(self) -> None:
        """Test CFG construction for while loops."""
        # Build AST: fn test() { while (true) { break; } }
        body = [
            WhileStmt(
                cond=BoolLit(value=True),
                body=[BreakStmt()]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        
        # Should have: entry, loop header, loop body, loop exit blocks
        assert len(cfg.blocks) >= 4
        
        # Find loop header
        loop_headers = [b for b in cfg.blocks.values() if b.is_loop_header]
        assert len(loop_headers) == 1
        
        loop_header = loop_headers[0]
        assert isinstance(loop_header.terminator, WhileStmt)
        
        # Check back edge
        successors = cfg.get_successors(loop_header.block_id)
        assert len(successors) == 2  # loop body and loop exit
        
        # Validate CFG
        issues = cfg.validate()
        assert not issues, f"CFG validation failed: {issues}"
    
    def test_match_statement_cfg(self) -> None:
        """Test CFG construction for match statements."""
        # Build AST: fn test(x) { match x { 1 => return 1; 2 => return 2; _ => return 0; } }
        body = [
            MatchStmt(
                expr=Name(value="x"),
                arms=[
                    (LiteralPattern(value=1), [ReturnStmt(expr=Literal(value=1))]),
                    (LiteralPattern(value=2), [ReturnStmt(expr=Literal(value=2))]),
                    (WildcardPattern(), [ReturnStmt(expr=Literal(value=0))])
                ]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        
        # Should have: entry + one block per arm + merge
        assert len(cfg.blocks) >= 5
        
        # Validate CFG
        issues = cfg.validate()
        assert not issues, f"CFG validation failed: {issues}"
    
    def test_nested_control_flow_cfg(self) -> None:
        """Test CFG construction for nested control flow."""
        # Build AST: fn test(x, y) { 
        #   if (x > 0) {
        #     while (y > 0) { y = y - 1; }
        #   }
        # }
        body = [
            IfStmt(
                cond=Binary(op=">", left=Name(value="x"), right=Literal(value=0)),
                then_body=[
                    WhileStmt(
                        cond=Binary(op=">", left=Name(value="y"), right=Literal(value=0)),
                        body=[AssignStmt(target=Name(value="y"), op="-=", expr=Literal(value=1))]
                    )
                ],
                else_body=[]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        
        # Should have complex structure with nested loops
        assert len(cfg.blocks) >= 5
        
        # Validate CFG
        issues = cfg.validate()
        assert not issues, f"CFG validation failed: {issues}"
    
    def test_dominator_analysis(self) -> None:
        """Test dominator analysis on CFG."""
        # Build a simple branching CFG
        body = [
            IfStmt(
                cond=Name(value="x"),
                then_body=[ReturnStmt(expr=Literal(value=1))],
                else_body=[ReturnStmt(expr=Literal(value=0))]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        dominators = cfg.compute_dominators()
        
        # Entry block should dominate all blocks
        assert cfg.entry_block in dominators
        for block_id in cfg.blocks:
            assert cfg.entry_block in dominators[block_id], f"Entry should dominate BB{block_id}"
        
        # Test dominance relationship
        assert cfg.dominates(cfg.entry_block, cfg.entry_block)  # Self-dominance
        # Entry dominates other blocks
        for block_id in cfg.blocks:
            if block_id != cfg.entry_block:
                assert cfg.dominates(cfg.entry_block, block_id)
    
    def test_natural_loop_detection(self) -> None:
        """Test natural loop detection."""
        # Build a simple loop
        body = [
            WhileStmt(
                cond=BoolLit(value=True),
                body=[ExprStmt(expr=Literal(value=42))]
            )
        ]
        
        cfg = build_cfg_for_function("test", body)
        loops = cfg.find_natural_loops()
        
        # Should find one loop
        assert len(loops) == 1
        
        # Loop should contain header and body blocks
        loop_header, loop_body = list(loops.items())[0]
        assert loop_header in loop_body
        assert len(loop_body) >= 2  # Header + at least body block


class TestEffectAnalysis:
    """Test effect analysis for optimization safety."""
    
    def test_literal_effects(self) -> None:
        """Test effect analysis of literals."""
        analyzer = create_effect_analyzer()
        
        # Literals should be pure
        lit = Literal(value=42)
        effect = analyzer.analyze_expression(lit)
        
        assert effect.is_pure
        assert not effect.effects
        assert not effect.reads_memory
        assert not effect.writes_memory
    
    def test_name_effects(self) -> None:
        """Test effect analysis of names."""
        analyzer = create_effect_analyzer()
        
        # Local variable name
        name = Name(value="x")
        effect = analyzer.analyze_expression(name)
        
        assert effect.is_pure
        assert "x" in effect.depends_on
        assert not effect.reads_memory
        assert not effect.writes_memory
        
        # Global variable name
        analyzer.add_global_variable("_global_counter")
        global_name = Name(value="_global_counter")
        effect = analyzer.analyze_expression(global_name)
        
        assert effect.is_pure
        assert "_global_counter" in effect.depends_on
        assert "_global_counter" in effect.reads_globals
        assert effect.reads_memory
    
    def test_binary_expression_effects(self) -> None:
        """Test effect analysis of binary expressions."""
        analyzer = create_effect_analyzer()
        
        # Simple addition
        add_expr = Binary(op="+", left=Name(value="x"), right=Literal(value=1))
        effect = analyzer.analyze_expression(add_expr)
        
        assert effect.is_pure
        assert "x" in effect.depends_on
        assert EffectType.CAN_TRAP in effect.effects  # Can trap on overflow
        
        # Division (can trap on division by zero)
        div_expr = Binary(op="/", left=Name(value="x"), right=Name(value="y"))
        effect = analyzer.analyze_expression(div_expr)
        
        assert effect.is_pure
        assert EffectType.CAN_TRAP in effect.effects
        assert "x" in effect.depends_on
        assert "y" in effect.depends_on
    
    def test_function_call_effects(self) -> None:
        """Test effect analysis of function calls."""
        analyzer = create_effect_analyzer()
        
        # Pure function call
        pure_call = Call(fn=Name(value="abs"), args=[Name(value="x")])
        effect = analyzer.analyze_expression(pure_call)
        
        assert effect.is_pure
        assert effect.calls_pure_functions
        
        # Impure function call
        impure_call = Call(fn=Name(value="print"), args=[Name(value="x")])
        effect = analyzer.analyze_expression(impure_call)
        
        assert not effect.is_pure
        assert effect.calls_impure_functions
        assert EffectType.HAS_IO in effect.effects
        
        # Unknown function call (conservative)
        unknown_call = Call(fn=Name(value="unknown_func"), args=[])
        effect = analyzer.analyze_expression(unknown_call)
        
        assert not effect.is_pure
        assert effect.calls_impure_functions
        assert EffectType.CALLS_FUNCTION in effect.effects
    
    def test_memory_access_effects(self) -> None:
        """Test effect analysis of memory access."""
        analyzer = create_effect_analyzer()
        
        # Array indexing
        index_expr = IndexExpr(obj=Name(value="arr"), index=Name(value="i"))
        effect = analyzer.analyze_expression(index_expr)
        
        assert effect.is_pure
        assert effect.reads_memory
        assert EffectType.READS_MEMORY in effect.effects
        assert EffectType.CAN_TRAP in effect.effects  # Bounds checking
        
        # Field access
        field_expr = FieldExpr(obj=Name(value="obj"), field="x")
        effect = analyzer.analyze_expression(field_expr)
        
        assert effect.is_pure
        assert effect.reads_memory
        assert EffectType.READS_MEMORY in effect.effects
    
    def test_assignment_effects(self) -> None:
        """Test effect analysis of assignments."""
        analyzer = create_effect_analyzer()
        
        # Simple assignment
        assign = AssignStmt(target=Name(value="x"), op="=", expr=Literal(value=1))
        effect = analyzer.analyze_statement(assign)
        
        assert not effect.is_pure
        assert effect.writes_memory
        assert EffectType.WRITES_MEMORY in effect.effects
        assert "x" in effect.modifies
        
        # Assignment to global
        analyzer.add_global_variable("_global_counter")
        global_assign = AssignStmt(target=Name(value="_global_counter"), op="+=", expr=Literal(value=1))
        effect = analyzer.analyze_statement(global_assign)
        
        assert not effect.is_pure
        assert effect.writes_memory
        assert "_global_counter" in effect.writes_globals
    
    def test_expression_reordering_safety(self) -> None:
        """Test expression reordering safety analysis."""
        analyzer = create_effect_analyzer()
        
        # Two pure expressions - can reorder
        expr1 = Literal(value=1)
        expr2 = Literal(value=2)
        assert analyzer.can_safely_reorder(expr1, expr2)
        
        # Pure and impure - cannot reorder
        pure_expr = Literal(value=1)
        impure_expr = Call(fn=Name(value="print"), args=[Literal(value="hello")])
        assert not analyzer.can_safely_reorder(pure_expr, impure_expr)
        
        # Two reads of same memory - can reorder
        read1 = IndexExpr(obj=Name(value="arr"), index=Literal(value=0))
        read2 = IndexExpr(obj=Name(value="arr"), index=Literal(value=1))
        assert analyzer.can_safely_reorder(read1, read2)
        
        # Read and write of same memory - cannot reorder
        read_expr = IndexExpr(obj=Name(value="arr"), index=Literal(value=0))
        # Note: This would need a more complex assignment expression to test properly
        # For now, we'll test with function call effects
        write_expr = Call(fn=Name(value="array_set"), args=[Name(value="arr"), Literal(value=0), Literal(value=1)])
        assert not analyzer.can_safely_reorder(read_expr, write_expr)


class TestExpressionKeying:
    """Test expression canonicalization and keying."""
    
    def test_literal_keying(self) -> None:
        """Test literal expression keying."""
        manager = create_expression_key_manager()
        
        lit1 = Literal(value=42)
        lit2 = Literal(value=42)
        lit3 = Literal(value=43)
        
        key1 = manager.get_expression_key(lit1)
        key2 = manager.get_expression_key(lit2)
        key3 = manager.get_expression_key(lit3)
        
        # Same values should have same key
        assert key1 == key2
        # Different values should have different keys
        assert key1 != key3
    
    def test_commutative_operation_keying(self) -> None:
        """Test commutative operation canonicalization."""
        manager = create_expression_key_manager()
        
        # Commutative operations: a + b should equal b + a
        add1 = Binary(op="+", left=Name(value="a"), right=Name(value="b"))
        add2 = Binary(op="+", left=Name(value="b"), right=Name(value="a"))
        
        key1 = manager.get_expression_key(add1)
        key2 = manager.get_expression_key(add2)
        
        # Should be equal due to canonicalization
        assert key1 == key2
        
        # Non-commutative operations should not be equal
        sub1 = Binary(op="-", left=Name(value="a"), right=Name(value="b"))
        sub2 = Binary(op="-", left=Name(value="b"), right=Name(value="a"))
        
        key3 = manager.get_expression_key(sub1)
        key4 = manager.get_expression_key(sub2)
        
        assert key3 != key4
    
    def test_complex_expression_keying(self) -> None:
        """Test keying of complex expressions."""
        manager = create_expression_key_manager()
        
        # (a + b) * (c + d)
        expr1 = Binary(
            op="*",
            left=Binary(op="+", left=Name(value="a"), right=Name(value="b")),
            right=Binary(op="+", left=Name(value="c"), right=Name(value="d"))
        )
        
        # (c + d) * (a + b) - should be equal due to commutativity of *
        expr2 = Binary(
            op="*",
            left=Binary(op="+", left=Name(value="c"), right=Name(value="d")),
            right=Binary(op="+", left=Name(value="a"), right=Name(value="b"))
        )
        
        key1 = manager.get_expression_key(expr1)
        key2 = manager.get_expression_key(expr2)
        
        assert key1 == key2
    
    def test_function_call_keying(self) -> None:
        """Test function call expression keying."""
        manager = create_expression_key_manager()
        
        # f(a, b)
        call1 = Call(fn=Name(value="f"), args=[Name(value="a"), Name(value="b")])
        call2 = Call(fn=Name(value="f"), args=[Name(value="a"), Name(value="b")])
        call3 = Call(fn=Name(value="f"), args=[Name(value="b"), Name(value="a")])
        
        key1 = manager.get_expression_key(call1)
        key2 = manager.get_expression_key(call2)
        key3 = manager.get_expression_key(call3)
        
        # Same arguments should be equal
        assert key1 == key2
        # Different argument order should not be equal (function calls aren't commutative)
        assert key1 != key3
    
    def test_caching_behavior(self) -> None:
        """Test expression caching behavior."""
        manager = create_expression_key_manager()
        
        expr = Binary(op="+", left=Name(value="x"), right=Literal(value=1))
        
        # First lookup should miss
        value = manager.lookup_cached_value(expr, 0, 0)
        assert value is None
        
        # Store value
        manager.cache_expression(expr, Literal(value=42), 0, 0)
        
        # Second lookup should hit
        value = manager.lookup_cached_value(expr, 0, 1)
        assert value is not None
        assert value.value == 42
        
        # Invalidate variable dependency
        manager.invalidate_variable("x")
        
        # Lookup should miss after invalidation
        value = manager.lookup_cached_value(expr, 0, 2)
        assert value is None


class TestPassManager:
    """Test pass manager functionality."""
    
    def test_pass_manager_creation(self) -> None:
        """Test pass manager creation and configuration."""
        manager = create_pass_manager()
        
        assert manager.overflow_mode == "trap"
        assert manager.profile == "debug"
        assert not manager.release_mode
        assert manager.max_iterations == 10
    
    def test_pass_registration(self) -> None:
        """Test pass registration and management."""
        manager = create_pass_manager()
        
        # Create a dummy pass
        class DummyPass(OptimizationPass):
            def _run_impl(self, fn_decl: FnDecl, context: PassContext) -> PassResult:
                return PassResult(success=True, changed=False)
        
        dummy_pass = DummyPass("dummy")
        manager.add_pass(dummy_pass)
        
        assert len(manager.passes) == 1
        assert manager.get_pass("dummy") is dummy_pass
        
        # Test pass removal
        removed = manager.remove_pass("dummy")
        assert removed
        assert len(manager.passes) == 0
        assert manager.get_pass("dummy") is None
    
    def test_simple_function_optimization(self) -> None:
        """Test optimization of a simple function."""
        manager = create_pass_manager()
        
        # Create a dummy pass that does nothing
        class DummyPass(OptimizationPass):
            def _run_impl(self, fn_decl: FnDecl, context: PassContext) -> PassResult:
                return PassResult(success=True, changed=False)
        
        manager.add_pass(DummyPass("dummy"))
        
        # Create a simple function
        fn_decl = FnDecl(
            name="test_function",
            generics=[],
            params=[("x", "Int")],
            ret="Int",
            body=[
                LetStmt(name="y", expr=Binary(op="+", left=Name(value="x"), right=Literal(value=1)), mut=False),
                ReturnStmt(expr=Name(value="y"))
            ]
        )
        
        result = manager.optimize_function(fn_decl)
        
        assert result.success
        assert not result.changed
        assert result.execution_time_ms >= 0
    
    def test_pass_statistics(self) -> None:
        """Test pass statistics collection."""
        manager = create_pass_manager()
        manager.max_iterations = 2  # Lower max iterations for testing
        
        # Test convergence detection directly
        class TestPass(OptimizationPass):
            def __init__(self, name):
                super().__init__(name, [])
            
            def _run_impl(self, fn_decl, context):
                from astra.optimizer.pass_manager import PassResult, ChangeType
                return PassResult(success=True, changed=False)  # No changes - should converge
        
        test_pass = TestPass("test")
        manager.add_pass(test_pass)
        
        # Create and optimize a function
        fn_decl = FnDecl(
            name="test",
            generics=[],
            params=[],
            ret="Int",
            body=[ReturnStmt(expr=Literal(value=1))]
        )
        
        manager.optimize_function(fn_decl)
        
        # Check statistics
        stats = test_pass.get_statistics()
        assert stats['total_runs'] == 1  # Pass converges after 1 run
        assert stats['total_changes'] == 0  # Pass makes no changes
        assert stats['change_rate_percent'] == 0  # 0% change rate when no changes
        assert stats['total_failures'] == 0
        
        # Check manager statistics
        manager_stats = manager.get_statistics()
        assert manager_stats['functions_optimized'] == 1
        assert manager_stats['total_passes_run'] == 1


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
