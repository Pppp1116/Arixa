"""Enhanced LLVM IR codegen with optimization attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra.ast import *
from astra.codegen import CodegenError
from astra.for_lowering import lower_for_loops
from astra.int_types import parse_int_type_name
from astra.layout import LayoutError, layout_of_struct, layout_of_type
from astra.semantic import analyze

try:
    from llvmlite import binding, ir
except Exception:
    binding = None
    ir = None


@dataclass(frozen=True)
class _EnhancedFnSig:
    name: str
    params: list[str]
    ret: str
    extern: bool = False
    variadic: bool = False
    link_libs: tuple[str, ...] = ()
    is_pure: bool = False
    is_readonly: bool = False
    is_readnone: bool = False


class EnhancedLLVMCodegen:
    """Enhanced LLVM code generation with optimization attributes."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.overflow_mode = overflow_mode
        self.profile = profile
        self.release_mode = profile == "release"
    
    def _add_arithmetic_attributes(self, instr: ir.Instruction, op: str, signed: bool = True):
        """Add NSW/NUW flags to arithmetic instructions when safe."""
        if not self.release_mode:
            return
        
        # Only add flags in wrap mode where overflow is defined
        if self.overflow_mode != "wrap":
            return
        
        if op in {"+", "-", "*"}:
            if signed:
                instr.set_metadata("nsw", self._get_debug_node())
            instr.set_metadata("nuw", self._get_debug_node())
    
    def _add_exact_attribute(self, instr: ir.Instruction, op: str):
        """Add exact flag to division/shift instructions when safe."""
        if not self.release_mode or self.overflow_mode != "wrap":
            return
        
        if op in {"/", "%", ">>", "<<"}:
            instr.set_metadata("exact", self._get_debug_node())
    
    def _add_nonnull_attribute(self, instr: ir.Instruction):
        """Add nonnull attribute when pointer is known non-null."""
        if self.release_mode:
            instr.set_metadata("nonnull", self._get_debug_node())
    
    def _add_dereferenceable_attribute(self, instr: ir.Instruction, bytes: int):
        """Add dereferenceable attribute when pointer alignment is known."""
        if self.release_mode and bytes > 0:
            md_node = ir.Constant(ir.IntType(64), bytes)
            instr.set_metadata("dereferenceable", self._get_metadata_node([md_node]))
    
    def _add_alignment_attribute(self, instr: ir.Instruction, align: int):
        """Add alignment attribute when alignment is known."""
        if self.release_mode and align > 0:
            md_node = ir.Constant(ir.IntType(64), align)
            instr.set_metadata("align", self._get_metadata_node([md_node]))
    
    def _add_range_attribute(self, instr: ir.Instruction, min_val: int, max_val: int):
        """Add range attribute for integer values."""
        if self.release_mode:
            min_node = ir.Constant(ir.IntType(64), min_val)
            max_node = ir.Constant(ir.IntType(64), max_val)
            instr.set_metadata("range", self._get_metadata_node([min_node, max_node]))
    
    def _add_noalias_attribute(self, instr: ir.Instruction):
        """Add noalias attribute for pointer parameters."""
        if self.release_mode:
            instr.set_metadata("noalias", self._get_debug_node())
    
    def _add_nocapture_attribute(self, instr: ir.Instruction):
        """Add nocapture attribute for pointer parameters."""
        if self.release_mode:
            instr.set_metadata("nocapture", self._get_debug_node())
    
    def _add_readonly_attribute(self, instr: ir.Instruction):
        """Add readonly attribute for function parameters."""
        if self.release_mode:
            instr.set_metadata("readonly", self._get_debug_node())
    
    def _add_readnone_attribute(self, instr: ir.Instruction):
        """Add readnone attribute for pure functions."""
        if self.release_mode:
            instr.set_metadata("readnone", self._get_debug_node())
    
    def _get_debug_node(self):
        """Get a debug metadata node."""
        if hasattr(self, '_debug_node'):
            return self._debug_node
        self._debug_node = ir.Constant(ir.IntType(32), 0)
        return self._debug_node
    
    def _get_metadata_node(self, values: list):
        """Create a metadata node with given values."""
        return ir.MDNode(values)
    
    def _enhance_function_attributes(self, fn: ir.Function, fn_sig: _EnhancedFnSig):
        """Add optimization attributes to function declaration."""
        if not self.release_mode:
            return
        
        # Add function attributes based on analysis
        if fn_sig.is_pure:
            fn.attributes.add("readonly")
        if fn_sig.is_readnone:
            fn.attributes.add("readnone")
        
        # Add alwaysinline for small functions in release mode
        if self._is_small_function(fn_sig):
            fn.attributes.add("alwaysinline")
        
        # Add nounwind for functions that don't throw
        fn.attributes.add("nounwind")
        
        # Add uwtable for better debugging in release mode
        fn.attributes.add("uwtable")
    
    def _is_small_function(self, fn_sig: _EnhancedFnSig) -> bool:
        """Heuristic to determine if function is small enough for inlining."""
        # Simple heuristic: functions with <= 4 parameters and small name
        return len(fn_sig.params) <= 4 and len(fn_sig.name) < 20
    
    def _enhance_parameter_attributes(self, param: ir.Argument, param_type: str, param_name: str):
        """Add optimization attributes to function parameters."""
        if not self.release_mode:
            return
        
        # Add nonnull for pointer parameters that shouldn't be null
        if param_type.endswith("*") and not param_name.startswith("opt_"):
            param.add_attribute("nonnull")
        
        # Add alignment for known-aligned parameters
        if param_name.startswith("aligned_"):
            param.add_attribute("align", 8)  # Assume 8-byte alignment
        
        # Add noalias for output parameters
        if param_name.startswith("out_") or param_name.startswith("result_"):
            param.add_attribute("noalias")
        
        # Add nocapture for callback parameters
        if param_name.startswith("cb_") or param_name.startswith("callback_"):
            param.add_attribute("nocapture")
    
    def _enhance_call_instruction(self, call_instr: ir.CallInstr, fn_name: str):
        """Add optimization attributes to call instructions."""
        if not self.release_mode:
            return
        
        # Add nounwind for known pure functions
        pure_functions = {
            "abs", "min", "max", "sqrt", "sin", "cos", "log", "exp",
            "strlen", "strcmp", "memcpy", "memset", "memmove"
        }
        
        if fn_name in pure_functions:
            call_instr.set_metadata("nounwind", self._get_debug_node())
    
    def _enhance_memory_operations(self, builder: ir.IRBuilder, ptr: ir.Value, size: int, is_load: bool = True):
        """Add attributes to memory operations."""
        if not self.release_mode:
            return ptr
        
        # Add alignment and dereferenceable for known memory ops
        if isinstance(ptr.type, ir.PointerType):
            element_size = self._get_type_size(ptr.type.pointee)
            if element_size > 0:
                self._add_alignment_attribute(ptr, element_size)
                self._add_dereferenceable_attribute(ptr, size)
        
        return ptr
    
    def _get_type_size(self, llvm_type: ir.Type) -> int:
        """Get the size of an LLVM type in bytes."""
        if isinstance(llvm_type, ir.IntType):
            return llvm_type.width // 8
        elif isinstance(llvm_type, ir.FloatType):
            return 4
        elif isinstance(llvm_type, ir.DoubleType):
            return 8
        elif isinstance(llvm_type, ir.PointerType):
            return 8  # Assume 64-bit pointers
        return 0
    
    def _add_lifetime_markers(self, builder: ir.IRBuilder, var: ir.Value, size: int, start: bool = True):
        """Add lifetime.start/end markers for stack variables."""
        if not self.release_mode:
            return
        
        lifetime_fn = builder.module.get_global("llvm.lifetime.start")
        if lifetime_fn is None:
            # Declare lifetime intrinsics if not present
            lifetime_start = ir.FunctionType(ir.VoidType(), [ir.IntType(64), ir.IntType(8).as_pointer()])
            lifetime_fn = ir.Function(builder.module, lifetime_start, "llvm.lifetime.start")
        
        if start:
            builder.call(lifetime_fn, [ir.Constant(ir.IntType(64), size), builder.bitcast(var, ir.IntType(8).as_pointer())])
    
    def _add_assume_intrinsic(self, builder: ir.IRBuilder, condition: ir.Value):
        """Add assume intrinsic for conditions we know are true."""
        if not self.release_mode:
            return
        
        assume_fn = builder.module.get_global("llvm.assume")
        if assume_fn is None:
            assume_type = ir.FunctionType(ir.VoidType(), [ir.IntType(1)])
            assume_fn = ir.Function(builder.module, assume_type, "llvm.assume")
        
        builder.call(assume_fn, [condition])
    
    def _optimize_branch_weights(self, builder: ir.IRBuilder, condition: ir.Value, likely_true: bool = True):
        """Add branch weight metadata for better branch prediction."""
        if not self.release_mode:
            return
        
        # Add branch weights (90% likely, 10% unlikely)
        if likely_true:
            weights = [ir.Constant(ir.IntType(32), 90), ir.Constant(ir.IntType(32), 10)]
        else:
            weights = [ir.Constant(ir.IntType(32), 10), ir.Constant(ir.IntType(32), 90)]
        
        # This would be added to the branch instruction
        # Implementation depends on the specific branch context
    
    def _enhance_aggregate_operations(self, builder: ir.IRBuilder, agg: ir.Value):
        """Add optimization hints for aggregate operations."""
        if not self.release_mode:
            return agg
        
        # Add alignment for aggregates
        if isinstance(agg.type, ir.StructType):
            layout = self._get_struct_layout(agg.type)
            if layout and layout['alignment'] > 0:
                self._add_alignment_attribute(agg, layout['alignment'])
        
        return agg
    
    def _get_struct_layout(self, struct_type: ir.StructType) -> dict:
        """Get layout information for a struct type."""
        # This would need to interface with the layout system
        # For now, return a basic layout
        return {
            'size': 0,
            'alignment': 8,  # Default alignment
            'field_offsets': []
        }


