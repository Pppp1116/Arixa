//! CPU feature multiversioning pass design notes.
//!
//! Active implementation is currently in the Python LLVM pipeline (`astra/llvm_codegen.py`).
//! This file mirrors the planned Rust pass location for future parity.

#[derive(Debug, Clone, Default)]
pub struct MultiversionConfig {
    pub cpu_dispatch: bool,
    pub cpu_target: String,
}

pub fn lower_multiversion_stub(ir: &str, _cfg: &MultiversionConfig) -> String {
    ir.to_string()
}
