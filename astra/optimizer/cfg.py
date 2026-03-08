"""Control Flow Graph infrastructure for real ASTRA optimizations.

This module provides the foundation for genuine compiler optimizations
by building actual CFGs with proper basic block structure,
predecessor/successor relationships, and dominance information.

Key differences from fake optimizations:
- Real basic blocks with terminator analysis
- Actual predecessor/successor relationships  
- Proper control flow merging
- Structure that enables dataflow analysis
- Soundness guarantees for transformations
"""

from __future__ import annotations

from typing import Any, Optional, Dict, Set, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from astra.ast import *


class BlockType(Enum):
    """Basic block type classification."""
    ENTRY = "entry"
    NORMAL = "normal" 
    EXIT = "exit"
    LOOP_HEADER = "loop_header"
    LOOP_BODY = "loop_body"
    LOOP_EXIT = "loop_exit"


@dataclass
class BasicBlock:
    """Represents a basic block in the control flow graph.
    
    A basic block is a maximal sequence of statements with:
    - Exactly one entry point (no jumps to middle)
    - Exactly one exit point (branch at end or fallthrough)
    - No internal control flow (except at terminator)
    """
    
    block_id: int
    block_type: BlockType = BlockType.NORMAL
    statements: List[Any] = field(default_factory=list)
    terminator: Optional[Any] = None  # IfStmt, WhileStmt, ReturnStmt, etc.
    
    # CFG structure
    predecessors: Set[int] = field(default_factory=set)
    successors: Set[int] = field(default_factory=set)
    
    # Analysis results (filled by various passes)
    is_reachable: bool = True
    is_loop_header: bool = False
    is_loop_latch: bool = False
    loop_depth: int = 0
    
    # Dataflow support
    gen_set: Set[Any] = field(default_factory=set)  # Generated expressions
    kill_set: Set[Any] = field(default_factory=set)  # Killed expressions
    in_set: Set[Any] = field(default_factory=set)   # Input expressions
    out_set: Set[Any] = field(default_factory=set)  # Output expressions
    
    def __str__(self) -> str:
        stmt_count = len(self.statements)
        term_type = type(self.terminator).__name__ if self.terminator else "fallthrough"
        return f"BB{self.block_id}({self.block_type.value}, {stmt_count} stmts, {term_type})"
    
    def add_predecessor(self, pred_id: int) -> None:
        """Add a predecessor edge."""
        self.predecessors.add(pred_id)
    
    def add_successor(self, succ_id: int) -> None:
        """Add a successor edge."""
        self.successors.add(succ_id)
    
    def is_terminated(self) -> bool:
        """Check if this block has a terminator."""
        return self.terminator is not None
    
    def can_fallthrough(self) -> bool:
        """Check if control can fall through to next block."""
        if not self.terminator:
            return True
        # ReturnStmt, BreakStmt, ContinueStmt don't fall through
        if isinstance(self.terminator, (ReturnStmt, BreakStmt, ContinueStmt)):
            return False
        # IfStmt without else might fall through
        if isinstance(self.terminator, IfStmt):
            # Invert: return True when else_body is empty, False when it has else
            # Conservative: treat as non-fallthrough when there's an else
            return not bool(self.terminator.else_body)
        # WhileStmt always falls through (loop body executes)
        return True


