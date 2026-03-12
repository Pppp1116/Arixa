"""Language Server Protocol implementation for Astra editor integrations."""
from __future__ import annotations
import argparse
import json
import logging
import re
import select
import subprocess
import sys
import time
from dataclasses import dataclass, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from astra.ast import (
    AssignStmt,
    Binary,
    BoolLit,
    Call,
    ComptimeStmt,
    ConstDecl,
    EnumDecl,
    ExprStmt,
    FieldExpr,
    ExternFnDecl,
    FnDecl,
    GuardedPattern,
    IteratorForStmt,
    IfStmt,
    ImportDecl,
    LetStmt,
    Literal,
    MatchStmt,
    MethodCall,
    Name,
    NilLit,
    OrPattern,
    ReturnStmt,
    StructDecl,
    TraitDecl,
    TypeAliasDecl,
    UnsafeStmt,
    WildcardPattern,
    WhileStmt,
)
from astra.check import _parse_diag_lines, run_check_source
from astra.formatter import fmt, resolve_format_config
from astra.module_resolver import ModuleResolutionError, resolve_import_path
from astra.lexer import lex
from astra.parser import ParseError, parse
from astra.semantic import BUILTIN_DOCS, BUILTIN_SIGS, GPU_API_DOCS, SemanticError, analyze

_LOG = logging.getLogger("astlsp")
KEYWORDS = [
    "fn",
    "mut",
    "if",
    "else",
    "while",
    "for",
    "match",
    "return",
    "break",
    "continue",
    "unreachable",
    "unsafe",
    "struct",
    "enum",
    "type",
    "import",
    "mut",
    "pub",
    "extern",
    "async",
    "await",
    "unsafe",
    "match",
    "none",
    "f16",
    "f80",
    "f128",
]
SNIPPETS = {
    "fn": "fn ${1:name}(${2}) ${3:Int} {\n    ${0}\n}",
    "struct": "struct ${1:Name} {\n    ${2:field} ${3:Int},\n}",
    "enum": "enum ${1:Name} {\n    ${2:Variant},\n}",
    "match": "match ${1:value} {\n    ${2:pattern} => {\n        ${0}\n    },\n}",
    "for": "for ${1:item} in ${2:iterable} {\n    ${0}\n}",
    "while": "while ${1:cond} {\n    ${0}\n}",
    "if": "if ${1:cond} {\n    ${0}\n}",
    "return": "return ${0};",
    "unreachable": "unreachable;",
    "mut": "mut ${1:name} = ${0};",
}
_NO_MSG = object()
_SEVERITY_MAP = {
    "error": 1,
    "warning": 2,
    "information": 3,
    "hint": 4,
}
@dataclass
class TextDocument:
    """Data container used by lsp.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    uri: str
    text: str
    version: int
    language_id: str
@dataclass
class AnalysisTask:
    """Data container used by lsp.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    uri: str
    version: int
    due_at: float
@dataclass
class SymbolInfo:
    """Data container used by lsp.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    kind: int
    line: int
    col: int
    detail: str
    uri: str
    doc: str = ""
def send(msg: dict[str, Any]) -> None:
    """Execute the `send` routine.
    
    Parameters:
        msg: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    raw = json.dumps(msg).encode("utf-8")
    sys.stdout.write(f"Content-Length: {len(raw)}\r\n\r\n")
    sys.stdout.write(raw.decode("utf-8"))
    sys.stdout.flush()
def _read_msg_with_timeout(timeout: float | None) -> dict[str, Any] | None | object:
    if timeout is not None:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return _NO_MSG
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\r\n", "\n", ""):
            break
        k, v = line.split(":", 1)
        headers[k.lower().strip()] = v.strip()
    n = int(headers.get("content-length", "0"))
    if n <= 0:
        return _NO_MSG
    body = sys.stdin.read(n)
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return _NO_MSG
def read_msg() -> dict[str, Any] | None:
    """Execute the `read_msg` routine.
    
    Parameters:
        none
    
    Returns:
        Value described by the function return annotation.
    """
    msg = _read_msg_with_timeout(None)
    if msg is None or msg is _NO_MSG:
        return None
    return msg
def _uri_to_filename(uri: str) -> str:
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"/{parsed.netloc}{path}"
        return path
    return uri
def _filename_to_uri(filename: str) -> str:
    if filename.startswith("file://"):
        return filename
    if filename.startswith("<") and filename.endswith(">"):
        return filename
    return Path(filename).resolve().as_uri()