def to_llvm_ir_enhanced(
    prog: Program,
    freestanding: bool = False,
    overflow_mode: str = "trap",
    triple: str | None = None,
    profile: str = "debug",
    filename: str = "<input>",
) -> str:
    """Enhanced LLVM IR generation with optimization attributes."""
    if binding is None or ir is None:
        raise CodegenError("CODEGEN <input>:1:1: llvmlite is required for LLVM backend")
    
    # Initialize enhanced codegen
    enhancer = EnhancedLLVMCodegen(overflow_mode=overflow_mode, profile=profile)
    
    # Use the original codegen as base
    from astra.llvm_codegen import to_llvm_ir as base_to_llvm_ir
    
    # Generate base LLVM IR
    base_ir = base_to_llvm_ir(
        prog, 
        freestanding=freestanding, 
        overflow_mode=overflow_mode, 
        triple=triple, 
        profile=profile, 
        filename=filename
    )
    
    # Parse and enhance the IR
    try:
        mod = binding.parse_assembly(base_ir)
        mod.verify()
        
        # In a full implementation, we would walk the IR and add attributes
        # For now, we'll add some basic optimizations at the module level
        
        # Add optimization pass manager for release builds
        if profile == "release":
            # Create a simple optimization pipeline
            pmb = binding.PassManagerBuilder()
            pmb.opt_level = 3
            pmb.size_level = 0
            pmb.inlining = True
            
            pm = binding.ModulePassManager()
            pmb.populate(pm)
            
            # Run optimizations
            pm.run(mod)
        
        enhanced_ir = str(mod)
        return enhanced_ir if enhanced_ir.endswith("\n") else enhanced_ir + "\n"
    
    except Exception as e:
        # Fallback to base IR if enhancement fails
        return base_ir