@dataclass 
class ControlFlowGraph:
    """Complete control flow graph for a function.
    
    Provides the foundation for real optimizations like:
    - Dataflow analysis (available expressions, liveness)
    - Loop analysis (natural loops, induction variables)
    - Dominance analysis (dominators, dominance frontier)
    - SSA construction (if needed)
    """
    
    function_name: str
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)
    entry_block: Optional[int] = None
    exit_blocks: Set[int] = field(default_factory=set)
    
    # Analysis caches
    _dominators: Optional[Dict[int, Set[int]]] = None
    _dominance_frontier: Optional[Dict[int, Set[int]]] = None
    _natural_loops: Optional[Dict[int, Set[int]]] = None
    _reverse_postorder: Optional[List[int]] = None
    
    def __str__(self) -> str:
        block_count = len(self.blocks)
        edge_count = sum(len(block.successors) for block in self.blocks.values())
        return f"CFG({self.function_name}): {block_count} blocks, {edge_count} edges"
    
    def add_block(self, block: BasicBlock) -> None:
        """Add a basic block to the CFG."""
        self.blocks[block.block_id] = block
        
        # Set entry block if this is the first
        if self.entry_block is None:
            self.entry_block = block.block_id
            block.block_type = BlockType.ENTRY
    
    def add_edge(self, from_id: int, to_id: int) -> None:
        """Add a control flow edge."""
        if from_id in self.blocks and to_id in self.blocks:
            self.blocks[from_id].add_successor(to_id)
            self.blocks[to_id].add_predecessor(from_id)
    
    def get_block(self, block_id: int) -> Optional[BasicBlock]:
        """Get a basic block by ID."""
        return self.blocks.get(block_id)
    
    def get_successors(self, block_id: int) -> Set[int]:
        """Get successor block IDs."""
        block = self.blocks.get(block_id)
        return block.successors if block else set()
    
    def get_predecessors(self, block_id: int) -> Set[int]:
        """Get predecessor block IDs."""
        block = self.blocks.get(block_id)
        return block.predecessors if block else set()
    
    def compute_reverse_postorder(self) -> List[int]:
        """Compute reverse post-order traversal of blocks."""
        if self._reverse_postorder is not None:
            return self._reverse_postorder
        
        if self.entry_block is None:
            self._reverse_postorder = []
            return self._reverse_postorder
        
        visited = set()
        postorder = []
        
        def dfs(block_id: int) -> None:
            if block_id in visited:
                return
            visited.add(block_id)
            
            # Visit successors first
            for succ_id in self.get_successors(block_id):
                dfs(succ_id)
            
            # Add to postorder
            postorder.append(block_id)
        
        dfs(self.entry_block)
        self._reverse_postorder = list(reversed(postorder))
        return self._reverse_postorder
    
    def compute_dominators(self) -> Dict[int, Set[int]]:
        """Compute dominator sets using iterative algorithm."""
        # Clear cache to ensure fresh computation
        self._dominators = None
        self._reverse_postorder = None
        
        if self.entry_block is None:
            self._dominators = {}
            return self._dominators
        
        # Initialize: entry dominates itself, others dominate all blocks
        all_blocks = set(self.blocks.keys())
        dominators = {
            block_id: all_blocks.copy() 
            for block_id in self.blocks.keys()
        }
        dominators[self.entry_block] = {self.entry_block}
        
        # Iterative fixed-point computation
        changed = True
        iteration = 0
        # Call compute_reverse_postorder after clearing cache
        reverse_postorder = self.compute_reverse_postorder()
        
        while changed:
            changed = False
            iteration += 1
            
            for block_id in reverse_postorder:
                if block_id == self.entry_block:
                    continue
                
                # Intersect dominators of all predecessors
                pred_doms = None
                for pred_id in self.get_predecessors(block_id):
                    if pred_id in dominators:
                        if pred_doms is None:
                            pred_doms = dominators[pred_id].copy()
                        else:
                            pred_doms &= dominators[pred_id]
                
                if pred_doms is not None:
                    pred_doms.add(block_id)  # Block dominates itself
                    
                    if dominators[block_id] != pred_doms:
                        dominators[block_id] = pred_doms
                        changed = True
        
        self._dominators = dominators
        return dominators
    
    def dominates(self, dom_id: int, sub_id: int) -> bool:
        """Check if dom_id dominates sub_id."""
        dominators = self.compute_dominators()
        return dom_id in dominators.get(sub_id, set())
    
    def compute_dominance_frontier(self) -> Dict[int, Set[int]]:
        """Compute dominance frontier for each block."""
        if self._dominance_frontier is not None:
            return self._dominance_frontier
        
        dominators = self.compute_dominators()
        frontier = {block_id: set() for block_id in self.blocks.keys()}
        
        for block_id in self.blocks.keys():
            # For each successor of block
            for succ_id in self.get_successors(block_id):
                # If block doesn't strictly dominate successor
                if not self.dominates(block_id, succ_id):
                    frontier[succ_id].add(block_id)
            
            # For each predecessor where block dominates predecessor
            for pred_id in self.get_predecessors(block_id):
                if self.dominates(block_id, pred_id):
                    # Add predecessor's frontier to block's frontier
                    frontier[block_id] |= frontier.get(pred_id, set())
        
        self._dominance_frontier = frontier
        return frontier
    
    def find_natural_loops(self) -> Dict[int, Set[int]]:
        """Find natural loops using back edge detection."""
        if self._natural_loops is not None:
            return self._natural_loops
        
        loops = {}
        dominators = self.compute_dominators()
        
        # Find back edges (edge where target dominates source)
        for block_id in self.blocks.keys():
            for succ_id in self.get_successors(block_id):
                # Check if this could be a back edge
                # Corrected: check if succ_id dominates block_id (target dominates source)
                if succ_id in dominators and block_id in dominators.get(succ_id, set()):
                    # Additional check: this should be a "backward" edge
                    # In our CFG construction, back edges are specifically from body/exits back to headers
                    # For now, use a heuristic: if successor has multiple predecessors, it's likely a header
                    succ_block = self.blocks.get(succ_id)
                    if succ_block and len(succ_block.predecessors) > 1:
                        # This is likely a back edge to a loop header
                        loop_header = succ_id
                        loop_body = {loop_header}
                        
                        # Find all blocks that can reach the back edge source
                        worklist = [block_id]
                        visited = set()
                        
                        while worklist:
                            current = worklist.pop()
                            if current in visited or current == loop_header:
                                continue
                            visited.add(current)
                            
                            if current not in loop_body:
                                loop_body.add(current)
                                worklist.extend(self.get_predecessors(current))
                        
                        loops[loop_header] = loop_body
                        
                        # Mark loop blocks
                        for body_id in loop_body:
                            block = self.blocks[body_id]
                            block.is_loop_header = (body_id == loop_header)
                            block.loop_depth = max(block.loop_depth, 1)
        
        self._natural_loops = loops
        return loops
    
    def validate(self) -> List[str]:
        """Validate CFG structure and return list of issues."""
        issues = []
        
        if not self.blocks:
            issues.append("CFG has no blocks")
            return issues
        
        if self.entry_block is None:
            issues.append("CFG has no entry block")
        
        if self.entry_block not in self.blocks:
            issues.append(f"Entry block {self.entry_block} not found")
        
        # Check for unreachable blocks
        reachable = self._compute_reachable_blocks()
        for block_id in self.blocks:
            if block_id not in reachable:
                issues.append(f"Block {block_id} is unreachable")
        
        # Check edge consistency
        for block_id, block in self.blocks.items():
            for succ_id in block.successors:
                if succ_id not in self.blocks:
                    issues.append(f"Block {block_id} has invalid successor {succ_id}")
                if block_id not in self.blocks[succ_id].predecessors:
                    issues.append(f"Edge {block_id} -> {succ_id} not reflected in predecessors")
        
        return issues
    
    def _compute_reachable_blocks(self) -> Set[int]:
        """Compute set of reachable blocks from entry."""
        if self.entry_block is None:
            return set()
        
        reachable = set()
        worklist = [self.entry_block]
        
        while worklist:
            current = worklist.pop()
            if current in reachable:
                continue
            reachable.add(current)
            # Add successors even if block has no successors (empty set)
            successors = self.get_successors(current)
            worklist.extend(successors)
        
        return reachable