def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2
def _line_start_offsets(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts
def _position_to_offset(text: str, line: int, character_utf16: int) -> int:
    starts = _line_start_offsets(text)
    if line < 0:
        return 0
    if line >= len(starts):
        return len(text)
    start = starts[line]
    end = starts[line + 1] if line + 1 < len(starts) else len(text)
    row = text[start:end]
    row = row[:-1] if row.endswith("\n") else row
    units = 0
    idx = 0
    for idx, ch in enumerate(row):
        u = _utf16_len(ch)
        if units + u > character_utf16:
            return start + idx
        units += u
    return start + len(row)
def _offset_to_position(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(offset, len(text)))
    starts = _line_start_offsets(text)
    line = 0
    for i, s in enumerate(starts):
        if s > offset:
            break
        line = i
    start = starts[line]
    row = text[start:offset]
    return line, _utf16_len(row)
def _apply_content_changes(text: str, changes: list[dict[str, Any]]) -> str:
    out = text
    for change in changes:
        if "range" not in change:
            out = change.get("text", "")
            continue
        rng = change["range"]
        start = rng["start"]
        end = rng["end"]
        s_off = _position_to_offset(out, int(start["line"]), int(start["character"]))
        e_off = _position_to_offset(out, int(end["line"]), int(end["character"]))
        if e_off < s_off:
            s_off, e_off = e_off, s_off
        out = out[:s_off] + change.get("text", "") + out[e_off:]
    return out
def _iter_ast(node: Any):
    if is_dataclass(node):
        yield node
        for field in node.__dataclass_fields__.keys():
            yield from _iter_ast(getattr(node, field))
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_ast(item)
        return
    if isinstance(node, tuple):
        for item in node:
            yield from _iter_ast(item)
def _word_at(text: str, line: int, character: int) -> str:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    row = lines[line]
    if not row:
        return ""
    pos = min(max(0, character), len(row) - 1)
    if not (row[pos].isalnum() or row[pos] == "_"):
        return ""
    s = pos
    e = pos
    while s > 0 and (row[s - 1].isalnum() or row[s - 1] == "_"):
        s -= 1
    while e + 1 < len(row) and (row[e + 1].isalnum() or row[e + 1] == "_"):
        e += 1
    return row[s : e + 1]
def _first_paragraph(doc: str) -> str:
    if not doc:
        return ""
    parts = doc.strip().split("\n\n", 1)
    return parts[0].strip()


_UNION_BINDING_PREFS = {
    "Error": "err",
    "File": "file",
    "Config": "cfg",
    "Vec<u8>": "bytes",
    "String": "text",
}
_UNRESOLVED_UNION_TYPES = {"<error>", "<unknown>", "<unresolved>", "<?>"}


def _canonical_type_name(typ: str) -> str:
    t = str(typ).strip()
    if not t:
        return t
    if t.endswith("?"):
        return f"{_canonical_type_name(t[:-1])} | none"
    if t.startswith("Option<") and t.endswith(">"):
        inner = t[len("Option<") : -1].strip()
        return f"{_canonical_type_name(inner)} | none"
    if t.startswith("&mut "):
        return f"&mut {_canonical_type_name(t[5:])}"
    if t.startswith("&"):
        return f"&{_canonical_type_name(t[1:])}"
    if t.startswith("Vec<") and t.endswith(">"):
        return f"Vec<{_canonical_type_name(t[4:-1])}>"
    return t


def _split_top_level_type(text: str, sep: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    depth_angle = 0
    depth_paren = 0
    depth_bracket = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            depth_angle += 1
        elif ch == ">" and depth_angle > 0:
            depth_angle -= 1
        elif ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        if (
            text.startswith(sep, i)
            and depth_angle == 0
            and depth_paren == 0
            and depth_bracket == 0
        ):
            out.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


def _normalized_union_members(typ: Any) -> list[str]:
    raw = str(typ).strip()
    if not raw:
        return []
    parts = _split_top_level_type(raw, "|")
    members = [p.strip() for p in parts if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for member in members:
        canon = _canonical_type_name(member)
        if canon in seen:
            continue
        seen.add(canon)
        out.append(canon)
    return out


def _is_supported_union_members(members: list[str]) -> bool:
    if len(members) <= 1:
        return False
    for member in members:
        if not member:
            return False
        if member in _UNRESOLVED_UNION_TYPES:
            return False
        low = member.lower()
        if "unsafe union" in low or "raw union" in low:
            return False
    return True


def _word_bounds(text: str, line: int, character: int) -> tuple[str, int, int]:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return "", 0, 0
    row = lines[line]
    if not row:
        return "", 0, 0
    pos = min(max(0, character), len(row) - 1)
    if not (row[pos].isalnum() or row[pos] == "_"):
        return "", 0, 0
    s = pos
    e = pos
    while s > 0 and (row[s - 1].isalnum() or row[s - 1] == "_"):
        s -= 1
    while e + 1 < len(row) and (row[e + 1].isalnum() or row[e + 1] == "_"):
        e += 1
    return row[s : e + 1], s, e + 1


def _iter_ast_with_parents(node: Any, parent: Any | None = None):
    if is_dataclass(node):
        yield node, parent
        for field in node.__dataclass_fields__.keys():
            child = getattr(node, field)
            yield from _iter_ast_with_parents(child, node)
        return
    if isinstance(node, list):
        for item in node:
            yield from _iter_ast_with_parents(item, parent)
        return
    if isinstance(node, tuple):
        for item in node:
            yield from _iter_ast_with_parents(item, parent)


def _is_expression_node(node: Any) -> bool:
    return isinstance(
        node,
        (
            Name,
            Call,
            FieldExpr,
            Binary,
            BoolLit,
            NilLit,
        ),
    )


def _is_statement_node(node: Any) -> bool:
    return isinstance(node, (LetStmt, ExprStmt, MatchStmt, IfStmt, WhileStmt, IteratorForStmt, ComptimeStmt))


def _parent_map(prog: Any) -> dict[int, Any]:
    parents: dict[int, Any] = {}
    for node, parent in _iter_ast_with_parents(prog):
        if parent is not None:
            parents[id(node)] = parent
    return parents


def _nearest_statement(node: Any, parents: dict[int, Any]) -> Any | None:
    cur = node
    while cur is not None:
        if _is_statement_node(cur):
            return cur
        cur = parents.get(id(cur))
    return None


def _line_text(text: str, line: int) -> str:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    return lines[line]


def _line_indent(text: str, line: int) -> str:
    row = _line_text(text, line)
    if not row:
        return ""
    return row[: len(row) - len(row.lstrip(" \t"))]


def _line_start_offset(text: str, line: int) -> int:
    return _position_to_offset(text, max(0, line), 0)


def _line_end_offset(text: str, line: int) -> int:
    lines = text.splitlines(keepends=True)
    if line < 0:
        return 0
    if line >= len(lines):
        return len(text)
    off = 0
    for i in range(line + 1):
        off += len(lines[i])
    return min(off, len(text))


def _offset_range(text: str, start: int, end: int) -> dict[str, dict[str, int]]:
    s_line, s_char = _offset_to_position(text, start)
    e_line, e_char = _offset_to_position(text, end)
    return {
        "start": {"line": s_line, "character": s_char},
        "end": {"line": e_line, "character": e_char},
    }


def _collect_declared_names(text: str) -> set[str]:
    out = set(KEYWORDS)
    for m in re.finditer(r"\b(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=;]+)?=", text):
        out.add(m.group(1))
    return out


def _binding_base_for_union_member(member: str) -> str:
    preferred = _UNION_BINDING_PREFS.get(member)
    if preferred:
        return preferred
    base = member.strip()
    if base.startswith("&mut "):
        base = base[5:]
    elif base.startswith("&"):
        base = base[1:]
    if base.startswith("[") and base.endswith("]"):
        return "vec"
    if "<" in base:
        base = base.split("<", 1)[0].strip()
    base = re.sub(r"[^A-Za-z0-9_]", "", base).lower()
    if not base:
        return "value"
    return base


def _unique_binding_name(base: str, used: set[str]) -> str:
    cand = base
    idx = 2
    while cand in used or cand in KEYWORDS:
        cand = f"{base}{idx}"
        idx += 1
    used.add(cand)
    return cand


def _union_member_pattern(member: str, used: set[str]) -> str:
    if member == "none":
        return "none"
    bind = _unique_binding_name(_binding_base_for_union_member(member), used)
    return f"{bind} if {bind} is {member}"


def _union_match_snippet(
    subject: str,
    members: list[str],
    base_indent: str,
    indent_unit: str,
    used: set[str],
    *,
    tab_index: int = 1,
    include_final_cursor: bool = True,
) -> tuple[str, int]:
    out: list[str] = [f"{base_indent}match {subject} {{"]
    tab = tab_index
    for member in members:
        pat = _union_member_pattern(member, used)
        out.append(f"{base_indent}{indent_unit}{pat} => {{")
        out.append(f"{base_indent}{indent_unit}{indent_unit}${{{tab}}}")
        out.append(f"{base_indent}{indent_unit}}}")
        tab += 1
    out.append(f"{base_indent}}}")
    if include_final_cursor:
        out.append(f"{base_indent}$0")
    return "\n".join(out) + "\n", tab


def _union_arms_snippet(
    members: list[str],
    base_indent: str,
    indent_unit: str,
    used: set[str],
    *,
    tab_index: int = 1,
) -> tuple[str, int]:
    out: list[str] = []
    tab = tab_index
    for member in members:
        pat = _union_member_pattern(member, used)
        out.append(f"{base_indent}{indent_unit}{pat} => {{")
        out.append(f"{base_indent}{indent_unit}{indent_unit}${{{tab}}}")
        out.append(f"{base_indent}{indent_unit}}}")
        tab += 1
    return ("\n".join(out) + ("\n" if out else "")), tab


def _literal_text(val: Any) -> str:
    if isinstance(val, str):
        return json.dumps(val)
    return str(val)


def _simple_atom_text(expr: Any) -> str | None:
    if isinstance(expr, Name):
        return expr.value
    if isinstance(expr, FieldExpr):
        obj = _simple_atom_text(expr.obj)
        if obj is None:
            return None
        return f"{obj}.{expr.field}"
    if isinstance(expr, BoolLit):
        return "true" if expr.value else "false"
    if isinstance(expr, NilLit):
        return "none"
    if hasattr(expr, "value"):
        return _literal_text(getattr(expr, "value"))
    return None


def _expr_text(expr: Any) -> str | None:
    if isinstance(expr, Call):
        fn_text = _simple_atom_text(expr.fn)
        if fn_text is None:
            return None
        arg_texts: list[str] = []
        for arg in expr.args:
            at = _simple_atom_text(arg)
            if at is None:
                return None
            arg_texts.append(at)
        return f"{fn_text}({', '.join(arg_texts)})"
    return _simple_atom_text(expr)


def _is_simple_match_subject(expr: Any) -> bool:
    if isinstance(expr, Name):
        return True
    if isinstance(expr, FieldExpr):
        return _simple_atom_text(expr) is not None
    if isinstance(expr, Call):
        return _expr_text(expr) is not None
    return False


def _subject_from_expr(expr: Any, used_names: set[str]) -> tuple[str, str] | None:
    expr_text = _expr_text(expr)
    if expr_text is None:
        return None
    if _is_simple_match_subject(expr):
        return "", expr_text
    tmp = _unique_binding_name("value", used_names)
    return f"{tmp} = {expr_text};\n", tmp


def _find_matching_brace(text: str, open_idx: int) -> int | None:
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 1
                    if i < n:
                        i += 1
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i < n:
                    if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                        i += 2
                        break
                    i += 1
                continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _match_stmt_offsets(text: str, st: MatchStmt) -> tuple[int, int, int] | None:
    start = int(getattr(st, "pos", -1))
    if start < 0 or start >= len(text):
        return None
    open_idx = text.find("{", start)
    if open_idx < 0:
        return None
    close_idx = _find_matching_brace(text, open_idx)
    if close_idx is None:
        return None
    return start, open_idx, close_idx


def _member_by_canonical(members: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for member in members:
        out[_canonical_type_name(member)] = member
    return out


def _covered_union_members_from_pattern(pat: Any, members: list[str]) -> set[str] | None:
    member_map = _member_by_canonical(members)
    if isinstance(pat, OrPattern):
        covered: set[str] = set()
        for sub in pat.patterns:
            sub_cov = _covered_union_members_from_pattern(sub, members)
            if sub_cov is None:
                return None
            covered.update(sub_cov)
        return covered
    if isinstance(pat, GuardedPattern):
        if isinstance(pat.guard, Binary) and pat.guard.op == "is":
            right = getattr(pat.guard, "right", None)
            if isinstance(right, Name):
                key = _canonical_type_name(right.value)
                if key in member_map:
                    return {member_map[key]}
        return set()
    if isinstance(pat, WildcardPattern):
        return None
    if isinstance(pat, Name):
        if pat.value == "_":
            return None
        # Unconditional name patterns are catch-all in Astra match semantics.
        return None
    if isinstance(pat, NilLit):
        if "none" in member_map:
            return {"none"}
    return set()


def _range_start(params: dict[str, Any]) -> tuple[int, int]:
    rng = params.get("range", {})
    start = rng.get("start", {})
    return int(start.get("line", 0)), int(start.get("character", 0))


def _find_union_binding_on_line(prog: Any, line: int) -> LetStmt | None:
    for node in _iter_ast(prog):
        if not isinstance(node, LetStmt):
            continue
        if int(getattr(node, "line", 0)) != line + 1:
            continue
        inferred = getattr(node.expr, "inferred_type", None)
        if not isinstance(inferred, str):
            continue
        members = _normalized_union_members(inferred)
        if _is_supported_union_members(members):
            return node
    return None


def _find_union_expr_at_position(prog: Any, text: str, line: int, character: int) -> Any | None:
    offset = _position_to_offset(text, line, character)
    word, word_start, _ = _word_bounds(text, line, character)
    line_word_off = _position_to_offset(text, line, word_start) if word else offset
    name_candidates: list[tuple[int, Any]] = []
    candidates: list[tuple[int, Any]] = []
    same_line_candidates: list[tuple[int, Any]] = []
    for node in _iter_ast(prog):
        if not _is_expression_node(node):
            continue
        inferred = getattr(node, "inferred_type", None)
        if not isinstance(inferred, str):
            continue
        members = _normalized_union_members(inferred)
        if not _is_supported_union_members(members):
            continue
        pos = int(getattr(node, "pos", -1))
        if pos < 0:
            continue
        candidates.append((pos, node))
        if int(getattr(node, "line", 0)) == line + 1:
            same_line_candidates.append((pos, node))
        if (
            word
            and isinstance(node, Name)
            and node.value == word
            and int(getattr(node, "line", 0)) == line + 1
        ):
            name_candidates.append((abs(pos - line_word_off), node))
    if name_candidates:
        name_candidates.sort(key=lambda item: item[0])
        return name_candidates[0][1]
    target = same_line_candidates or candidates
    if not target:
        return None
    before = [item for item in target if item[0] <= offset]
    if before:
        before.sort(key=lambda item: item[0], reverse=True)
        return before[0][1]
    target.sort(key=lambda item: abs(item[0] - offset))
    return target[0][1]


def _code_action_key(title: str, rng: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        title,
        str(rng.get("start", {}).get("line", "")),
        str(rng.get("start", {}).get("character", "")),
        str(rng.get("end", {}).get("line", "")),
        str(rng.get("end", {}).get("character", "")),
    )


def _indent_unit_for_uri(uri: str) -> str:
    path = Path(_uri_to_filename(uri)) if uri.startswith("file://") else None
    cfg = resolve_format_config(path) if path is not None else resolve_format_config(None)
    return " " * max(1, int(getattr(cfg, "indent_width", 4)))


def _build_create_union_match_action(
    *,
    uri: str,
    doc: TextDocument,
    prog: Any,
    line: int,
    character: int,
    title: str,
    kind: str,
    diagnostic: dict[str, Any] | None = None,
    wrap: bool = False,
) -> tuple[dict[str, Any], tuple[str, str, str, str, str]] | None:
    line = max(0, line)
    indent_unit = _indent_unit_for_uri(uri)
    used_names = _collect_declared_names(doc.text)
    word = _word_at(doc.text, line, character)
    binding_on_line = _find_union_binding_on_line(prog, line)
    parents = _parent_map(prog)
    expr = _find_union_expr_at_position(prog, doc.text, line, character)

    members: list[str] = []
    base_indent = _line_indent(doc.text, line)
    edit_start = _line_start_offset(doc.text, line)
    edit_end = edit_start
    subject = ""
    prelude = ""

    # Cursor on variable declaration line where inferred initializer is a union.
    if binding_on_line is not None and (word == binding_on_line.name or expr is None):
        inferred = getattr(binding_on_line.expr, "inferred_type", None)
        if isinstance(inferred, str):
            cand_members = _normalized_union_members(inferred)
            if _is_supported_union_members(cand_members):
                members = cand_members
                base_line = max(0, int(getattr(binding_on_line, "line", 1)) - 1)
                base_indent = _line_indent(doc.text, base_line)
                if wrap and binding_on_line.type_name is not None:
                    subject_parts = _subject_from_expr(binding_on_line.expr, used_names)
                    if subject_parts is None:
                        return None
                    prelude, subject = subject_parts
                    edit_start = _line_start_offset(doc.text, base_line)
                    edit_end = _line_end_offset(doc.text, base_line)
                else:
                    subject = binding_on_line.name
                    used_names.add(subject)
                    edit_start = _line_end_offset(doc.text, base_line)
                    edit_end = edit_start

    if not members and expr is not None:
        inferred = getattr(expr, "inferred_type", None)
        if not isinstance(inferred, str):
            return None
        cand_members = _normalized_union_members(inferred)
        if not _is_supported_union_members(cand_members):
            return None
        members = cand_members
        stmt = _nearest_statement(expr, parents)
        if isinstance(stmt, LetStmt):
            base_line = max(0, int(getattr(stmt, "line", 1)) - 1)
            base_indent = _line_indent(doc.text, base_line)
            if wrap and stmt.type_name is not None:
                subject_parts = _subject_from_expr(stmt.expr, used_names)
                if subject_parts is None:
                    return None
                prelude, subject = subject_parts
                edit_start = _line_start_offset(doc.text, base_line)
                edit_end = _line_end_offset(doc.text, base_line)
            else:
                subject = stmt.name
                used_names.add(subject)
                edit_start = _line_end_offset(doc.text, base_line)
                edit_end = edit_start
        elif isinstance(stmt, ExprStmt) and stmt.expr is expr:
            base_line = max(0, int(getattr(stmt, "line", 1)) - 1)
            base_indent = _line_indent(doc.text, base_line)
            subject_parts = _subject_from_expr(expr, used_names)
            if subject_parts is None:
                return None
            prelude, subject = subject_parts
            edit_start = _line_start_offset(doc.text, base_line)
            edit_end = _line_end_offset(doc.text, base_line)
        else:
            subject_parts = _subject_from_expr(expr, used_names)
            if subject_parts is None:
                return None
            prelude, subject = subject_parts
            edit_start = _line_end_offset(doc.text, line)
            edit_end = edit_start

    if not members or not subject:
        return None

    snippet, _ = _union_match_snippet(
        subject,
        members,
        base_indent,
        indent_unit,
        used_names,
        tab_index=1,
        include_final_cursor=True,
    )
    if prelude:
        prelude_text = "".join(f"{base_indent}{row}\n" for row in prelude.rstrip("\n").splitlines())
        new_text = prelude_text + snippet
    else:
        new_text = snippet

    rng = _offset_range(doc.text, edit_start, edit_end)
    action: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "edit": {"changes": {uri: [{"range": rng, "newText": new_text}]}},
    }
    if diagnostic is not None:
        action["diagnostics"] = [diagnostic]
        action["isPreferred"] = bool(wrap)
    return action, _code_action_key(title, rng)


def _find_match_stmt_at_offset(prog: Any, text: str, offset: int) -> tuple[MatchStmt, tuple[int, int, int]] | None:
    hits: list[tuple[int, MatchStmt, tuple[int, int, int]]] = []
    for node in _iter_ast(prog):
        if not isinstance(node, MatchStmt):
            continue
        offs = _match_stmt_offsets(text, node)
        if offs is None:
            continue
        start, _, end = offs
        if start <= offset <= end:
            hits.append((end - start, node, offs))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0])
    _, stmt, offs = hits[0]
    return stmt, offs


def _build_add_missing_union_arms_action(
    *,
    uri: str,
    doc: TextDocument,
    prog: Any,
    line: int,
    character: int,
    title: str,
    kind: str,
    diagnostic: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[str, str, str, str, str]] | None:
    offset = _position_to_offset(doc.text, line, character)
    match_hit = _find_match_stmt_at_offset(prog, doc.text, offset)
    if match_hit is None:
        return None
    stmt, offs = match_hit
    inferred = getattr(stmt.expr, "inferred_type", None)
    if not isinstance(inferred, str):
        return None
    members = _normalized_union_members(inferred)
    if not _is_supported_union_members(members):
        return None

    covered: set[str] = set()
    for pat, _ in stmt.arms:
        arm_cov = _covered_union_members_from_pattern(pat, members)
        if arm_cov is None:
            return None
        covered.update(arm_cov)
    missing = [m for m in members if m not in covered]
    if not missing:
        return None

    indent_unit = _indent_unit_for_uri(uri)
    base_line = max(0, int(getattr(stmt, "line", 1)) - 1)
    base_indent = _line_indent(doc.text, base_line)
    used_names = _collect_declared_names(doc.text)
    arm_text, _ = _union_arms_snippet(missing, base_indent, indent_unit, used_names, tab_index=1)
    if not arm_text:
        return None

    _, _, close_idx = offs
    close_line, _ = _offset_to_position(doc.text, close_idx)
    # Insert on the closing-brace line to preserve user-written arm order.
    insert_offset = _line_start_offset(doc.text, close_line)
    if close_line == base_line:
        insert_offset = close_idx
        new_text = "\n" + arm_text + base_indent
    else:
        new_text = arm_text

    rng = _offset_range(doc.text, insert_offset, insert_offset)
    action: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "edit": {"changes": {uri: [{"range": rng, "newText": new_text}]}},
    }
    if diagnostic is not None:
        action["diagnostics"] = [diagnostic]
    return action, _code_action_key(title, rng)


def _is_stable_user_facing_type(typ: str) -> bool:
    t = _canonical_type_name(typ)
    if not t:
        return False
    if t in {"<none>", "none"}:
        return False
    if t in {"Any", "Never"}:
        return False
    lower = t.lower()
    if "<error>" in lower or "<unknown>" in lower or "unresolved" in lower:
        return False
    if lower.startswith("<") and lower.endswith(">"):
        return False
    return True


def _pretty_type_text(typ: str) -> str:
    return _canonical_type_name(typ).strip()


def _tokenize_source(text: str, filename: str) -> list[Any]:
    try:
        return [tok for tok in lex(text, filename=filename) if tok.kind != "EOF"]
    except Exception:
        return []


def _binding_decl_token_info(tokens: list[Any], st: LetStmt) -> dict[str, Any] | None:
    start = int(getattr(st, "pos", -1))
    if start < 0:
        return None
    start_idx = -1
    for i, tok in enumerate(tokens):
        if tok.pos < start:
            continue
        if tok.line != st.line:
            if tok.line > st.line:
                break
            continue
        if tok.kind in {"mut", "IDENT"}:
            start_idx = i
            break
    if start_idx < 0:
        return None
    i = start_idx
    if tokens[i].kind == "mut":
        i += 1
    if i >= len(tokens) or tokens[i].kind != "IDENT":
        return None
    name_tok = tokens[i]
    if name_tok.text != st.name:
        # Fallback: find matching identifier token on declaration line.
        found = None
        for j in range(start_idx, len(tokens)):
            tok = tokens[j]
            if tok.line != st.line:
                if tok.line > st.line:
                    break
                continue
            if tok.kind == "IDENT" and tok.text == st.name:
                found = j
                break
        if found is None:
            return None
        i = found
        name_tok = tokens[i]
    colon_tok = None
    eq_tok = None
    j = i + 1
    while j < len(tokens):
        tok = tokens[j]
        if tok.line != st.line:
            if tok.line > st.line:
                break
            j += 1
            continue
        if tok.kind == ":" and colon_tok is None:
            colon_tok = tok
        if tok.kind == "=":
            eq_tok = tok
            break
        if tok.kind == ";" and eq_tok is None:
            break
        j += 1
    return {"name": name_tok, "colon": colon_tok, "eq": eq_tok}