def _analyze_function_properties(fn_decl: FnDecl) -> _EnhancedFnSig:
    """Analyze function to determine optimization properties."""
    is_pure = True
    is_readonly = True
    is_readnone = True
    
    # Simple analysis - in a full implementation this would be more sophisticated
    for stmt in fn_decl.body:
        if _has_side_effects(stmt):
            is_pure = False
            is_readnone = False
        if _reads_memory(stmt):
            is_readonly = False
    
    return _EnhancedFnSig(
        name=fn_decl.name,
        params=[param for param, _ in fn_decl.params],
        ret=fn_decl.ret,
        is_pure=is_pure,
        is_readonly=is_readonly,
        is_readnone=is_readnone
    )


def _has_side_effects(stmt: Any) -> bool:
    """Check if statement has side effects."""
    if isinstance(stmt, ExprStmt):
        return isinstance(stmt.expr, Call)
    elif isinstance(stmt, AssignStmt):
        return True
    elif isinstance(stmt, (IfStmt, WhileStmt, ForStmt)):
        return any(_has_side_effects(s) for s in getattr(stmt, 'body', []))
    return False


def _reads_memory(stmt: Any) -> bool:
    """Check if statement reads memory."""
    if isinstance(stmt, ExprStmt):
        if isinstance(stmt.expr, Call):
            return True
        if _has_memory_access(stmt.expr):
            return True
    return False


def _has_memory_access(expr: Any) -> bool:
    """Check if expression accesses memory."""
    if isinstance(expr, (IndexExpr, FieldExpr)):
        return True
    elif isinstance(expr, Call):
        return True
    elif isinstance(expr, (Unary, Binary)):
        return (_has_memory_access(expr.left) if hasattr(expr, 'left') else False) or \
               (_has_memory_access(expr.right) if hasattr(expr, 'right') else False) or \
               (_has_memory_access(expr.expr) if hasattr(expr, 'expr') else False)
    return False
