"""Language Server Protocol implementation for Astra editor integrations."""
from __future__ import annotations
import argparse
import json
import logging
import re
import select
import sys
import time
from dataclasses import dataclass, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from astra.ast import (
    ComptimeStmt,
    EnumDecl,
    ExternFnDecl,
    FnDecl,
    IteratorForStmt,
    IfStmt,
    ImportDecl,
    LetStmt,
    MatchStmt,
    Name,
    StructDecl,
    TypeAliasDecl,
    WhileStmt,
)
from astra.check import _parse_diag_lines, run_check_source
from astra.formatter import fmt, resolve_format_config
from astra.module_resolver import ModuleResolutionError, resolve_import_path
from astra.parser import ParseError, parse
from astra.semantic import BUILTIN_SIGS, SemanticError, analyze
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
            prog = parse(doc.text, filename=filename)
            
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
        
        prog = self._parse_prog(doc)
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
        prog = self._parse_prog(doc)
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
        try:
            prog = parse(doc.text, filename=filename)
        except ParseError:
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
        
        # Check built-in functions and types
        if symbol in BUILTIN_SIGS:
            sig = BUILTIN_SIGS[symbol]
            # For built-ins, we could return a documentation link or special marker
            results.append({
                "uri": "builtin://" + symbol,
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": len(symbol)},
                },
                "origin": "builtin",
                "detail": f"builtin {symbol}({', '.join(sig.args or [])}) {sig.ret}"
            })
        
        return results
    
    def _get_symbol_priority(self, kind: int, symbol: str) -> int:
        """Get priority for symbol ranking in go-to-definition results."""
        # Higher priority = more likely to be the target
        priority_map = {
            12: 100,  # Function
            23: 90,   # Struct
            10: 80,   # Enum
            5: 70,    # Type alias
            8: 60,    # Field
            6: 50,    # Variable
            2: 40,    # Import
        }
        return priority_map.get(kind, 0)
    
    def _implementation_target(self, uri: str, line0: int, col0: int) -> list[dict[str, Any]]:
        """Go to implementation - for trait implementations and function overrides."""
        doc = self.docs.get(uri)
        if doc is None:
            return []
        
        symbol = _word_at(doc.text, line0, col0)
        if not symbol:
            return []
        
        results = []
        
        # For now, return definition targets
        # In a full implementation, this would find trait implementations, overrides, etc.
        return self._definition_target(uri, line0, col0)
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
            return {"contents": {"kind": "markdown", "value": f"`builtin {symbol}({args}) {sig.ret}`"}}
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
        elif context["in_type_annotation"]:
            self._add_type_completions(doc, context, add)
        elif context["in_import"]:
            self._add_import_completions(doc, context, add)
        elif context["after_dot"]:
            self._add_member_completions(doc, context, add)
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
            "current_token": "",
            "function_name": "",
            "type_base": "",
            "object_type": None,
            "line": line,
            "col": col
        }
        
        # Function call context
        if '(' in prefix and not prefix.rstrip().endswith(')'):
            context["in_function_call"] = True
            # Extract function name
            func_match = re.search(r'(\w+)\s*\(\s*[^)]*$', prefix)
            if func_match:
                context["function_name"] = func_match.group(1)
        
        # Type annotation context  
        if ':' in prefix and ('fn' in prefix or 'let' in prefix or 'mut' in prefix):
            context["in_type_annotation"] = True
            type_match = re.search(r':\s*(\w*)$', prefix)
            if type_match:
                context["type_base"] = type_match.group(1)
        
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
        # Basic types
        basic_types = ["Int", "Float", "Bool", "String", "Char", "Void"]
        for t in basic_types:
            add(t, 5, f"primitive type {t}", priority=90)
        
        # Generic types
        generic_types = ["Vec", "Option", "Result", "HashMap", "HashSet"]
        for t in generic_types:
            add(t, 5, f"generic type {t}", insert_text=f"{t}<$1>", insert_format=2, priority=85)
        
        # Pointer and reference types
        pointer_types = ["Ptr", "Ref"]
        for t in pointer_types:
            add(t, 5, f"pointer/reference type {t}", insert_text=f"{t}<$1>", insert_format=2, priority=80)
        
        # User-defined types from workspace
        for syms in self.symbol_index.values():
            for s in syms:
                if s.kind in [23, 10]:  # Struct, Enum
                    add(s.name, 5, s.detail, priority=75)
    
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
        # This would require type inference to determine the object's type
        # For now, add common struct methods and fields
        
        # Common method names
        common_methods = ["len", "push", "pop", "get", "set", "clear", "is_empty", "clone"]
        for method in common_methods:
            add(method, 3, f"method {method}", insert_text=f"{method}($1)", insert_format=2, priority=85)
        
        # Common field names  
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
                            "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
                            "referencesProvider": True,
                            "renameProvider": True,
                            "documentSymbolProvider": True,
                            "workspaceSymbolProvider": True,
                            "documentFormattingProvider": True,
                            "codeActionProvider": True,
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
                refs = self._find_word_refs(uri, old_name, include_decl=True)
                changes: dict[str, list[dict[str, Any]]] = {}
                for r in refs:
                    changes.setdefault(r["uri"], []).append({"range": r["range"], "newText": new_name})
                self._respond(msg_id, {"changes": changes})
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