def _find_untyped_binding_at_position(
    prog: Any,
    text: str,
    filename: str,
    line: int,
    character: int,
) -> tuple[LetStmt, dict[str, Any], str] | None:
    tokens = _tokenize_source(text, filename)
    if not tokens:
        return None
    word = _word_at(text, line, character)
    for node in _iter_ast(prog):
        if not isinstance(node, LetStmt):
            continue
        if node.type_name is not None:
            continue
        inferred = getattr(node.expr, "inferred_type", None)
        if not isinstance(inferred, str):
            continue
        typ = _pretty_type_text(inferred)
        if not _is_stable_user_facing_type(typ):
            continue
        stmt_line = max(0, int(getattr(node, "line", 1)) - 1)
        if stmt_line != line:
            continue
        if word and word != node.name:
            continue
        info = _binding_decl_token_info(tokens, node)
        if info is None or info.get("colon") is not None:
            continue
        return node, info, typ
    return None


def _build_add_explicit_type_action(
    *,
    uri: str,
    doc: TextDocument,
    prog: Any,
    line: int,
    character: int,
    title: str,
    kind: str,
    diagnostic: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[str, str, str, str, str]] | None:
    filename = _uri_to_filename(uri)
    hit = _find_untyped_binding_at_position(prog, doc.text, filename, line, character)
    if hit is None:
        return None
    _, info, typ = hit
    name_tok = info["name"]
    insert_off = int(name_tok.pos) + len(str(name_tok.text))
    rng = _offset_range(doc.text, insert_off, insert_off)
    action: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "edit": {"changes": {uri: [{"range": rng, "newText": f": {typ}"}]}},
    }
    if diagnostic is not None:
        action["diagnostics"] = [diagnostic]
    return action, _code_action_key(title, rng)


def _binding_annotation_context(
    prog: Any,
    text: str,
    filename: str,
    line: int,
    character: int,
) -> dict[str, Any] | None:
    tokens = _tokenize_source(text, filename)
    if not tokens:
        return None
    offset = _position_to_offset(text, line, character)
    for node in _iter_ast(prog):
        if not isinstance(node, LetStmt):
            continue
        info = _binding_decl_token_info(tokens, node)
        if info is None:
            continue
        colon = info.get("colon")
        if colon is None:
            continue
        eq_tok = info.get("eq")
        start_off = int(colon.pos) + 1
        end_off = int(eq_tok.pos) if eq_tok is not None else _line_end_offset(text, max(0, node.line - 1))
        if start_off <= offset <= end_off:
            inferred = getattr(node.expr, "inferred_type", None)
            inferred_text = _pretty_type_text(inferred) if isinstance(inferred, str) else ""
            typed_prefix = text[start_off:offset].strip()
            return {
                "name": node.name,
                "prefix": typed_prefix,
                "inferred_type": inferred_text if _is_stable_user_facing_type(inferred_text) else "",
            }
    # Fallback for partially-typed declarations in syntactically incomplete code.
    row = _line_text(text, line)
    if not row:
        return None
    col = min(max(0, character), len(row))
    prefix = row[:col]
    m = re.search(r"\b(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z0-9_<>&\[\], |]*)$", prefix)
    if m is None:
        return None
    return {"name": m.group(1), "prefix": m.group(2).strip(), "inferred_type": ""}


def _is_trivial_decl_for_bulk(st: LetStmt, typ: str) -> bool:
    canon = _canonical_type_name(typ)
    expr = st.expr
    if isinstance(expr, BoolLit) and canon == "Bool":
        return True
    if isinstance(expr, NilLit):
        return True
    if isinstance(expr, Literal):
        val = expr.value
        if isinstance(val, bool) and canon == "Bool":
            return True
        if isinstance(val, int) and (canon == "Int" or re.fullmatch(r"[iu]\d+", canon) is not None):
            return True
        if isinstance(val, float) and canon in {"Float", "f16", "f32", "f64", "f80", "f128"}:
            return True
        if isinstance(val, str) and canon in {"String", "str"}:
            return True
    return False


def _build_bulk_add_explicit_types_action(
    *,
    uri: str,
    doc: TextDocument,
    prog: Any,
    start_line: int,
    end_line: int,
    title: str,
    kind: str,
    non_trivial_only: bool,
) -> tuple[dict[str, Any], tuple[str, str, str, str, str]] | None:
    filename = _uri_to_filename(uri)
    tokens = _tokenize_source(doc.text, filename)
    if not tokens:
        return None
    changes: list[dict[str, Any]] = []
    for node in _iter_ast(prog):
        if not isinstance(node, LetStmt):
            continue
        if node.type_name is not None:
            continue
        ln0 = max(0, int(getattr(node, "line", 1)) - 1)
        if ln0 < start_line or ln0 > end_line:
            continue
        inferred = getattr(node.expr, "inferred_type", None)
        if not isinstance(inferred, str):
            continue
        typ = _pretty_type_text(inferred)
        if not _is_stable_user_facing_type(typ):
            continue
        if non_trivial_only and _is_trivial_decl_for_bulk(node, typ):
            continue
        info = _binding_decl_token_info(tokens, node)
        if info is None or info.get("colon") is not None:
            continue
        name_tok = info["name"]
        insert_off = int(name_tok.pos) + len(str(name_tok.text))
        rng = _offset_range(doc.text, insert_off, insert_off)
        changes.append({"range": rng, "newText": f": {typ}"})
    if not changes:
        return None
    if not non_trivial_only and len(changes) < 2:
        return None
    action: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "edit": {"changes": {uri: changes}},
    }
    key_rng = changes[0]["range"]
    return action, _code_action_key(title, key_rng)


def _balanced_text_fallback(text: str) -> str:
    """Best-effort tolerant source rewrite for completion/hover parsing."""
    out = text
    lines = out.splitlines()
    rewritten: list[str] = []
    for row in lines:
        if row.rstrip().endswith('.'):
            rewritten.append(row.rstrip() + "_placeholder")
        else:
            rewritten.append(row)
    out = "\n".join(rewritten)

    pairs = {'(': ')', '[': ']', '{': '}'}
    closers = set(pairs.values())
    stack: list[str] = []
    for ch in out:
        if ch in pairs:
            stack.append(ch)
        elif ch in closers:
            if stack and pairs[stack[-1]] == ch:
                stack.pop()

    if stack:
        suffix = ''.join(pairs[ch] for ch in reversed(stack))
        out += suffix

    return out


def _try_parse_tolerant(text: str, filename: str):
    try:
        return parse(text, filename=filename)
    except ParseError as err:
        _LOG.debug("Initial parse failed for %s; retrying tolerant parse: %s", filename, err)
    patched = _balanced_text_fallback(text)
    try:
        return parse(patched, filename=filename)
    except ParseError as err:
        _LOG.debug("Tolerant parse failed for %s; continuing without AST: %s", filename, err)
        return None

def _decl_symbols(prog: Any, uri: str) -> list[SymbolInfo]:
    out: list[SymbolInfo] = []
    for item in getattr(prog, "items", []):
        if isinstance(item, FnDecl):
            sig = ", ".join(f"{n}: {t}" for n, t in item.params)
            out.append(
                SymbolInfo(
                    name=item.name,
                    kind=12,
                    line=item.line,
                    col=item.col,
                    detail=f"fn {item.name}({sig}) {item.ret}",
                    uri=uri,
                    doc=item.doc,
                )
            )
        elif isinstance(item, StructDecl):
            out.append(SymbolInfo(name=item.name, kind=23, line=item.line, col=item.col, detail=f"struct {item.name}", uri=uri, doc=item.doc))
            for fname, _ in item.fields:
                out.append(SymbolInfo(name=fname, kind=8, line=item.line, col=item.col, detail=f"field {fname}", uri=uri, doc=""))
        elif isinstance(item, EnumDecl):
            out.append(SymbolInfo(name=item.name, kind=10, line=item.line, col=item.col, detail=f"enum {item.name}", uri=uri, doc=item.doc))
            for vname, _ in item.variants:
                out.append(SymbolInfo(name=vname, kind=22, line=item.line, col=item.col, detail=f"variant {vname}", uri=uri, doc=""))
        elif isinstance(item, TypeAliasDecl):
            out.append(SymbolInfo(name=item.name, kind=5, line=item.line, col=item.col, detail=f"type {item.name}", uri=uri, doc=""))
        elif isinstance(item, ImportDecl):
            if item.alias:
                out.append(SymbolInfo(name=item.alias, kind=2, line=item.line, col=item.col, detail="import alias", uri=uri, doc=""))
    return out