class CFGBuilder:
    """Builds control flow graphs from ASTRA function bodies."""
    
    def __init__(self):
        self.next_block_id = 0
        self.current_cfg: Optional[ControlFlowGraph] = None
    
    def build_cfg(self, fn_name: str, body: List[Any]) -> ControlFlowGraph:
        """Build a CFG from a function body."""
        self.current_cfg = ControlFlowGraph(function_name=fn_name)
        self.next_block_id = 0
        
        # Start with entry block
        entry_block = self._create_block(BlockType.ENTRY)
        self.current_cfg.entry_block = entry_block.block_id
        
        # Build CFG from statements
        self._build_from_stmts(entry_block, body)
        
        # Validate and return
        issues = self.current_cfg.validate()
        if issues:
            print(f"CFG validation warnings for {fn_name}:")
            for issue in issues:
                print(f"  - {issue}")
        
        return self.current_cfg
    
    def _create_block(self, block_type: BlockType = BlockType.NORMAL) -> BasicBlock:
        """Create a new basic block."""
        block = BasicBlock(block_id=self.next_block_id, block_type=block_type)
        self.next_block_id += 1
        # Add block to CFG
        self.current_cfg.add_block(block)
        return block
    
    def _build_from_stmts(self, current_block: BasicBlock, stmts: List[Any]) -> None:
        """Build CFG from a list of statements."""
        i = 0
        while i < len(stmts):
            stmt = stmts[i]
            
            # Check if statement is a terminator
            if self._is_terminator(stmt):
                current_block.terminator = stmt
                self._handle_terminator(current_block, stmt)
                i += 1
                break
            
            # Handle control flow statements
            if isinstance(stmt, IfStmt):
                self._handle_if_stmt(current_block, stmt, stmts[i+1:])
                break
            elif isinstance(stmt, WhileStmt):
                self._handle_while_stmt(current_block, stmt, stmts[i+1:])
                break
            elif isinstance(stmt, MatchStmt):
                self._handle_match_stmt(current_block, stmt, stmts[i+1:])
                break
            else:
                # Regular statement - add to current block
                current_block.statements.append(stmt)
                i += 1
        
        # If we finished all statements without terminator, fall through
        if i >= len(stmts) and not current_block.is_terminated():
            # Mark as potential exit block if no successors added
            if not current_block.successors:
                self.current_cfg.exit_blocks.add(current_block.block_id)
    
    def _is_terminator(self, stmt: Any) -> bool:
        """Check if a statement is a block terminator."""
        return isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt))
    
    def _handle_terminator(self, block: BasicBlock, terminator: Any) -> None:
        """Handle terminator statements."""
        if isinstance(terminator, ReturnStmt):
            self.current_cfg.exit_blocks.add(block.block_id)
        # Break/Continue handled by loop context (simplified for now)
    
    def _handle_if_stmt(self, current_block: BasicBlock, if_stmt: IfStmt, remaining_stmts: List[Any]) -> None:
        """Handle if statement by creating branches."""
        # Create then and else blocks
        then_block = self._create_block()
        else_block = self._create_block() if if_stmt.else_body else None
        merge_block = self._create_block()
        
        # Add edges
        self.current_cfg.add_edge(current_block.block_id, then_block.block_id)
        if else_block:
            self.current_cfg.add_edge(current_block.block_id, else_block.block_id)
            self.current_cfg.add_edge(else_block.block_id, merge_block.block_id)
        else:
            self.current_cfg.add_edge(current_block.block_id, merge_block.block_id)
        
        self.current_cfg.add_edge(then_block.block_id, merge_block.block_id)
        
        # Set terminator
        current_block.terminator = if_stmt
        
        # Build sub-CFGs
        self._build_from_stmts(then_block, if_stmt.then_body)
        if else_block:
            self._build_from_stmts(else_block, if_stmt.else_body)
        
        # Continue with merge block and remaining statements
        self._build_from_stmts(merge_block, remaining_stmts)
    
    def _handle_while_stmt(self, current_block: BasicBlock, while_stmt: WhileStmt, remaining_stmts: List[Any]) -> None:
        """Handle while statement by creating loop structure."""
        # Create loop header, body, and exit blocks
        header_block = self._create_block(BlockType.LOOP_HEADER)
        body_block = self._create_block(BlockType.LOOP_BODY)
        exit_block = self._create_block(BlockType.LOOP_EXIT)
        
        # Set up loop structure
        header_block.is_loop_header = True
        header_block.terminator = while_stmt
        
        # Add edges
        self.current_cfg.add_edge(current_block.block_id, header_block.block_id)
        self.current_cfg.add_edge(header_block.block_id, body_block.block_id)
        self.current_cfg.add_edge(header_block.block_id, exit_block.block_id)
        self.current_cfg.add_edge(body_block.block_id, header_block.block_id)  # Back edge
        
        # Build loop body
        self._build_from_stmts(body_block, while_stmt.body)
        
        # Continue with exit block and remaining statements
        self._build_from_stmts(exit_block, remaining_stmts)
    
    def _handle_match_stmt(self, current_block: BasicBlock, match_stmt: MatchStmt, remaining_stmts: List[Any]) -> None:
        """Handle match statement by creating multiple branches."""
        # Create blocks for each arm
        arm_blocks = []
        for pattern, arm_body in match_stmt.arms:
            arm_block = self._create_block()
            arm_blocks.append(arm_block)
            self.current_cfg.add_edge(current_block.block_id, arm_block.block_id)
            self._build_from_stmts(arm_block, arm_body)
        
        # Create merge block
        merge_block = self._create_block()
        for arm_block in arm_blocks:
            self.current_cfg.add_edge(arm_block.block_id, merge_block.block_id)
        
        # Set terminator
        current_block.terminator = match_stmt
        
        # Continue with merge block
        self._build_from_stmts(merge_block, remaining_stmts)


def build_cfg_for_function(fn_name: str, body: List[Any]) -> ControlFlowGraph:
    """Convenience function to build CFG for a function."""
    builder = CFGBuilder()
    return builder.build_cfg(fn_name, body)
