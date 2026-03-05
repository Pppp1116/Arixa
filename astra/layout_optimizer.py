from __future__ import annotations

import json
import re
from pathlib import Path


PROFILE_PATH = Path(".build") / "astra-profile.json"


def write_profile_template(functions: list[str], llvm_ir: str | None) -> dict[str, dict[str, int]]:
    """Write a zero-initialized layout profile template from known functions and IR CFG edges."""
    edges: dict[str, int] = {}
    all_functions: set[str] = set(functions)
    if llvm_ir:
        for fn_name, blocks in _extract_functions(llvm_ir):
            all_functions.add(fn_name)
            succ = _build_successors(blocks)
            for src, dsts in succ.items():
                for dst in dsts:
                    edges[f"{fn_name}:{src}->{dst}"] = 0
    payload = {
        "functions": {name: 0 for name in sorted(all_functions)},
        "edges": dict(sorted(edges.items())),
        "indirect_calls": {},
    }
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def load_profile() -> dict[str, dict[str, int]]:
    """Load layout profile data from disk, returning empty defaults when missing."""
    if not PROFILE_PATH.exists():
        return {"functions": {}, "edges": {}, "indirect_calls": {}}
    data = json.loads(PROFILE_PATH.read_text())
    return {
        "functions": {str(k): int(v) for k, v in data.get("functions", {}).items()},
        "edges": {str(k): int(v) for k, v in data.get("edges", {}).items()},
        "indirect_calls": {str(k): int(v) for k, v in data.get("indirect_calls", {}).items()},
    }


def optimize_llvm_layout(llvm_ir: str, profile: dict[str, dict[str, int]]) -> str:
    """Reorder functions and basic blocks in LLVM IR using profile hotness data."""
    parts: list[str] = []
    functions: list[tuple[str, list[str]]] = []
    lines = llvm_ir.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("define "):
            fn_lines = [line]
            i += 1
            while i < len(lines):
                fn_lines.append(lines[i])
                if lines[i].strip() == "}":
                    i += 1
                    break
                i += 1
            name = _function_name(fn_lines[0])
            functions.append((name, _reorder_blocks(name, fn_lines, profile.get("edges", {}))))
        else:
            parts.append(line)
            i += 1
    hotness = profile.get("functions", {})
    functions.sort(key=lambda item: hotness.get(item[0], 0), reverse=True)
    out = parts + [line for _, body in functions for line in body]
    return "\n".join(out) + "\n"


def _function_name(header: str) -> str:
    """Extract an LLVM function name from a define header (quoted or unquoted)."""
    m = re.search(r'@"([^"]+)"\(|@([A-Za-z_][\w\.]*)\(', header)
    if not m:
        return "<anon>"
    quoted = m.group(1)
    if quoted is not None:
        return quoted
    ident = m.group(2)
    return ident if ident is not None else "<anon>"



def _extract_functions(ir: str) -> list[tuple[str, dict[str, list[str]]]]:
    """Split module IR into per-function block dictionaries keyed by function name."""
    out: list[tuple[str, dict[str, list[str]]]] = []
    lines = ir.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("define "):
            header = lines[i]
            buf = [header]
            i += 1
            while i < len(lines):
                buf.append(lines[i])
                if lines[i].strip() == "}":
                    i += 1
                    break
                i += 1
            out.append((_function_name(header), _split_blocks(buf)))
        else:
            i += 1
    return out


def _split_blocks(fn_lines: list[str]) -> dict[str, list[str]]:
    """Split a function body into labeled basic-block line groups."""
    blocks: dict[str, list[str]] = {}
    current = "entry"
    blocks[current] = [fn_lines[0]]
    for line in fn_lines[1:]:
        m = re.match(r"^\s*([A-Za-z0-9_.-]+):(?:\s.*)?$", line)
        if m:
            current = m.group(1)
            blocks.setdefault(current, []).append(line)
            continue
        blocks.setdefault(current, []).append(line)
    return blocks


def _build_successors(blocks: dict[str, list[str]]) -> dict[str, list[str]]:
    """Build a simple successor map by scanning terminator labels in each block."""
    succ: dict[str, list[str]] = {k: [] for k in blocks.keys()}
    for name, lines in blocks.items():
        tail = " ".join(lines[-2:])
        labels = re.findall(r"label\s+%([A-Za-z0-9_.-]+)", tail)
        succ[name] = labels
    return succ


def _reorder_blocks(fn_name: str, fn_lines: list[str], edge_weights: dict[str, int]) -> list[str]:
    """Reorder blocks to bias fallthrough along the hottest discovered path."""
    blocks = _split_blocks(fn_lines)
    if len(blocks) <= 2:
        return fn_lines
    successors = _build_successors(blocks)
    names = list(blocks.keys())
    if names and names[0] == "entry":
        start = "entry"
    else:
        start = max(names, key=lambda n: _block_weight(fn_name, n, edge_weights))
    order: list[str] = []
    seen: set[str] = set()
    current = start
    while current and current not in seen:
        order.append(current)
        seen.add(current)
        next_nodes = [n for n in successors.get(current, []) if n not in seen]
        if not next_nodes:
            break
        current = max(next_nodes, key=lambda n: edge_weights.get(f"{fn_name}:{current}->{n}", 0))
    for name in names:
        if name not in seen:
            order.append(name)
    out: list[str] = []
    for name in order:
        out.extend(blocks[name])
    return out


def _block_weight(fn_name: str, block: str, edge_weights: dict[str, int]) -> int:
    """Compute aggregate incoming/outgoing edge weight for a block."""
    total = 0
    for k, w in edge_weights.items():
        if not k.startswith(f"{fn_name}:"):
            continue
        edge_part = k.split(":", 1)[1]
        if "->" not in edge_part:
            continue
        src, dst = edge_part.split("->", 1)
        if src == block or dst == block:
            total += int(w)
    return total