def _decl_map(prog: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sym in _decl_symbols(prog, ""):
        out[sym.name] = {
            "line": sym.line,
            "col": sym.col,
            "detail": sym.detail,
            "doc": sym.doc,
            "kind": sym.kind,
        }
    return out
def _diag_to_lsp(diag, primary_uri: str, primary_filename: str) -> dict[str, Any]:
    start_line = max(0, diag.span.line - 1)
    start_col = max(0, diag.span.col - 1)
    end_line = max(start_line, diag.span.end_line - 1)
    end_col = max(start_col + 1, diag.span.end_col - 1)
    item = {
        "range": {
            "start": {"line": start_line, "character": start_col},
            "end": {"line": end_line, "character": end_col},
        },
        "severity": _SEVERITY_MAP.get(getattr(diag, "severity", "error"), 1),
        "source": "astra",
        "code": getattr(diag, "code", "E9999"),
        "message": getattr(diag, "message", "unknown error"),
    }
    suggestions = []
    for s in getattr(diag, "suggestions", ()):
        if getattr(s, "span", None) is None:
            suggestions.append({"message": s.message, "replacement": s.replacement, "range": None})
            continue
        s_span = s.span
        suggestions.append(
            {
                "message": s.message,
                "replacement": s.replacement,
                "range": {
                    "start": {"line": max(0, s_span.line - 1), "character": max(0, s_span.col - 1)},
                    "end": {"line": max(0, s_span.end_line - 1), "character": max(0, s_span.end_col - 1)},
                },
            }
        )
    if suggestions:
        item["data"] = {"suggestions": suggestions}
    related = []
    for note in getattr(diag, "notes", ()):
        if note.span is None:
            continue
        note_uri = primary_uri if note.span.filename == primary_filename else _filename_to_uri(note.span.filename)
        related.append(
            {
                "location": {
                    "uri": note_uri,
                    "range": {
                        "start": {
                            "line": max(0, note.span.line - 1),
                            "character": max(0, note.span.col - 1),
                        },
                        "end": {
                            "line": max(0, note.span.end_line - 1),
                            "character": max(0, note.span.end_col - 1),
                        },
                    },
                },
                "message": note.message,
            }
        )
    if related:
        item["relatedInformation"] = related
    return item
def _parse_only_diagnostics(text: str, filename: str, uri: str) -> list[dict[str, Any]]:
    try:
        parse(text, filename=filename)
        return []
    except ParseError as err:
        out = []
        for d in _parse_diag_lines(str(err), default_filename=filename):
            out.append(_diag_to_lsp(d, uri, filename))
        return out
def _semantic_diagnostics(text: str, filename: str, uri: str, *, freestanding: bool, overflow: str) -> list[dict[str, Any]]:
    result = run_check_source(text, filename=filename, collect_errors=True, freestanding=freestanding, overflow=overflow)
    return [_diag_to_lsp(diag, uri, filename) for diag in result.diagnostics]
class LSPServer:
    """Data container used by lsp.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    def __init__(self, *, log: logging.Logger, debounce_ms: int = 200):
        self.log = log
        self.debounce_ms = debounce_ms
        self.docs: dict[str, TextDocument] = {}
        self.pending: dict[str, AnalysisTask] = {}
        self.symbol_index: dict[str, list[SymbolInfo]] = {}
        self.dependencies: dict[str, set[str]] = {}
        self.reverse_deps: dict[str, set[str]] = {}
        self.workspace_folders: list[Path] = []
        self.canceled: set[Any] = set()
        self.shutting_down = False
        self.exit_code = 0
        self.settings = {
            "freestanding": False,
            "overflow": "trap",
            "target": "py",
        }
        
        # Performance optimization: caching
        self._ast_cache: dict[str, tuple[Any, float]] = {}  # uri -> (ast, timestamp)
        self._symbol_cache: dict[str, tuple[list[SymbolInfo], float]] = {}  # uri -> (symbols, timestamp)
        self._completion_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}  # context_key -> (completions, timestamp)
        self._cache_ttl = 30.0  # Cache entries expire after 30 seconds
        
        # Performance monitoring
        self._performance_stats = {
            "parse_time": [],
            "analysis_time": [],
            "completion_time": [],
            "cache_hits": 0,
            "cache_misses": 0
        }
    def _publish_diagnostics(self, uri: str, version: int, diagnostics: list[dict[str, Any]]) -> None:
        doc = self.docs.get(uri)
        if doc is None or doc.version != version:
            return
        send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "version": version, "diagnostics": diagnostics},
            }
        )
    def _schedule_semantic(self, uri: str, version: int) -> None:
        self.pending[uri] = AnalysisTask(uri=uri, version=version, due_at=time.monotonic() + self.debounce_ms / 1000.0)
    def _parse_prog(self, doc: TextDocument):
        """Parse program with caching for performance."""
        filename = _uri_to_filename(doc.uri)
        
        # Check cache first
        cache_key = f"{doc.uri}:{doc.version}"
        if cache_key in self._ast_cache:
            cached_ast, timestamp = self._ast_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                self._performance_stats["cache_hits"] += 1
                return cached_ast
            else:
                del self._ast_cache[cache_key]
        
        self._performance_stats["cache_misses"] += 1
        start_time = time.perf_counter()
        
        try:
            prog = _try_parse_tolerant(doc.text, filename)
            if prog is None:
                return None

            # Cache the result
            self._ast_cache[cache_key] = (prog, time.time())
            
            # Update performance stats
            parse_time = time.perf_counter() - start_time
            self._performance_stats["parse_time"].append(parse_time)
            
            # Keep only recent stats
            if len(self._performance_stats["parse_time"]) > 100:
                self._performance_stats["parse_time"] = self._performance_stats["parse_time"][-50:]
            
            return prog
        except ParseError:
            return None
    
    def _update_symbol_index(self, uri: str) -> None:
        """Update symbol index with caching."""
        doc = self.docs.get(uri)
        if doc is None:
            self.symbol_index.pop(uri, None)
            return
        
        # Check cache first
        cache_key = f"{uri}:{doc.version}"
        if cache_key in self._symbol_cache:
            cached_symbols, timestamp = self._symbol_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                self.symbol_index[uri] = cached_symbols
                return
            else:
                del self._symbol_cache[cache_key]
        
        prog = self._parse_and_analyze(doc)
        if prog is None:
            self.symbol_index[uri] = []
            return
        
        symbols = _decl_symbols(prog, uri)
        self.symbol_index[uri] = symbols
        
        # Cache the result
        self._symbol_cache[cache_key] = (symbols, time.time())
    
    def _clean_expired_cache(self):
        """Clean expired cache entries to prevent memory leaks."""
        current_time = time.time()
        
        # Clean AST cache
        expired_keys = [
            key for key, (_, timestamp) in self._ast_cache.items()
            if current_time - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            del self._ast_cache[key]
        
        # Clean symbol cache
        expired_keys = [
            key for key, (_, timestamp) in self._symbol_cache.items()
            if current_time - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            del self._symbol_cache[key]
        
        # Clean completion cache
        expired_keys = [
            key for key, (_, timestamp) in self._completion_cache.items()
            if current_time - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            del self._completion_cache[key]
    def _update_module_graph(self, uri: str) -> None:
        doc = self.docs.get(uri)
        if doc is None:
            old = self.dependencies.pop(uri, set())
            for dep in old:
                self.reverse_deps.get(dep, set()).discard(uri)
            return
        prog = self._parse_and_analyze(doc)
        new: set[str] = set()
        if prog is not None:
            for item in getattr(prog, "items", []):
                if not isinstance(item, ImportDecl):
                    continue
                try:
                    dep = resolve_import_path(item, _uri_to_filename(uri))
                    dep_uri = dep.resolve().as_uri()
                    new.add(dep_uri)
                except ModuleResolutionError:
                    continue
        old = self.dependencies.get(uri, set())
        for dep in old - new:
            self.reverse_deps.get(dep, set()).discard(uri)
        for dep in new - old:
            self.reverse_deps.setdefault(dep, set()).add(uri)
        self.dependencies[uri] = new
    def _parse_and_analyze(self, doc: TextDocument):
        filename = _uri_to_filename(doc.uri)
        prog = _try_parse_tolerant(doc.text, filename)
        if prog is None:
            return None
        try:
            analyze(prog, filename=filename, freestanding=bool(self.settings.get("freestanding", False)))
        except SemanticError:
            pass
        return prog
    def _due_tasks(self) -> None:
        now = time.monotonic()
        due = [t for t in self.pending.values() if t.due_at <= now]
        
        # Clean expired cache entries periodically
        if len(due) > 0 and int(now) % 60 == 0:  # Every minute
            self._clean_expired_cache()
        
        for task in due:
            self.pending.pop(task.uri, None)
            doc = self.docs.get(task.uri)
            if doc is None or doc.version != task.version:
                continue
            filename = _uri_to_filename(doc.uri)
            start = time.perf_counter()
            diags = _semantic_diagnostics(
                doc.text,
                filename,
                doc.uri,
                freestanding=bool(self.settings.get("freestanding", False)),
                overflow=str(self.settings.get("overflow", "trap")),
            )
            elapsed = (time.perf_counter() - start) * 1000
            self._performance_stats["analysis_time"].append(elapsed)
            
            # Keep only recent stats
            if len(self._performance_stats["analysis_time"]) > 100:
                self._performance_stats["analysis_time"] = self._performance_stats["analysis_time"][-50:]
            
            self.log.debug("semantic diagnostics %s v%s in %.2fms", task.uri, task.version, elapsed)
            self._publish_diagnostics(task.uri, task.version, diags)
    def _local_decls(self, prog: Any, line: int, col: int) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        fn = None
        items = getattr(prog, "items", [])
        for i, item in enumerate(items):
            if not isinstance(item, FnDecl):
                continue
            next_line = None
            for nxt in items[i + 1 :]:
                ln = getattr(nxt, "line", 0)
                if ln:
                    next_line = ln
                    break
            if item.line <= line and (next_line is None or line < next_line):
                fn = item
                break
        if fn is None:
            return out
        for pname, _ in fn.params:
            out[pname] = (fn.line, fn.col)
        def before(st):
            sl = getattr(st, "line", 0)
            sc = getattr(st, "col", 0)
            return sl < line or (sl == line and sc <= col)
        def walk(stmts):
            for st in stmts:
                if not before(st):
                    break
                if isinstance(st, LetStmt):
                    out[st.name] = (st.line, st.col)
                if isinstance(st, IteratorForStmt):
                    out[st.var_name] = (st.line, st.col)
                    walk(st.body)
                if isinstance(st, IfStmt):
                    walk(st.then_body)
                    walk(st.else_body)
                if isinstance(st, WhileStmt):
                    walk(st.body)
                if isinstance(st, MatchStmt):
                    for _, b in st.arms:
                        walk(b)
                if isinstance(st, ComptimeStmt):
                    walk(st.body)
        walk(fn.body)
        return out
    def _local_decl_types(self, prog: Any, line: int, col: int) -> dict[str, str]:
        out: dict[str, str] = {}
        fn = None
        items = getattr(prog, "items", [])
        for i, item in enumerate(items):
            if not isinstance(item, FnDecl):
                continue
            next_line = None
            for nxt in items[i + 1 :]:
                ln = getattr(nxt, "line", 0)
                if ln:
                    next_line = ln
                    break
            if item.line <= line and (next_line is None or line < next_line):
                fn = item
                break
        if fn is None:
            return out
        for pname, pty in fn.params:
            out[pname] = str(pty)

        def before(st):
            sl = getattr(st, "line", 0)
            sc = getattr(st, "col", 0)
            return sl < line or (sl == line and sc <= col)

        def walk(stmts):
            for st in stmts:
                if not before(st):
                    break
                if isinstance(st, LetStmt):
                    inferred = st.type_name or getattr(st.expr, "inferred_type", None)
                    if isinstance(inferred, str):
                        out[st.name] = inferred
                if isinstance(st, IteratorForStmt):
                    out[st.var_name] = "Any"
                    walk(st.body)
                if isinstance(st, IfStmt):
                    walk(st.then_body)
                    walk(st.else_body)
                if isinstance(st, WhileStmt):
                    walk(st.body)
                if isinstance(st, MatchStmt):
                    for _, b in st.arms:
                        walk(b)
                if isinstance(st, ComptimeStmt):
                    walk(st.body)

        walk(fn.body)
        return out

    def _definition_target(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        """Enhanced go-to-definition with multiple results and better type inference."""
        doc = self.docs.get(uri)
        if doc is None:
            return []
        
        symbol = _word_at(doc.text, line0, col0)
        if not symbol:
            return []
        
        line = line0 + 1
        col = col0 + 1
        results = []
        
        # First check local scope (highest priority)
        prog = self._parse_and_analyze(doc)
        if prog is not None:
            locals_map = self._local_decls(prog, line, col)
            if symbol in locals_map:
                dl, dc = locals_map[symbol]
                results.append({
                    "uri": uri,
                    "range": {
                        "start": {"line": max(0, dl - 1), "character": max(0, dc - 1)},
                        "end": {"line": max(0, dl - 1), "character": max(0, dc - 1 + len(symbol))},
                    },
                    "origin": "local"
                })
                
                # If we found a local definition, return it immediately
                return results
            
            # Check document-level declarations
            dmap = _decl_map(prog)
            if symbol in dmap:
                d = dmap[symbol]
                results.append({
                    "uri": uri,
                    "range": {
                        "start": {"line": max(0, d["line"] - 1), "character": max(0, d["col"] - 1)},
                        "end": {"line": max(0, d["line"] - 1), "character": max(0, d["col"] - 1 + len(symbol))},
                    },
                    "origin": "document",
                    "kind": d.get("kind", 6),
                    "detail": d.get("detail", "")
                })
        
        # Check workspace symbols (for functions, types, etc.)
        workspace_matches = []
        for sym_uri, syms in self.symbol_index.items():
            for s in syms:
                if s.name == symbol and sym_uri != uri:  # Avoid duplicates from current document
                    match_info = {
                        "uri": sym_uri,
                        "range": {
                            "start": {"line": max(0, s.line - 1), "character": max(0, s.col - 1)},
                            "end": {"line": max(0, s.line - 1), "character": max(0, s.col - 1 + len(symbol))},
                        },
                        "origin": "workspace",
                        "kind": s.kind,
                        "detail": s.detail
                    }
                    
                    # Prioritize by symbol kind and relevance
                    priority = self._get_symbol_priority(s.kind, symbol)
                    workspace_matches.append((priority, match_info))
        
        # Sort workspace matches by priority and add to results
        workspace_matches.sort(key=lambda x: x[0])
        results.extend([match for _, match in workspace_matches])
        
        return results

    def _get_symbol_priority(self, kind: int, _symbol: str) -> int:
        """Lower scores sort earlier for definition/implementation lookups."""
        # LSP SymbolKind numbers currently emitted by _decl_symbols:
        # 12=function, 23=struct, 10=enum, 5=type alias, 8=field, 22=enum member.
        priority = {
            12: 0,   # function
            23: 1,   # struct
            10: 2,   # enum
            5: 3,    # type alias
            6: 4,    # variable
            13: 4,   # parameter
            8: 5,    # field/property
            22: 6,   # enum member
        }
        return priority.get(int(kind), 9)

    def _implementation_target(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        """Best-effort implementation lookup using AST declarations and workspace symbols."""
        doc = self.docs.get(uri)
        if doc is None:
            return []
        symbol = _word_at(doc.text, line0, col0)
        if not symbol:
            return []

        results: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()

        def add_loc(target_uri: str, line1: int, col1: int, *, kind: int, detail: str, origin: str) -> None:
            key = (target_uri, max(0, line1 - 1), max(0, col1 - 1))
            if key in seen:
                return
            seen.add(key)
            results.append(
                {
                    "uri": target_uri,
                    "range": {
                        "start": {"line": key[1], "character": key[2]},
                        "end": {"line": key[1], "character": key[2] + max(1, len(symbol))},
                    },
                    "kind": kind,
                    "detail": detail,
                    "origin": origin,
                }
            )

        # Current document declarations first.
        prog = self._parse_and_analyze(doc)
        if prog is not None:
            dmap = _decl_map(prog)
            decl = dmap.get(symbol)
            if decl is not None:
                add_loc(
                    uri,
                    int(decl.get("line", 1)),
                    int(decl.get("col", 1)),
                    kind=int(decl.get("kind", 6)),
                    detail=str(decl.get("detail", "")),
                    origin="document",
                )
            for item in getattr(prog, "items", []):
                if isinstance(item, StructDecl):
                    if item.name == symbol:
                        add_loc(uri, item.line, item.col, kind=23, detail=f"struct {item.name}", origin="document")
                    for m in getattr(item, "methods", []):
                        if isinstance(m, FnDecl) and m.name == symbol:
                            add_loc(uri, m.line, m.col, kind=12, detail=f"fn {m.name}", origin="document")
                elif isinstance(item, TraitDecl):
                    if item.name == symbol:
                        add_loc(uri, item.line, item.col, kind=11, detail=f"trait {item.name}", origin="document")
                    for mname, params, ret in item.methods:
                        if mname != symbol:
                            continue
                        sig = ", ".join(f"{n}: {t}" for n, t in params)
                        add_loc(
                            uri,
                            item.line,
                            item.col,
                            kind=12,
                            detail=f"trait fn {mname}({sig}) {ret}",
                            origin="document",
                        )

        # Workspace declarations.
        ranked: list[tuple[int, dict[str, Any]]] = []
        for sym_uri, syms in self.symbol_index.items():
            for s in syms:
                if s.name != symbol:
                    continue
                loc = {
                    "uri": sym_uri,
                    "range": {
                        "start": {"line": max(0, s.line - 1), "character": max(0, s.col - 1)},
                        "end": {"line": max(0, s.line - 1), "character": max(0, s.col - 1 + len(symbol))},
                    },
                    "kind": s.kind,
                    "detail": s.detail,
                    "origin": "workspace",
                }
                ranked.append((self._get_symbol_priority(s.kind, symbol), loc))
        ranked.sort(key=lambda item: item[0])
        for _, loc in ranked:
            key = (
                loc["uri"],
                int(loc["range"]["start"]["line"]),
                int(loc["range"]["start"]["character"]),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(loc)

        return results

    def _semantic_tokens_legend(self) -> dict[str, list[str]]:
        return {
            "tokenTypes": [
                "namespace",
                "type",
                "class",
                "enum",
                "interface",
                "struct",
                "typeParameter",
                "parameter",
                "variable",
                "property",
                "enumMember",
                "event",
                "function",
                "method",
                "macro",
                "keyword",
                "modifier",
                "comment",
                "string",
                "number",
                "regexp",
                "operator",
            ],
            "tokenModifiers": ["declaration", "readonly", "defaultLibrary"],
        }

    def _semantic_tokens(self, uri: str) -> dict[str, Any]:
        doc = self.docs.get(uri)
        if doc is None:
            return {"data": []}
        tokens = _tokenize_source(doc.text, _uri_to_filename(uri))
        if not tokens:
            return {"data": []}

        legend = self._semantic_tokens_legend()["tokenTypes"]
        type_idx = {name: i for i, name in enumerate(legend)}

        out: list[tuple[int, int, int, int, int]] = []
        prev_kind = ""
        for i, tok in enumerate(tokens):
            if tok.kind == "EOF":
                continue
            token_type = None
            mods = 0
            if tok.kind == "IDENT":
                nxt = tokens[i + 1].kind if i + 1 < len(tokens) else ""
                prv = tokens[i - 1].kind if i > 0 else ""
                if prev_kind in {"fn", "extern"}:
                    token_type = "function"
                    mods |= 1  # declaration
                elif prev_kind in {"struct"}:
                    token_type = "struct"
                    mods |= 1
                elif prev_kind in {"enum"}:
                    token_type = "enum"
                    mods |= 1
                elif prev_kind in {"trait"}:
                    token_type = "interface"
                    mods |= 1
                elif prev_kind in {"type"}:
                    token_type = "type"
                    mods |= 1
                elif prev_kind in {"mut", ","} and nxt == ":":
                    token_type = "parameter"
                    mods |= 1
                elif nxt == "(":
                    token_type = "function"
                elif prv == "." and nxt == "(":
                    token_type = "method"
                elif prv == ".":
                    token_type = "property"
                else:
                    token_type = "variable"
            elif tok.kind in KEYWORDS:
                token_type = "keyword"
            elif tok.kind in {"STR", "STR_MULTI", "STR_INTERP", "CHAR"}:
                token_type = "string"
            elif tok.kind in {"INT", "FLOAT"}:
                token_type = "number"
            elif tok.kind == "INT_TYPE":
                token_type = "type"
            elif tok.kind in {
                "=>",
                "->",
                "==",
                "!=",
                "<=",
                ">=",
                "&&",
                "||",
                "??",
                "+=",
                "-=",
                "*=",
                "/=",
                "%=",
                "<<=",
                ">>=",
                "&=",
                "|=",
                "^=",
                "<<",
                ">>",
                "..=",
                "..",
                "{",
                "}",
                "(",
                ")",
                "<",
                ">",
                ";",
                ",",
                "=",
                "+",
                "-",
                "*",
                "/",
                "%",
                "!",
                "?",
                "[",
                "]",
                ":",
                ".",
                "&",
                "|",
                "^",
                "~",
            }:
                token_type = "operator"
            if token_type is None:
                prev_kind = tok.kind
                continue
            out.append((max(0, tok.line - 1), max(0, tok.col - 1), max(1, len(tok.text)), type_idx[token_type], mods))
            prev_kind = tok.kind

        out.sort(key=lambda t: (t[0], t[1]))
        data: list[int] = []
        prev_line = 0
        prev_col = 0
        for line0, col0, length, t_idx, mods in out:
            dl = line0 - prev_line
            ds = col0 - prev_col if dl == 0 else col0
            data.extend([dl, ds, length, t_idx, mods])
            prev_line = line0
            prev_col = col0
        return {"data": data}

    def _inlay_hints(self, uri: str, req_range: dict[str, Any]) -> list[dict[str, Any]]:
        doc = self.docs.get(uri)
        if doc is None:
            return []
        prog = self._parse_and_analyze(doc)
        if prog is None:
            return []
        start_line = int(req_range.get("start", {}).get("line", 0))
        end_line = int(req_range.get("end", {}).get("line", start_line))

        out: list[dict[str, Any]] = []
        filename = _uri_to_filename(uri)
        toks = _tokenize_source(doc.text, filename)

        fn_params: dict[str, list[str]] = {}
        for item in getattr(prog, "items", []):
            if isinstance(item, FnDecl):
                fn_params[item.name] = [p for p, _ in item.params]
            elif isinstance(item, TraitDecl):
                for mname, params, _ in item.methods:
                    fn_params[mname] = [p for p, _ in params]

        for node in _iter_ast(prog):
            if isinstance(node, LetStmt):
                line0 = max(0, int(getattr(node, "line", 1)) - 1)
                if line0 < start_line or line0 > end_line:
                    continue
                if node.type_name is not None:
                    continue
                inferred = getattr(node.expr, "inferred_type", None)
                if not isinstance(inferred, str) or not _is_stable_user_facing_type(inferred):
                    continue
                info = _binding_decl_token_info(toks, node)
                name_tok = info.get("name") if info is not None else None
                if name_tok is None:
                    continue
                out.append(
                    {
                        "position": {"line": max(0, name_tok.line - 1), "character": max(0, name_tok.col - 1 + len(name_tok.text))},
                        "label": f": {_pretty_type_text(inferred)}",
                        "kind": 1,  # Type
                    }
                )
            elif isinstance(node, Call):
                line0 = max(0, int(getattr(node, "line", 1)) - 1)
                if line0 < start_line or line0 > end_line:
                    continue
                fn_name = node.fn.value if isinstance(node.fn, Name) else None
                if not fn_name:
                    continue
                params = fn_params.get(fn_name, [])
                for i, arg in enumerate(node.args):
                    if i >= len(params):
                        break
                    out.append(
                        {
                            "position": {"line": max(0, int(getattr(arg, "line", 1)) - 1), "character": max(0, int(getattr(arg, "col", 1)) - 1)},
                            "label": f"{params[i]}:",
                            "kind": 2,  # Parameter
                            "paddingRight": True,
                        }
                    )
        return out[:200]

    def _folding_ranges(self, uri: str) -> list[dict[str, Any]]:
        doc = self.docs.get(uri)
        if doc is None:
            return []
        lines = doc.text.splitlines()
        out: list[dict[str, Any]] = []

        # Fold import groups.
        import_start = None
        for i, row in enumerate(lines):
            if row.strip().startswith("import "):
                if import_start is None:
                    import_start = i
            else:
                if import_start is not None and i - 1 > import_start:
                    out.append({"startLine": import_start, "endLine": i - 1, "kind": "imports"})
                import_start = None
        if import_start is not None and len(lines) - 1 > import_start:
            out.append({"startLine": import_start, "endLine": len(lines) - 1, "kind": "imports"})

        # Fold brace-delimited blocks.
        stack: list[int] = []
        in_string = False
        escaped = False
        for ln, row in enumerate(lines):
            for ch in row:
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    stack.append(ln)
                elif ch == "}" and stack:
                    start_ln = stack.pop()
                    if ln > start_ln:
                        out.append({"startLine": start_ln, "endLine": ln - 1, "kind": "region"})
        out.sort(key=lambda r: (r["startLine"], r["endLine"]))
        return out[:500]

    def _execute_command(self, params: dict[str, Any]) -> Any:
        command = str(params.get("command", ""))
        args = params.get("arguments", [])
        if command == "astra.formatDocument":
            uri = str(args[0]) if args else ""
            return {"edits": self._format_document(uri)} if uri else {"edits": []}
        if command == "astra.rebuildProject":
            self._scan_workspace()
            for uri, doc in self.docs.items():
                self._update_symbol_index(uri)
                self._schedule_semantic(uri, doc.version)
            return {"ok": True, "message": "project rebuilt"}
        if command == "astra.runTests":
            if not self.workspace_folders:
                return {"ok": False, "message": "no workspace folder configured"}
            root = self.workspace_folders[0]
            try:
                proc = subprocess.run(
                    ["pytest", "-q"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
                return {"ok": proc.returncode == 0, "code": proc.returncode, "output": output[-8000:]}
            except Exception as err:
                return {"ok": False, "message": str(err)}
        return {"ok": False, "message": f"unknown command: {command}"}

    def _call_hierarchy(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        doc = self.docs.get(uri)
        if doc is None:
            return []
        name = _word_at(doc.text, line0, col0)
        if not name:
            return []
        defs = self._definition_target(uri, line0, col0)
        if defs:
            d = defs[0]
            return [
                {
                    "name": name,
                    "kind": int(d.get("kind", 12)),
                    "uri": d.get("uri", uri),
                    "range": d["range"],
                    "selectionRange": d["range"],
                    "detail": d.get("detail", ""),
                    "data": {"name": name},
                }
            ]
        return []

    def _incoming_calls(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        target_name = str(item.get("data", {}).get("name") or item.get("name") or "")
        if not target_name:
            return []
        out: list[dict[str, Any]] = []
        uris = set(self.symbol_index.keys()) | set(self.docs.keys())
        for uri in uris:
            doc = self.docs.get(uri)
            if doc is None and uri.startswith("file://"):
                try:
                    text = Path(_uri_to_filename(uri)).read_text()
                except Exception:
                    continue
                doc = TextDocument(uri=uri, text=text, version=0, language_id="astra")
            if doc is None:
                continue
            prog = self._parse_and_analyze(doc)
            if prog is None:
                continue
            for fn in getattr(prog, "items", []):
                if not isinstance(fn, FnDecl):
                    continue
                call_ranges: list[dict[str, Any]] = []
                for node in _iter_ast(fn.body):
                    if isinstance(node, Call) and isinstance(node.fn, Name) and node.fn.value == target_name:
                        ln = max(0, int(getattr(node.fn, "line", 1)) - 1)
                        col = max(0, int(getattr(node.fn, "col", 1)) - 1)
                        call_ranges.append(
                            {
                                "start": {"line": ln, "character": col},
                                "end": {"line": ln, "character": col + max(1, len(target_name))},
                            }
                        )
                if not call_ranges:
                    continue
                from_item = {
                    "name": fn.name,
                    "kind": 12,
                    "uri": uri,
                    "detail": f"fn {fn.name}",
                    "range": {
                        "start": {"line": max(0, fn.line - 1), "character": max(0, fn.col - 1)},
                        "end": {"line": max(0, fn.line - 1), "character": max(0, fn.col - 1 + len(fn.name))},
                    },
                    "selectionRange": {
                        "start": {"line": max(0, fn.line - 1), "character": max(0, fn.col - 1)},
                        "end": {"line": max(0, fn.line - 1), "character": max(0, fn.col - 1 + len(fn.name))},
                    },
                    "data": {"name": fn.name},
                }
                out.append({"from": from_item, "fromRanges": call_ranges})
        return out[:200]

    def _outgoing_calls(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        src_name = str(item.get("data", {}).get("name") or item.get("name") or "")
        src_uri = str(item.get("uri") or "")
        if not src_name:
            return []
        out: list[dict[str, Any]] = []
        doc = self.docs.get(src_uri)
        if doc is None and src_uri.startswith("file://"):
            try:
                text = Path(_uri_to_filename(src_uri)).read_text()
            except Exception:
                return []
            doc = TextDocument(uri=src_uri, text=text, version=0, language_id="astra")
        if doc is None:
            return []
        prog = self._parse_and_analyze(doc)
        if prog is None:
            return []
        src_fn = None
        for fn in getattr(prog, "items", []):
            if isinstance(fn, FnDecl) and fn.name == src_name:
                src_fn = fn
                break
        if src_fn is None:
            return []

        seen: set[tuple[str, int, int]] = set()
        for node in _iter_ast(src_fn.body):
            if not (isinstance(node, Call) and isinstance(node.fn, Name)):
                continue
            target = node.fn.value
            target_defs = []
            for uri, syms in self.symbol_index.items():
                for s in syms:
                    if s.name == target and s.kind == 12:
                        target_defs.append((uri, s))
            if not target_defs:
                continue
            call_ln = max(0, int(getattr(node.fn, "line", 1)) - 1)
            call_col = max(0, int(getattr(node.fn, "col", 1)) - 1)
            call_rng = {
                "start": {"line": call_ln, "character": call_col},
                "end": {"line": call_ln, "character": call_col + max(1, len(target))},
            }
            for tgt_uri, sym in target_defs[:1]:
                key = (tgt_uri, max(0, sym.line - 1), max(0, sym.col - 1))
                if key in seen:
                    continue
                seen.add(key)
                to_item = {
                    "name": sym.name,
                    "kind": 12,
                    "uri": tgt_uri,
                    "detail": sym.detail,
                    "range": {
                        "start": {"line": max(0, sym.line - 1), "character": max(0, sym.col - 1)},
                        "end": {"line": max(0, sym.line - 1), "character": max(0, sym.col - 1 + len(sym.name))},
                    },
                    "selectionRange": {
                        "start": {"line": max(0, sym.line - 1), "character": max(0, sym.col - 1)},
                        "end": {"line": max(0, sym.line - 1), "character": max(0, sym.col - 1 + len(sym.name))},
                    },
                    "data": {"name": sym.name},
                }
                out.append({"to": to_item, "fromRanges": [call_rng]})
        return out[:200]

    def _type_hierarchy(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        doc = self.docs.get(uri)
        if doc is None:
            return []
        symbol = _word_at(doc.text, line0, col0)
        if not symbol:
            return []
        defs = self._definition_target(uri, line0, col0)
        if not defs:
            return []
        d = defs[0]
        kind = int(d.get("kind", 5))
        if kind not in {5, 10, 11, 23}:
            return []
        return [
            {
                "name": symbol,
                "kind": kind,
                "uri": d.get("uri", uri),
                "range": d["range"],
                "selectionRange": d["range"],
                "detail": d.get("detail", ""),
                "data": {"name": symbol},
            }
        ]

    def _type_relationships(self) -> tuple[dict[str, set[str]], dict[str, tuple[str, int, int, int, str]]]:
        parents: dict[str, set[str]] = {}
        decls: dict[str, tuple[str, int, int, int, str]] = {}
        uris = set(self.symbol_index.keys()) | set(self.docs.keys())
        for uri in uris:
            doc = self.docs.get(uri)
            if doc is None and uri.startswith("file://"):
                try:
                    text = Path(_uri_to_filename(uri)).read_text()
                except Exception:
                    continue
                doc = TextDocument(uri=uri, text=text, version=0, language_id="astra")
            if doc is None:
                continue
            prog = self._parse_and_analyze(doc)
            if prog is None:
                continue
            for item in getattr(prog, "items", []):
                if isinstance(item, StructDecl):
                    decls[item.name] = (uri, item.line, item.col, 23, f"struct {item.name}")
                    ps = set(getattr(item, "derives", []) or [])
                    if ps:
                        parents.setdefault(item.name, set()).update(ps)
                elif isinstance(item, EnumDecl):
                    decls[item.name] = (uri, item.line, item.col, 10, f"enum {item.name}")
                    ps = set(getattr(item, "derives", []) or [])
                    if ps:
                        parents.setdefault(item.name, set()).update(ps)
                elif isinstance(item, TraitDecl):
                    decls[item.name] = (uri, item.line, item.col, 11, f"trait {item.name}")
                elif isinstance(item, TypeAliasDecl):
                    decls[item.name] = (uri, item.line, item.col, 5, f"type {item.name}")
                    base = str(item.target).split("<", 1)[0].strip()
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
                        parents.setdefault(item.name, set()).add(base)
        return parents, decls

    def _supertypes(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        name = str(item.get("data", {}).get("name") or item.get("name") or "")
        if not name:
            return []
        parents, decls = self._type_relationships()
        out: list[dict[str, Any]] = []
        for p in sorted(parents.get(name, set())):
            if p not in decls:
                continue
            uri, line1, col1, kind, detail = decls[p]
            rng = {
                "start": {"line": max(0, line1 - 1), "character": max(0, col1 - 1)},
                "end": {"line": max(0, line1 - 1), "character": max(0, col1 - 1 + len(p))},
            }
            out.append({"name": p, "kind": kind, "uri": uri, "range": rng, "selectionRange": rng, "detail": detail, "data": {"name": p}})
        return out

    def _subtypes(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        name = str(item.get("data", {}).get("name") or item.get("name") or "")
        if not name:
            return []
        parents, decls = self._type_relationships()
        out: list[dict[str, Any]] = []
        for child, ps in parents.items():
            if name not in ps or child not in decls:
                continue
            uri, line1, col1, kind, detail = decls[child]
            rng = {
                "start": {"line": max(0, line1 - 1), "character": max(0, col1 - 1)},
                "end": {"line": max(0, line1 - 1), "character": max(0, col1 - 1 + len(child))},
            }
            out.append({"name": child, "kind": kind, "uri": uri, "range": rng, "selectionRange": rng, "detail": detail, "data": {"name": child}})
        return out

    def _linked_editing_ranges(self, uri: str, line0: int, col0: int) -> dict[str, Any] | None:
        doc = self.docs.get(uri)
        if doc is None:
            return None
        lines = doc.text.splitlines()
        if line0 < 0 or line0 >= len(lines):
            return None
        row = lines[line0]
        if not row:
            return None
        pos = min(max(0, col0), max(0, len(row) - 1))

        pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
        rev = {v: k for k, v in pairs.items()}
        ch = row[pos]
        if ch in pairs or ch in rev:
            open_ch = ch if ch in pairs else rev[ch]
            close_ch = pairs[open_ch]
            text = doc.text
            off = _position_to_offset(text, line0, pos)
            if ch in pairs:
                depth = 0
                i = off
                while i < len(text):
                    c = text[i]
                    if c == open_ch:
                        depth += 1
                    elif c == close_ch:
                        depth -= 1
                        if depth == 0:
                            end_line, end_col = _offset_to_position(text, i)
                            return {
                                "ranges": [
                                    {"start": {"line": line0, "character": pos}, "end": {"line": line0, "character": pos + 1}},
                                    {"start": {"line": end_line, "character": end_col}, "end": {"line": end_line, "character": end_col + 1}},
                                ]
                            }
                    i += 1
            else:
                depth = 0
                i = off
                while i >= 0:
                    c = text[i]
                    if c == close_ch:
                        depth += 1
                    elif c == open_ch:
                        depth -= 1
                        if depth == 0:
                            start_line, start_col = _offset_to_position(text, i)
                            return {
                                "ranges": [
                                    {"start": {"line": start_line, "character": start_col}, "end": {"line": start_line, "character": start_col + 1}},
                                    {"start": {"line": line0, "character": pos}, "end": {"line": line0, "character": pos + 1}},
                                ]
                            }
                    i -= 1

        symbol, s, e = _word_bounds(doc.text, line0, col0)
        if not symbol:
            return None
        decl_line = lines[line0].strip()
        if re.match(rf"^(fn|struct|enum|trait|type)\s+{re.escape(symbol)}\b", decl_line):
            ranges = []
            for m in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", lines[line0]):
                ranges.append(
                    {
                        "start": {"line": line0, "character": m.start()},
                        "end": {"line": line0, "character": m.end()},
                    }
                )
            if len(ranges) >= 2:
                return {"ranges": ranges, "wordPattern": r"[A-Za-z_][A-Za-z0-9_]*"}
        return None

    def _rename_conflict_reason(self, uri: str, line0: int, col0: int, old_name: str, new_name: str) -> str | None:
        if new_name in KEYWORDS:
            return "rename target is a reserved keyword"
        doc = self.docs.get(uri)
        if doc is None:
            return None
        prog = self._parse_and_analyze(doc)
        if prog is None:
            return None
        line = line0 + 1
        col = col0 + 1
        locals_map = self._local_decls(prog, line, col)
        if old_name in locals_map and new_name in locals_map and old_name != new_name:
            return f"`{new_name}` already exists in local scope"
        dmap = _decl_map(prog)
        if old_name in dmap and new_name in dmap and old_name != new_name:
            return f"`{new_name}` already exists in this module"
        return None

    def _hover(self, uri: str, line0: int, col0: int) -> dict[str, Any] | None:
        doc = self.docs.get(uri)
        if doc is None:
            return None
        symbol = _word_at(doc.text, line0, col0)
        if not symbol:
            return {"contents": {"kind": "markdown", "value": "Astra source"}}
        if symbol in KEYWORDS:
            return {"contents": {"kind": "markdown", "value": f"`{symbol}` keyword"}}
        prog = self._parse_and_analyze(doc)
        if prog is not None:
            for node in _iter_ast(prog):
                if isinstance(node, Name):
                    if node.line == line0 + 1 and max(0, node.col - 1) <= col0 < max(0, node.col - 1) + len(node.value):
                        inferred = getattr(node, "inferred_type", None)
                        if inferred:
                            return {"contents": {"kind": "markdown", "value": f"`{symbol}`: `{inferred}`"}}
            dmap = _decl_map(prog)
            decl = dmap.get(symbol)
            if decl is not None:
                docp = _first_paragraph(decl.get("doc", ""))
                content = f"```astra\n{decl['detail']}\n```"
                if docp:
                    content += f"\n\n{docp}"
                return {"contents": {"kind": "markdown", "value": content}}
        if symbol in BUILTIN_SIGS:
            sig = BUILTIN_SIGS[symbol]
            args = ", ".join(sig.args or ["..."])
            text = f"`builtin {symbol}({args}) {sig.ret}`"
            hint = BUILTIN_DOCS.get(symbol, "")
            if hint:
                text += f"\n\n{hint}"
            return {"contents": {"kind": "markdown", "value": text}}
        if symbol == "gpu":
            api_list = "\n".join(f"- `gpu.{name}`: {doc_text}" for name, doc_text in sorted(GPU_API_DOCS.items()))
            return {"contents": {"kind": "markdown", "value": f"### GPU namespace\n{api_list}"}}
        line_text = doc.text.splitlines()[line0] if 0 <= line0 < len(doc.text.splitlines()) else ""
        if "." in line_text:
            for api, api_doc in GPU_API_DOCS.items():
                if f"gpu.{api}" in line_text and symbol == api:
                    return {"contents": {"kind": "markdown", "value": f"`gpu.{api}`\n\n{api_doc}"}}
        return {"contents": {"kind": "markdown", "value": f"Astra symbol `{symbol}`"}}

    def _completion(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        """Enhanced completion with caching and performance monitoring."""
        doc = self.docs.get(uri)
        if doc is None:
            return []
        
        start_time = time.perf_counter()
        
        # Create cache key based on context
        context_key = f"{uri}:{doc.version}:{line0}:{col0}"
        
        # Check cache first
        if context_key in self._completion_cache:
            cached_completions, timestamp = self._completion_cache[context_key]
            if time.time() - timestamp < self._cache_ttl:
                self._performance_stats["cache_hits"] += 1
                return cached_completions
            else:
                del self._completion_cache[context_key]
        
        self._performance_stats["cache_misses"] += 1
        
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        
        # Get context for intelligent completion
        context = self._get_completion_context(doc, line0, col0)
        
        def add(label: str, kind: int, detail: str, insert_text: str | None = None, insert_format: int | None = None, priority: int = 0) -> None:
            if not label or label in seen:
                return
            seen.add(label)
            item: dict[str, Any] = {
                "label": label, 
                "kind": kind, 
                "detail": detail,
                "sortText": f"{priority:03d}{label}"
            }
            if insert_text is not None:
                item["insertText"] = insert_text
            if insert_format is not None:
                item["insertTextFormat"] = insert_format
            out.append(item)
        
        # Context-aware suggestions
        if context["in_function_call"]:
            self._add_argument_completions(doc, context, add)
            # Keep full symbol visibility while typing call arguments.
            self._add_standard_completions(doc, context, add)
        elif context["in_type_annotation"]:
            self._add_type_completions(doc, context, add)
        elif context["in_import"]:
            self._add_import_completions(doc, context, add)
        elif context["after_dot"]:
            self._add_member_completions(doc, context, add)
        elif context["in_match"]:
            self._add_standard_completions(doc, context, add)
            add("_", 13, "wildcard match pattern", priority=95)
            add("none", 13, "optional none pattern", priority=94)
            add("true", 13, "bool pattern", priority=93)
            add("false", 13, "bool pattern", priority=93)
        else:
            # Standard completions
            self._add_standard_completions(doc, context, add)
        
        # Cache the result
        self._completion_cache[context_key] = (out, time.time())
        
        # Update performance stats
        completion_time = time.perf_counter() - start_time
        self._performance_stats["completion_time"].append(completion_time)
        
        # Keep only recent stats
        if len(self._performance_stats["completion_time"]) > 100:
            self._performance_stats["completion_time"] = self._performance_stats["completion_time"][-50:]
            
        return out
    
    def _get_completion_context(self, doc: TextDocument, line: int, col: int) -> dict[str, Any]:
        """Analyze the context around the cursor for intelligent completion."""
        lines = doc.text.splitlines()
        if line < 0 or line >= len(lines):
            return {"in_function_call": False, "in_type_annotation": False, "in_import": False, "after_dot": False}
        
        current_line = lines[line]
        prefix = current_line[:col]
        suffix = current_line[col:]
        
        # Check for different contexts
        context = {
            "in_function_call": False,
            "in_type_annotation": False, 
            "in_import": False,
            "after_dot": False,
            "in_match": False,
            "current_token": "",
            "function_name": "",
            "type_base": "",
            "type_prefix": "",
            "inferred_type": "",
            "object_type": None,
            "line": line,
            "col": col
        }

        prog = self._parse_and_analyze(doc)
        if prog is not None:
            ann = _binding_annotation_context(prog, doc.text, _uri_to_filename(doc.uri), line, col)
            if ann is not None:
                context["in_type_annotation"] = True
                context["type_prefix"] = ann.get("prefix", "")
                context["inferred_type"] = ann.get("inferred_type", "")
                if context["type_prefix"]:
                    context["current_token"] = context["type_prefix"]
        
        # Function call context
        if '(' in prefix and not prefix.rstrip().endswith(')'):
            context["in_function_call"] = True
            # Extract function name
            func_match = re.search(r'(\w+)\s*\(\s*[^)]*$', prefix)
            if func_match:
                context["function_name"] = func_match.group(1)
        
        # Type annotation context  
        if not context["in_type_annotation"] and ':' in prefix and ('fn' in prefix or 'mut' in prefix):
            context["in_type_annotation"] = True
            type_match = re.search(r':\s*(\w*)$', prefix)
            if type_match:
                context["type_base"] = type_match.group(1)
                context["type_prefix"] = type_match.group(1)
        
        # Import context
        if 'import' in prefix:
            context["in_import"] = True
        
        # Member access context (after dot)
        if prefix.endswith('.'):
            context["after_dot"] = True
            # Try to determine object type
            obj_match = re.search(r'(\w+)\s*\.$', prefix)
            if obj_match:
                obj_name = obj_match.group(1)
                context["current_token"] = obj_name
        
        if re.search(r'\bmatch\b', prefix):
            context["in_match"] = True

        # Current token being typed
        token_match = re.search(r'(\w+)$', prefix)
        if token_match:
            context["current_token"] = token_match.group(1)
            
        return context
    
    def _add_standard_completions(self, doc: TextDocument, context: dict[str, Any], add) -> None:
        """Add standard completions for keywords, builtins, and symbols."""
        # Keywords with snippets
        for k in KEYWORDS:
            snippet = SNIPPETS.get(k)
            if snippet:
                add(k, 15, "snippet", insert_text=snippet, insert_format=2, priority=100)
            else:
                add(k, 14, "keyword", priority=90)
        
        # GPU namespace and APIs
        add("gpu", 9, "GPU runtime namespace", priority=92)
        for api, doc_text in sorted(GPU_API_DOCS.items()):
            add(f"gpu.{api}", 3, doc_text, priority=88)

        # Built-in functions
        for b in BUILTIN_SIGS:
            if not b.startswith("__"):
                sig = BUILTIN_SIGS[b]
                args = ", ".join(sig.args or ["..."])
                detail = f"builtin {b}({args}) {sig.ret}"
                add(b, 3, detail, priority=80)
        
        # Local symbols
        prog = self._parse_and_analyze(doc)
        if prog is not None:
            # Document symbols
            for sym in _decl_symbols(prog, doc.uri):
                if sym.kind == 12:  # Function
                    add(sym.name, 3, sym.detail, insert_text=f"{sym.name}($1)", insert_format=2, priority=70)
                else:
                    add(sym.name, 6, sym.detail, priority=60)
            
            # Local variables in scope
            locals_map = self._local_decls(prog, context.get("line", 0) + 1, context.get("col", 0) + 1)
            for name in sorted(locals_map):
                add(name, 6, "local variable", priority=85)
        
        # Workspace symbols
        for syms in self.symbol_index.values():
            for s in syms:
                if s.uri != doc.uri:  # Don't duplicate local symbols
                    add(s.name, 6, s.detail, priority=50)
    
    def _add_type_completions(self, doc: TextDocument, context: dict[str, Any], add) -> None:
        """Add type-specific completions."""
        prefix = str(context.get("type_prefix", "") or "").strip()
        prefix_l = prefix.lower()

        def allow(label: str) -> bool:
            if not prefix_l:
                return True
            return label.lower().startswith(prefix_l)

        inferred = _pretty_type_text(str(context.get("inferred_type", "") or ""))
        if inferred and _is_stable_user_facing_type(inferred) and allow(inferred):
            add(inferred, 5, "inferred type", priority=1)
            if "|" in inferred:
                for member in _normalized_union_members(inferred):
                    if allow(member):
                        add(member, 5, "union member type", priority=2)

        builtin_types = [
            "Int",
            "isize",
            "usize",
            "Float",
            "f16",
            "f32",
            "f64",
            "f80",
            "f128",
            "Bool",
            "String",
            "str",
            "Bytes",
            "Void",
            "none",
        ]
        for t in builtin_types:
            if allow(t):
                add(t, 5, f"builtin type {t}", priority=40)

        # Container and pointer/reference spellings supported by parser/semantic.
        shaped = [
            ("Vec<$1>", "generic vec type"),
            ("Map<$1, $2>", "generic map type"),
            ("Set<$1>", "generic set type"),
            ("[$1]", "slice/array type"),
            ("&$1", "reference type"),
            ("&mut $1", "mutable reference type"),
            ("*$1", "pointer type"),
        ]
        for label, detail in shaped:
            if allow(label):
                add(label, 5, detail, insert_text=label, insert_format=2, priority=50)

        # User-defined types from current program and workspace index.
        prog = self._parse_and_analyze(doc)
        if prog is not None:
            for sym in _decl_symbols(prog, doc.uri):
                if sym.kind in {23, 10, 5} and allow(sym.name):  # struct/enum/type alias
                    add(sym.name, 5, sym.detail, priority=30)

        for syms in self.symbol_index.values():
            for s in syms:
                if s.kind in {23, 10, 5} and allow(s.name):
                    add(s.name, 5, s.detail, priority=60)
    
    def _add_import_completions(self, doc: TextDocument, context: dict[str, Any], add) -> None:
        """Add import-specific completions."""
        # Standard library modules
        stdlib_modules = ["algorithm", "atomic", "c", "collections", "gpu", "math", "os", "time"]
        for module in stdlib_modules:
            add(module, 9, f"std library module {module}", priority=90)
        
        # Local files that could be imported
        try:
            current_dir = Path(_uri_to_filename(doc.uri)).parent
            for file_path in current_dir.rglob("*.arixa"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(current_dir)
                    module_name = str(rel_path.with_suffix("")).replace("/", ".")
                    add(module_name, 9, f"local module {module_name}", priority=80)
        except Exception:
            pass
    
    def _add_argument_completions(self, doc: TextDocument, context: dict[str, Any], add) -> None:
        """Add argument completions for function calls."""
        func_name = context.get("function_name", "")
        
        # Check if it's a known function with specific argument types
        if func_name in BUILTIN_SIGS:
            sig = BUILTIN_SIGS[func_name]
            if sig.args:
                # Suggest variables that match the parameter types
                prog = self._parse_and_analyze(doc)
                if prog:
                    locals_map = self._local_decls(prog, context.get("line", 0) + 1, context.get("col", 0) + 1)
                    for var_name in sorted(locals_map):
                        add(var_name, 6, f"variable {var_name}", priority=90)
        
        # General variable suggestions
        prog = self._parse_and_analyze(doc)
        if prog:
            locals_map = self._local_decls(prog, context.get("line", 0) + 1, context.get("col", 0) + 1)
            for var_name in sorted(locals_map):
                add(var_name, 6, f"variable {var_name}", priority=80)
    
    def _add_member_completions(self, doc: TextDocument, context: dict[str, Any], add) -> None:
        """Add member completions for dot access."""
        obj_name = context.get("current_token", "")
        if obj_name == "gpu":
            for api, doc_text in sorted(GPU_API_DOCS.items()):
                add(api, 3, doc_text, insert_text=f"{api}($1)", insert_format=2, priority=98)
            return

        prog = self._parse_and_analyze(doc)
        if prog is not None and obj_name:
            locals_types = self._local_decl_types(prog, context.get("line", 0) + 1, context.get("col", 0) + 1)
            obj_ty = locals_types.get(obj_name)
            if obj_ty:
                for item in getattr(prog, "items", []):
                    if isinstance(item, StructDecl) and item.name == obj_ty:
                        for fname, fty in item.fields:
                            add(fname, 8, f"field {fname}: {fty}", priority=97)
                        return

        # Heuristic fallback for incomplete code during typing: `name = StructName(`
        if obj_name:
            row_limit = context.get("line", 0)
            lines = doc.text.splitlines()
            local_text = "\n".join(lines[: row_limit + 1])
            m = re.search(rf"\b{re.escape(obj_name)}\s*=\s*([A-Z][A-Za-z0-9_]*)\s*\(", local_text)
            if m:
                struct_name = m.group(1)
                struct_match = re.search(rf"struct\s+{re.escape(struct_name)}\s*\{{([^}}]*)\}}", doc.text, re.DOTALL)
                if struct_match:
                    body = struct_match.group(1)
                    for part in body.split(","):
                        chunk = part.strip()
                        if not chunk:
                            continue
                        bits = chunk.split()
                        if len(bits) >= 2:
                            fname = bits[0]
                            fty = " ".join(bits[1:])
                            add(fname, 8, f"field {fname}: {fty}", priority=96)
                    return

        common_methods = ["len", "push", "pop", "get", "set", "clear", "is_empty", "clone"]
        for method in common_methods:
            add(method, 3, f"method {method}", insert_text=f"{method}($1)", insert_format=2, priority=85)

        common_fields = ["data", "size", "capacity", "length", "count"]
        for field in common_fields:
            add(field, 8, f"field {field}", priority=80)
    
    def _signature_help(self, uri: str, line0: int, col0: int) -> dict[str, Any] | None:
        doc = self.docs.get(uri)
        if doc is None:
            return None
        off = _position_to_offset(doc.text, line0, col0)
        prefix = doc.text[:off]
        depth = 0
        arg_index = 0
        open_idx = -1
        for i in range(len(prefix) - 1, -1, -1):
            ch = prefix[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    open_idx = i
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                arg_index += 1
        if open_idx < 0:
            return None
        j = open_idx - 1
        while j >= 0 and (prefix[j].isalnum() or prefix[j] == "_"):
            j -= 1
        fn_name = prefix[j + 1 : open_idx]
        if not fn_name:
            return None
        sig_label = None
        params: list[str] = []
        for syms in self.symbol_index.values():
            for s in syms:
                if s.name == fn_name and s.kind == 12:
                    sig_label = s.detail
                    m = re.search(r"\((.*)\)", s.detail)
                    if m:
                        raw = m.group(1).strip()
                        params = [p.strip() for p in raw.split(",")] if raw else []
                    break
            if sig_label:
                break
        if sig_label is None and fn_name in BUILTIN_SIGS:
            bs = BUILTIN_SIGS[fn_name]
            params = bs.args or []
            sig_label = f"{fn_name}({', '.join(params)}) {bs.ret}"
        if sig_label is None:
            return None
        return {
            "signatures": [{"label": sig_label, "parameters": [{"label": p} for p in params]}],
            "activeSignature": 0,
            "activeParameter": min(arg_index, max(0, len(params) - 1)) if params else 0,
        }
    def _find_word_refs(self, uri: str, name: str, include_decl: bool) -> list[dict[str, Any]]:
        locs: list[dict[str, Any]] = []
        rex = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
        def scan_uri(u: str, txt: str):
            for m in rex.finditer(txt):
                s_off, e_off = m.span()
                s_line, s_col = _offset_to_position(txt, s_off)
                e_line, e_col = _offset_to_position(txt, e_off)
                locs.append(
                    {
                        "uri": u,
                        "range": {
                            "start": {"line": s_line, "character": s_col},
                            "end": {"line": e_line, "character": e_col},
                        },
                    }
                )
        for u, d in self.docs.items():
            scan_uri(u, d.text)
        if include_decl:
            defs = self._definition_target(uri, 0, 0)
            for d in defs:
                if d not in locs:
                    locs.append(d)
        return locs
    def _document_symbols(self, uri: str) -> list[dict[str, Any]]:
        out = []
        for s in self.symbol_index.get(uri, []):
            line0 = max(0, s.line - 1)
            col0 = max(0, s.col - 1)
            out.append(
                {
                    "name": s.name,
                    "kind": s.kind,
                    "detail": s.detail,
                    "range": {
                        "start": {"line": line0, "character": col0},
                        "end": {"line": line0, "character": col0 + max(1, len(s.name))},
                    },
                    "selectionRange": {
                        "start": {"line": line0, "character": col0},
                        "end": {"line": line0, "character": col0 + max(1, len(s.name))},
                    },
                }
            )
        return out
    def _workspace_symbols(self, query: str) -> list[dict[str, Any]]:
        q = (query or "").lower()
        out = []
        for uri, syms in self.symbol_index.items():
            for s in syms:
                if q and q not in s.name.lower() and q not in s.detail.lower():
                    continue
                line0 = max(0, s.line - 1)
                col0 = max(0, s.col - 1)
                out.append(
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "location": {
                            "uri": uri,
                            "range": {
                                "start": {"line": line0, "character": col0},
                                "end": {"line": line0, "character": col0 + max(1, len(s.name))},
                            },
                        },
                        "containerName": s.detail,
                    }
                )
        return out[:200]
    def _format_document(self, uri: str) -> list[dict[str, Any]]:
        doc = self.docs.get(uri)
        if doc is None:
            return []
        path = Path(_uri_to_filename(uri)) if uri.startswith("file://") else None
        cfg = resolve_format_config(path) if path is not None else resolve_format_config(None)
        new_text = fmt(doc.text, config=cfg)
        if new_text == doc.text:
            return []
        end_line, end_col = _offset_to_position(doc.text, len(doc.text))
        return [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": end_line, "character": end_col},
                },
                "newText": new_text,
            }
        ]
    def _code_actions(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        text_doc = params.get("textDocument", {})
        uri = text_doc.get("uri", "")
        context = params.get("context", {})
        diagnostics = context.get("diagnostics", [])
        actions: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for diag in diagnostics:
            data = diag.get("data", {})
            suggestions = data.get("suggestions", []) if isinstance(data, dict) else []
            for s in suggestions:
                rng = s.get("range")
                replacement = s.get("replacement")
                if replacement is None or rng is None:
                    continue
                key = (
                    str(diag.get("code", "")),
                    str(rng.get("start", {}).get("line", "")),
                    str(rng.get("start", {}).get("character", "")),
                    str(rng.get("end", {}).get("line", "")),
                    str(rng.get("end", {}).get("character", "")),
                )
                if key in seen:
                    continue
                seen.add(key)
                actions.append(
                    {
                        "title": s.get("message") or "Apply suggested fix",
                        "kind": "quickfix",
                        "isPreferred": True,
                        "diagnostics": [diag],
                        "edit": {"changes": {uri: [{"range": rng, "newText": replacement}]}},
                    }
                )
        # --- Deeper quick-fix: import suggestions for unresolved names ---
        doc = self.docs.get(uri)
        if doc is not None:
            for diag in diagnostics:
                msg = diag.get("message", "")
                # Suggest adding missing import for unresolved name errors
                if "undefined" in msg.lower() or "unresolved" in msg.lower() or "not defined" in msg.lower():
                    # Extract the symbol name from the diagnostic
                    import re as _re
                    m = _re.search(r"`(\w+)`", msg)
                    if m:
                        sym = m.group(1)
                        # Search workspace for the symbol in other files
                        for other_uri, symbols in self.symbol_index.items():
                            if other_uri == uri:
                                continue
                            for si in symbols:
                                if si.name == sym:
                                    # Build an import quick-fix
                                    other_path = _uri_to_filename(other_uri)
                                    import_line = f'import "{other_path}";\n'
                                    fix_key = ("import", sym, other_uri, "", "")
                                    if fix_key not in seen:
                                        seen.add(fix_key)
                                        actions.append({
                                            "title": f'Add import for `{sym}` from {other_path}',
                                            "kind": "quickfix",
                                            "isPreferred": False,
                                            "diagnostics": [diag],
                                            "edit": {
                                                "changes": {
                                                    uri: [{
                                                        "range": {
                                                            "start": {"line": 0, "character": 0},
                                                            "end": {"line": 0, "character": 0},
                                                        },
                                                        "newText": import_line,
                                                    }]
                                                }
                                            },
                                        })
                                    break
                # Suggest removing unused imports
                if "unused" in msg.lower() and "import" in msg.lower():
                    rng = diag.get("range", {})
                    start_line = rng.get("start", {}).get("line", 0)
                    end_line = rng.get("end", {}).get("line", start_line)
                    fix_key = ("remove-import", str(start_line), str(end_line), "", "")
                    if fix_key not in seen:
                        seen.add(fix_key)
                        actions.append({
                            "title": "Remove unused import",
                            "kind": "quickfix",
                            "isPreferred": True,
                            "diagnostics": [diag],
                            "edit": {
                                "changes": {
                                    uri: [{
                                        "range": {
                                            "start": {"line": start_line, "character": 0},
                                            "end": {"line": end_line + 1, "character": 0},
                                        },
                                        "newText": "",
                                    }]
                                }
                            },
                        })
            prog = self._parse_and_analyze(doc)
            if prog is not None:
                req_line, req_char = _range_start(params)
                for title in ["Add explicit variable type", "Insert inferred type annotation"]:
                    explicit = _build_add_explicit_type_action(
                        uri=uri,
                        doc=doc,
                        prog=prog,
                        line=req_line,
                        character=req_char,
                        title=title,
                        kind="refactor.rewrite",
                    )
                    if explicit is not None:
                        action, key = explicit
                        if key not in seen:
                            seen.add(key)
                            actions.append(action)

                req_rng = params.get("range", {})
                req_start = req_rng.get("start", {})
                req_end = req_rng.get("end", {})
                start_line = int(req_start.get("line", req_line))
                end_line = int(req_end.get("line", req_line))
                if end_line < start_line:
                    start_line, end_line = end_line, start_line
                for title, non_trivial in [
                    ("Add explicit types to variable declarations", False),
                    ("Add explicit types where inference is non-trivial", True),
                ]:
                    bulk = _build_bulk_add_explicit_types_action(
                        uri=uri,
                        doc=doc,
                        prog=prog,
                        start_line=start_line,
                        end_line=end_line,
                        title=title,
                        kind="refactor.rewrite",
                        non_trivial_only=non_trivial,
                    )
                    if bulk is not None:
                        action, key = bulk
                        if key not in seen:
                            seen.add(key)
                            actions.append(action)

                create_refactor = _build_create_union_match_action(
                    uri=uri,
                    doc=doc,
                    prog=prog,
                    line=req_line,
                    character=req_char,
                    title="Create match for union",
                    kind="refactor.rewrite",
                    wrap=False,
                )
                if create_refactor is not None:
                    action, key = create_refactor
                    if key not in seen:
                        seen.add(key)
                        actions.append(action)
                add_missing = _build_add_missing_union_arms_action(
                    uri=uri,
                    doc=doc,
                    prog=prog,
                    line=req_line,
                    character=req_char,
                    title="Add missing union arms",
                    kind="refactor.rewrite",
                )
                if add_missing is not None:
                    action, key = add_missing
                    if key not in seen:
                        seen.add(key)
                        actions.append(action)

                for diag in diagnostics:
                    drng = diag.get("range", {})
                    dstart = drng.get("start", {})
                    dline = int(dstart.get("line", req_line))
                    dchar = int(dstart.get("character", req_char))
                    explicit_quickfix = _build_add_explicit_type_action(
                        uri=uri,
                        doc=doc,
                        prog=prog,
                        line=dline,
                        character=dchar,
                        title="Add explicit variable type",
                        kind="quickfix",
                        diagnostic=diag,
                    )
                    if explicit_quickfix is not None:
                        action, key = explicit_quickfix
                        if key not in seen:
                            seen.add(key)
                            actions.append(action)
                    for title, wrap in [
                        ("Create match for union", False),
                        ("Wrap in exhaustive match", True),
                    ]:
                        quickfix = _build_create_union_match_action(
                            uri=uri,
                            doc=doc,
                            prog=prog,
                            line=dline,
                            character=dchar,
                            title=title,
                            kind="quickfix",
                            diagnostic=diag,
                            wrap=wrap,
                        )
                        if quickfix is None:
                            continue
                        action, key = quickfix
                        if key in seen:
                            continue
                        seen.add(key)
                        actions.append(action)
        return actions[:50]
    def _scan_workspace(self) -> None:
        for root in self.workspace_folders:
            if not root.exists():
                continue
            for path in root.rglob("*.arixa"):
                uri = path.resolve().as_uri()
                if uri in self.docs:
                    continue
                try:
                    text = path.read_text()
                except Exception:
                    continue
                fake_doc = TextDocument(uri=uri, text=text, version=0, language_id="astra")
                prog = self._parse_prog(fake_doc)
                self.symbol_index[uri] = _decl_symbols(prog, uri) if prog is not None else []
    def _on_open(self, params: dict[str, Any]) -> None:
        td = params.get("textDocument", {})
        uri = td.get("uri")
        if not uri:
            return
        version = int(td.get("version", 0))
        doc = TextDocument(uri=uri, text=td.get("text", ""), version=version, language_id=td.get("languageId", "astra"))
        self.docs[uri] = doc
        self._update_symbol_index(uri)
        self._update_module_graph(uri)
        filename = _uri_to_filename(uri)
        parse_diags = _parse_only_diagnostics(doc.text, filename, uri)
        self._publish_diagnostics(uri, version, parse_diags)
        self._schedule_semantic(uri, version)
    def _on_change(self, params: dict[str, Any]) -> None:
        tdoc = params.get("textDocument", {})
        uri = tdoc.get("uri")
        if not uri or uri not in self.docs:
            return
        doc = self.docs[uri]
        new_text = _apply_content_changes(doc.text, params.get("contentChanges", []))
        version = int(tdoc.get("version", doc.version + 1))
        doc.text = new_text
        doc.version = version
        self._update_symbol_index(uri)
        self._update_module_graph(uri)
        filename = _uri_to_filename(uri)
        parse_diags = _parse_only_diagnostics(doc.text, filename, uri)
        self._publish_diagnostics(uri, version, parse_diags)
        self._schedule_semantic(uri, version)
        for dep_uri in self.reverse_deps.get(uri, set()):
            dep_doc = self.docs.get(dep_uri)
            if dep_doc is not None:
                self._schedule_semantic(dep_uri, dep_doc.version)
    def _on_save(self, params: dict[str, Any]) -> None:
        uri = params.get("textDocument", {}).get("uri")
        if not uri or uri not in self.docs:
            return
        self._schedule_semantic(uri, self.docs[uri].version)
    def _on_close(self, params: dict[str, Any]) -> None:
        uri = params.get("textDocument", {}).get("uri")
        if not uri:
            return
        self.docs.pop(uri, None)
        self.pending.pop(uri, None)
        self._update_module_graph(uri)
        self.symbol_index.pop(uri, None)
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": []}})
    def _on_config_change(self, params: dict[str, Any]) -> None:
        settings = params.get("settings", {})
        astra_settings = settings.get("astra", settings)
        if isinstance(astra_settings, dict):
            self.settings["freestanding"] = bool(astra_settings.get("freestanding", self.settings["freestanding"]))
            overflow = astra_settings.get("overflow", self.settings["overflow"])
            if overflow in {"trap", "wrap", "debug"}:
                self.settings["overflow"] = overflow
            target = astra_settings.get("target", self.settings["target"])
            if target in {"py", "llvm", "native"}:
                self.settings["target"] = target
        for uri, doc in self.docs.items():
            self._schedule_semantic(uri, doc.version)
    def _respond(self, msg_id: Any, result: Any) -> None:
        if msg_id in self.canceled:
            self.canceled.discard(msg_id)
            return
        send({"jsonrpc": "2.0", "id": msg_id, "result": result})
    def _error(self, msg_id: Any, code: int, message: str) -> None:
        send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})
    def handle(self, msg: dict[str, Any]) -> bool:
        """Process one incoming LSP request/notification and emit responses.
        
        Parameters:
            msg: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
        method = msg.get("method")
        msg_id = msg.get("id")
        start = time.perf_counter()
        self.log.debug("req method=%s id=%s", method, msg_id)
        try:
            if method == "initialize":
                params = msg.get("params", {})
                folders = params.get("workspaceFolders") or []
                self.workspace_folders = []
                for f in folders:
                    uri = f.get("uri")
                    if uri and uri.startswith("file://"):
                        self.workspace_folders.append(Path(_uri_to_filename(uri)))
                root_uri = params.get("rootUri")
                if root_uri and root_uri.startswith("file://"):
                    self.workspace_folders.append(Path(_uri_to_filename(root_uri)))
                self._scan_workspace()
                self._respond(
                    msg_id,
                    {
                        "capabilities": {
                            "positionEncoding": "utf-16",
                            "textDocumentSync": {
                                "openClose": True,
                                "change": 2,
                                "save": {"includeText": False},
                            },
                            "hoverProvider": True,
                            "completionProvider": {
                                "resolveProvider": False,
                                "triggerCharacters": [".", "\"", "/"],
                            },
                            "definitionProvider": True,
                            "implementationProvider": True,
                            "semanticTokensProvider": {
                                "legend": self._semantic_tokens_legend(),
                                "full": True,
                            },
                            "inlayHintProvider": True,
                            "foldingRangeProvider": True,
                            "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
                            "referencesProvider": True,
                            "renameProvider": {"prepareProvider": True},
                            "linkedEditingRangeProvider": True,
                            "callHierarchyProvider": True,
                            "typeHierarchyProvider": True,
                            "documentSymbolProvider": True,
                            "workspaceSymbolProvider": True,
                            "documentFormattingProvider": True,
                            "codeActionProvider": True,
                            "executeCommandProvider": {
                                "commands": [
                                    "astra.formatDocument",
                                    "astra.rebuildProject",
                                    "astra.runTests",
                                ]
                            },
                        }
                    },
                )
                return True
            if method == "initialized":
                return True
            if method == "shutdown":
                self.shutting_down = True
                self._respond(msg_id, None)
                return True
            if method == "exit":
                self.exit_code = 0 if self.shutting_down else 1
                return False
            if method == "$/cancelRequest":
                rid = msg.get("params", {}).get("id")
                self.canceled.add(rid)
                return True
            if method == "workspace/didChangeConfiguration":
                self._on_config_change(msg.get("params", {}))
                return True
            if method == "textDocument/didOpen":
                self._on_open(msg.get("params", {}))
                return True
            if method == "textDocument/didChange":
                self._on_change(msg.get("params", {}))
                return True
            if method == "textDocument/didSave":
                self._on_save(msg.get("params", {}))
                return True
            if method == "textDocument/didClose":
                self._on_close(msg.get("params", {}))
                return True
            if method == "textDocument/hover":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._hover(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "textDocument/completion":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._completion(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "textDocument/definition":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                defs = self._definition_target(uri, int(pos.get("line", 0)), int(pos.get("character", 0)))
                self._respond(msg_id, defs[0] if len(defs) == 1 else defs or None)
                return True
            if method == "textDocument/implementation":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                impls = self._implementation_target(uri, int(pos.get("line", 0)), int(pos.get("character", 0)))
                self._respond(msg_id, impls[0] if len(impls) == 1 else impls or None)
                return True
            if method == "textDocument/semanticTokens/full":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                self._respond(msg_id, self._semantic_tokens(uri))
                return True
            if method == "textDocument/inlayHint":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                self._respond(msg_id, self._inlay_hints(uri, p.get("range", {})))
                return True
            if method == "textDocument/foldingRange":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                self._respond(msg_id, self._folding_ranges(uri))
                return True
            if method == "textDocument/signatureHelp":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._signature_help(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "textDocument/references":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                doc = self.docs.get(uri)
                name = _word_at(doc.text, int(pos.get("line", 0)), int(pos.get("character", 0))) if doc else ""
                include_decl = bool(p.get("context", {}).get("includeDeclaration", True))
                self._respond(msg_id, self._find_word_refs(uri, name, include_decl) if name else [])
                return True
            if method == "textDocument/rename":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                new_name = p.get("newName", "")
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
                    self._error(msg_id, -32602, "invalid rename target")
                    return True
                doc = self.docs.get(uri)
                old_name = _word_at(doc.text, int(pos.get("line", 0)), int(pos.get("character", 0))) if doc else ""
                if not old_name or old_name in KEYWORDS:
                    self._error(msg_id, -32602, "invalid rename target")
                    return True
                conflict = self._rename_conflict_reason(
                    uri,
                    int(pos.get("line", 0)),
                    int(pos.get("character", 0)),
                    old_name,
                    new_name,
                )
                if conflict:
                    self._error(msg_id, -32602, conflict)
                    return True
                refs = self._find_word_refs(uri, old_name, include_decl=True)
                changes: dict[str, list[dict[str, Any]]] = {}
                for r in refs:
                    changes.setdefault(r["uri"], []).append({"range": r["range"], "newText": new_name})
                self._respond(msg_id, {"changes": changes})
                return True
            if method == "textDocument/prepareRename":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                doc = self.docs.get(uri)
                if doc is None:
                    self._respond(msg_id, None)
                    return True
                name, start, end = _word_bounds(doc.text, int(pos.get("line", 0)), int(pos.get("character", 0)))
                if not name or name in KEYWORDS:
                    self._respond(msg_id, None)
                    return True
                line0 = int(pos.get("line", 0))
                self._respond(
                    msg_id,
                    {
                        "range": {
                            "start": {"line": line0, "character": start},
                            "end": {"line": line0, "character": end},
                        },
                        "placeholder": name,
                    },
                )
                return True
            if method == "workspace/executeCommand":
                self._respond(msg_id, self._execute_command(msg.get("params", {})))
                return True
            if method == "textDocument/prepareCallHierarchy":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._call_hierarchy(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "callHierarchy/incomingCalls":
                p = msg.get("params", {})
                self._respond(msg_id, self._incoming_calls(p.get("item", {})))
                return True
            if method == "callHierarchy/outgoingCalls":
                p = msg.get("params", {})
                self._respond(msg_id, self._outgoing_calls(p.get("item", {})))
                return True
            if method == "textDocument/prepareTypeHierarchy":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._type_hierarchy(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "typeHierarchy/supertypes":
                p = msg.get("params", {})
                self._respond(msg_id, self._supertypes(p.get("item", {})))
                return True
            if method == "typeHierarchy/subtypes":
                p = msg.get("params", {})
                self._respond(msg_id, self._subtypes(p.get("item", {})))
                return True
            if method == "textDocument/linkedEditingRange":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                pos = p.get("position", {})
                self._respond(msg_id, self._linked_editing_ranges(uri, int(pos.get("line", 0)), int(pos.get("character", 0))))
                return True
            if method == "textDocument/documentSymbol":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                self._respond(msg_id, self._document_symbols(uri))
                return True
            if method == "workspace/symbol":
                p = msg.get("params", {})
                self._respond(msg_id, self._workspace_symbols(p.get("query", "")))
                return True
            if method == "textDocument/formatting":
                p = msg.get("params", {})
                uri = p.get("textDocument", {}).get("uri", "")
                self._respond(msg_id, self._format_document(uri))
                return True
            if method == "textDocument/codeAction":
                p = msg.get("params", {})
                self._respond(msg_id, self._code_actions(p))
                return True
            if msg_id is not None:
                self._respond(msg_id, None)
            return True
        except Exception as err:
            self.log.exception("lsp request failed: %s", method)
            if msg_id is not None:
                self._error(msg_id, -32603, f"internal error: {err}")
            return True
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            self.log.debug("done method=%s id=%s %.2fms", method, msg_id, elapsed)
def _parse_and_analyze(text: str, uri: str):
    filename = _uri_to_filename(uri)
    try:
        prog = parse(text, filename=filename)
    except ParseError:
        return None
    try:
        analyze(prog, filename=filename)
    except SemanticError:
        pass
    return prog
def _parse_diagnostics(text: str, uri: str):
    filename = _uri_to_filename(uri)
    result = run_check_source(text, filename=filename, collect_errors=True)
    return [_diag_to_lsp(diag, uri, filename) for diag in result.diagnostics]
def _setup_logging(log_file: str | None, trace: bool) -> logging.Logger:
    logger = logging.getLogger("astlsp")
    logger.setLevel(logging.DEBUG if trace else logging.INFO)
    logger.handlers.clear()
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    else:
        logger.addHandler(logging.NullHandler())
    return logger
def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    ap = argparse.ArgumentParser(prog="astlsp")
    ap.add_argument("--log-file")
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--debounce-ms", type=int, default=200)
    ns = ap.parse_args([] if argv is None else argv)
    log = _setup_logging(ns.log_file, ns.trace)
    srv = LSPServer(log=log, debounce_ms=max(50, min(1000, ns.debounce_ms)))
    while True:
        srv._due_tasks()
        next_due = None
        if srv.pending:
            next_due = min(t.due_at for t in srv.pending.values())
        timeout = None if next_due is None else max(0.0, min(0.25, next_due - time.monotonic()))
        msg = _read_msg_with_timeout(timeout)
        if msg is None:
            break
        if msg is _NO_MSG:
            continue
        keep_going = srv.handle(msg)
        if not keep_going:
            break
    raise SystemExit(srv.exit_code)
if __name__ == "__main__":
    main()
