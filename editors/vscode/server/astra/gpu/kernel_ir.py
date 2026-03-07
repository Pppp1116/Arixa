"""Kernel IR datamodel used by ASTRA GPU lowering and backends."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KernelParamIR:
    """Lowered kernel parameter metadata."""

    name: str
    type_name: str


@dataclass(frozen=True)
class KernelIR:
    """Lowered GPU kernel metadata consumed by runtime backends."""

    name: str
    symbol: str
    params: tuple[KernelParamIR, ...]
    ret: str
    source_file: str
    line: int
    col: int
    builtin_calls: tuple[str, ...] = ()
    statement_count: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "symbol": self.symbol,
            "params": [{"name": p.name, "type": p.type_name} for p in self.params],
            "ret": self.ret,
            "source_file": self.source_file,
            "line": self.line,
            "col": self.col,
            "builtin_calls": list(self.builtin_calls),
            "statement_count": self.statement_count,
        }


@dataclass(frozen=True)
class KernelProgramIR:
    """Lowered GPU program payload containing all kernels in a module."""

    kernels: tuple[KernelIR, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"kernels": [k.to_dict() for k in self.kernels]}
