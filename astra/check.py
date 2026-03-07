"""Static checking pipeline that reports normalized diagnostics for Astra sources."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from pathlib import Path

from astra.ast import (
    BoolLit,
    ComptimeStmt,
    ContinueStmt,
    BreakStmt,
    FnDecl,
    ForStmt,
    IfStmt,
    IndexExpr,
    LetStmt,
    Literal,
    MatchStmt,
    ReturnStmt,
    UnsafeStmt,
    WhileStmt,
)
from astra.comptime import ComptimeError, run_comptime
from astra.parser import ParseError, parse
from astra.semantic import BUILTIN_SIGS, SemanticError, analyze


@dataclass(frozen=True)
class DiagSpan:
    """Source span metadata used for diagnostics and editor features.

    This type is part of Astra's public compiler/tooling surface.
    """

    filename: str
    line: int
    col: int
    end_line: int
    end_col: int


@dataclass(frozen=True)
class DiagNote:
    """Data container used by check.

    This type is part of Astra's public compiler/tooling surface.
    """

    message: str
    span: DiagSpan | None = None
    kind: str = "note"


@dataclass(frozen=True)
class DiagSuggestion:
    """Suggested fix emitted with a diagnostic when available.

    This type is part of Astra's public compiler/tooling surface.
    """

    message: str
    span: DiagSpan | None = None
    replacement: str | None = None


@dataclass(frozen=True)
class Diagnostic:
    """Data container used by check.

    This type is part of Astra's public compiler/tooling surface.
    """

    phase: str
    code: str
    message: str
    span: DiagSpan
    notes: tuple[DiagNote, ...] = ()
    suggestions: tuple[DiagSuggestion, ...] = ()
    severity: str = "error"


@dataclass(frozen=True)
class CheckResult:
    """Structured result payload returned by compiler tooling helpers.

    This type is part of Astra's public compiler/tooling surface.
    """

    ok: bool
    diagnostics: tuple[Diagnostic, ...] = ()
    files_checked: tuple[str, ...] = ()


_TYPE_MISMATCH_RE = re.compile(r"^type mismatch (?:in|for) ([^:]+): expected (.+), got (.+)$")
_UNDEFINED_NAME_RE = re.compile(r"\bundefined name ([A-Za-z_][A-Za-z0-9_]*)\b")
_UNDEFINED_FN_RE = re.compile(r"\bundefined function ([A-Za-z_][A-Za-z0-9_]*)\b")
_EXPECTS_ARGS_RE = re.compile(r"\bexpects (\d+) args, got (\d+)\b")
_EXPECTS_ARGUMENT_RE = re.compile(r"\bexpects (\d+) arguments?\b")
_EXPECTS_AT_LEAST_RE = re.compile(r"\bexpects at least (.+)$")
_FREESTANDING_BUILTIN_RE = re.compile(r"\bfreestanding mode forbids builtin ([A-Za-z_][A-Za-z0-9_]*)\b")
_NO_MATCHING_IMPL_RE = re.compile(r"^no matching overload for ([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$")
_ENTRY_SIG_RE = re.compile(r"^(main|_start)\(\) (must not take parameters|must return Int)$")
_UNKNOWN_FIELD_RE = re.compile(r"\bunknown field ([A-Za-z_][A-Za-z0-9_]*)\b")
_MISSING_FIELD_RE = re.compile(r"\bmissing field ([A-Za-z_][A-Za-z0-9_]*)\b")
_EXPECTED_GOT_RE = re.compile(r"^expected (.+), got (.+)$")
_NON_EXHAUSTIVE_ENUM_RE = re.compile(
    r"^non-exhaustive match for enum ([A-Za-z_][A-Za-z0-9_]*)(?:;\s*missing variants:\s*(.+))?$"
)

# Cached source text used for richer snippet rendering in format_diagnostic().
_SOURCE_CACHE: dict[str, str] = {}


def run_check_source(
    source: str,
    *,
    filename: str = "<input>",
    freestanding: bool = False,
    overflow: str = "trap",
    collect_errors: bool = True,
) -> CheckResult:
    """Run parse/comptime/semantic checks for one source text input.

    Parameters:
        source: Astra source text to process.
        filename: Filename context used for diagnostics or path resolution.
        freestanding: Whether hosted-runtime features are disallowed.
        overflow: Integer overflow behavior mode requested by the caller.
        collect_errors: Input value used by this routine.

    Returns:
        Value described by the function return annotation.
    """

    _SOURCE_CACHE[filename] = source
    overflow_mode = "trap" if overflow == "debug" else overflow
    diagnostics: list[Diagnostic] = []
    prog = None

    try:
        prog = parse(source, filename=filename)
    except ParseError as err:
        diagnostics.extend(_parse_diag_lines(str(err), default_filename=filename))
        diagnostics = [
            _enrich_diagnostic(
                d,
                source_text=source,
                known_names=_known_names_from_source(source),
                known_call_arities=_known_call_arities_from_source(source),
            )
            for d in diagnostics
        ]
        return _result(diagnostics, [filename])

    known_names = _known_names_from_source(source) | _known_names_from_program(prog)
    known_call_arities = _merge_call_arity_maps(_known_call_arities_from_source(source), _known_call_arities_from_program(prog))

    try:
        run_comptime(prog, filename=filename, overflow_mode=overflow_mode)
    except ComptimeError as err:
        diagnostics.extend(_parse_diag_lines(str(err), default_filename=filename))
    except Exception as err:  # pragma: no cover - defensive fallback for deterministic output
        diagnostics.extend(_parse_diag_lines(str(err), default_filename=filename))

    try:
        analyze(prog, filename=filename, freestanding=freestanding, collect_errors=collect_errors)
    except SemanticError as err:
        diagnostics.extend(_parse_diag_lines(str(err), default_filename=filename))

    diagnostics.extend(_warning_diagnostics(prog, filename, source))
    diagnostics = [
        _enrich_diagnostic(d, source_text=source, known_names=known_names, known_call_arities=known_call_arities)
        for d in diagnostics
    ]
    return _result(diagnostics, [filename])


def run_check_paths(
    paths: list[str],
    *,
    freestanding: bool = False,
    overflow: str = "trap",
    collect_errors: bool = True,
) -> CheckResult:
    """Run compiler checks for a list of source file paths.

    Parameters:
        paths: Filesystem path input used by this routine.
        freestanding: Whether hosted-runtime features are disallowed.
        overflow: Integer overflow behavior mode requested by the caller.
        collect_errors: Input value used by this routine.

    Returns:
        Value described by the function return annotation.
    """

    diagnostics: list[Diagnostic] = []
    files: list[str] = []
    for path in paths:
        src = Path(path).read_text()
        _SOURCE_CACHE[path] = src
        res = run_check_source(
            src,
            filename=path,
            freestanding=freestanding,
            overflow=overflow,
            collect_errors=collect_errors,
        )
        files.extend(res.files_checked)
        diagnostics.extend(res.diagnostics)
    return _result(diagnostics, files)


def diagnostics_to_json_list(diags: list[Diagnostic] | tuple[Diagnostic, ...]) -> list[dict]:
    """Convert diagnostics to a JSON-serializable list of dictionaries.

    Parameters:
        diags: Input value used by this routine.

    Returns:
        Value described by the function return annotation.
    """

    out: list[dict] = []
    for d in diags:
        out.append(
            {
                "phase": d.phase,
                "code": d.code,
                "severity": d.severity,
                "message": d.message,
                "file": d.span.filename,
                "range": {
                    "start": {"line": d.span.line, "col": d.span.col},
                    "end": {"line": d.span.end_line, "col": d.span.end_col},
                },
                # Keep legacy shape for compatibility.
                "span": {
                    "filename": d.span.filename,
                    "line": d.span.line,
                    "col": d.span.col,
                    "end_line": d.span.end_line,
                    "end_col": d.span.end_col,
                },
                "suggestions": [
                    {
                        "message": s.message,
                        "replacement": s.replacement,
                        "file": None if s.span is None else s.span.filename,
                        "range": None
                        if s.span is None
                        else {
                            "start": {"line": s.span.line, "col": s.span.col},
                            "end": {"line": s.span.end_line, "col": s.span.end_col},
                        },
                    }
                    for s in d.suggestions
                ],
                "notes": [
                    {
                        "kind": n.kind,
                        "message": n.message,
                        "file": None if n.span is None else n.span.filename,
                        "range": None
                        if n.span is None
                        else {
                            "start": {"line": n.span.line, "col": n.span.col},
                            "end": {"line": n.span.end_line, "col": n.span.end_col},
                        },
                        # Keep legacy shape for compatibility.
                        "span": None
                        if n.span is None
                        else {
                            "filename": n.span.filename,
                            "line": n.span.line,
                            "col": n.span.col,
                            "end_line": n.span.end_line,
                            "end_col": n.span.end_col,
                        },
                    }
                    for n in d.notes
                ],
            }
        )
    return out


def format_diagnostic(d: Diagnostic) -> str:
    """Render one normalized diagnostic in human-readable text form.

    Parameters:
        d: Input value used by this routine.

    Returns:
        Value described by the function return annotation.
    """

    lines = [f"{d.severity}[{d.code}]: {d.message}"]
    lines.extend(_format_span_block(d.span, _primary_label_for(d), arrow="-->"))
    lines.append("   |")

    for s in d.suggestions:
        lines.append(f"   = help: {s.message}")

    for n in d.notes:
        if n.kind == "help":
            lines.append(f"   = help: {n.message}")
        else:
            lines.append(f"   = note: {n.message}")
        if n.span is not None:
            lines.extend(_format_span_block(n.span, "", arrow=":::"))

    return "\n".join(lines)


def _result(diagnostics: list[Diagnostic], files: list[str]) -> CheckResult:
    normalized = _dedupe_and_sort(diagnostics)
    ok = not any(d.severity == "error" for d in normalized)
    return CheckResult(ok=ok, diagnostics=tuple(normalized), files_checked=tuple(files))


def _dedupe_and_sort(diags: list[Diagnostic]) -> list[Diagnostic]:
    by_key: dict[tuple, Diagnostic] = {}
    for d in diags:
        key = (
            d.phase,
            d.code,
            d.message,
            d.severity,
            d.span.filename,
            d.span.line,
            d.span.col,
            d.span.end_line,
            d.span.end_col,
            tuple((n.kind, n.message, None if n.span is None else (n.span.filename, n.span.line, n.span.col, n.span.end_line, n.span.end_col)) for n in d.notes),
            tuple((s.message, s.replacement, None if s.span is None else (s.span.filename, s.span.line, s.span.col, s.span.end_line, s.span.end_col)) for s in d.suggestions),
        )
        if key not in by_key:
            by_key[key] = d

    order = {"error": 0, "warning": 1, "information": 2, "hint": 3}
    return sorted(
        by_key.values(),
        key=lambda d: (
            d.span.filename,
            d.span.line,
            d.span.col,
            order.get(d.severity, 9),
            d.phase,
            d.code,
            d.message,
        ),
    )


def _parse_diag_lines(text: str, *, default_filename: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parsed = _parse_one_diag_line(line, default_filename=default_filename)
        out.append(parsed)
    if out:
        return out
    fallback_span = DiagSpan(default_filename, 1, 1, 1, 2)
    return [
        Diagnostic(
            phase="SEM",
            code="E9999",
            message=text.strip() or "unknown compiler error",
            span=fallback_span,
        )
    ]


def _parse_one_diag_line(line: str, *, default_filename: str) -> Diagnostic:
    if " " not in line:
        span = DiagSpan(default_filename, 1, 1, 1, 2)
        return Diagnostic(phase="SEM", code="E9999", message=line, span=span)

    phase, rest = line.split(" ", 1)
    phase = phase.strip().upper()
    m = re.match(r"^(.*):(\d+):(\d+):\s+(.*)$", rest)
    if m is None:
        span = DiagSpan(default_filename, 1, 1, 1, 2)
        msg = rest.strip() or line
        return Diagnostic(phase=phase, code=_code_for(phase, msg), message=msg, span=span)

    filename = m.group(1) or default_filename
    ln = max(1, int(m.group(2)))
    col = max(1, int(m.group(3)))
    msg = m.group(4).strip()
    span = DiagSpan(filename, ln, col, ln, col + 1)
    return Diagnostic(phase=phase, code=_code_for(phase, msg), message=msg, span=span)


def _code_for(phase: str, message: str) -> str:
    m = message.lower()
    if phase == "LEX":
        if "unterminated string" in m:
            return "E0002"
        if "unterminated char" in m:
            return "E0003"
        if "unterminated block comment" in m:
            return "E0004"
        if "invalid numeric literal" in m:
            return "E0005"
        return "E0001"

    if phase == "PARSE":
        if m.startswith("expected ;"):
            return "E0301"
        if m.startswith("expected "):
            return "E0300"
        if "unexpected top-level token" in m or "unexpected atom" in m:
            return "E0002"
        if "unexpected eof" in m:
            return "E0003"
        if "for expects `for <ident> in <expr> { ... }`" in m:
            return "E0302"
        return "E0001"

    if phase == "SEM":
        if "type mismatch" in m:
            return "E0100"
        if "cannot implicitly convert" in m:
            return "E0100"
        if "`none` requires" in m:
            return "E0100"
        if "numeric operator" in m or "mixed int/float" in m or "operator " in m and "expects" in m:
            return "E0101"
        if _EXPECTS_ARGS_RE.search(m) or _EXPECTS_AT_LEAST_RE.search(m) or _EXPECTS_ARGUMENT_RE.search(m):
            return "E0102"
        if "must return" in m:
            return "E0103"
        if "cannot call non-function value" in m or "cannot call value of non-function type" in m:
            return "E0105"
        if "duplicate wildcard match arm" in m or "wildcard match arm must be last" in m:
            return "E0110"
        if "duplicate bool match arm" in m or "wildcard pattern `_` is only valid in match arms" in m:
            return "E0110"
        if "non-exhaustive match" in m:
            return "E0111"
        if "cannot resolve import" in m:
            return "E0202"
        if "undefined name" in m:
            return "E0200"
        if "undefined function" in m:
            return "E0201"
        if "unknown field" in m:
            return "E0203"
        if "missing field" in m:
            return "E0204"
        if "cannot assign to immutable binding" in m:
            return "E0104"
        if "assignment to undefined name" in m:
            return "E0200"
        if "borrow" in m:
            return "E0400"
        if "use-after-move" in m:
            return "E0401"
        if "use-after-free" in m:
            return "E0402"
        if "owned allocation(s) not released" in m:
            return "E0403"
        if "this cast requires unsafe context" in m or "requires unsafe context" in m:
            return "E0500"
        if "freestanding mode forbids builtin" in m:
            return "E0501"
        if "missing main()" in m or "missing _start()" in m:
            return "E0600"
        if _ENTRY_SIG_RE.match(message):
            return "E0600"
        if "outside loop" in m:
            return "E0302"
        if "integer overflow" in m:
            return "E0701"
        if "cannot resolve import" in m:
            return "E0202"
        if "comptime:" in m:
            return "E0700"
        return "E9999"

    if phase == "LINT":
        if "unreachable" in m:
            return "W0001"
        if "unused variable" in m:
            return "W0002"
        if "dead code" in m:
            return "W0102"
        if "shadows a previous declaration" in m:
            return "W0104"
        if "array index is negative" in m or "array index is very large" in m:
            return "W0101"
        if "column-first traversal of row-major 2D array" in m:
            return "W0201"
        if "repeated property lookup" in m:
            return "W0202"
        if "large struct by-value copy" in m:
            return "W0203"
        if "needless temporary allocation" in m:
            return "W0204"
        if "repeated bounds checks" in m:
            return "W0205"
        if "iteration by value instead of reference" in m:
            return "W0206"
        if "possible null dereference" in m:
            return "W0301"
        if "ignored fallible operation result" in m:
            return "W0302"
        if "non-exhaustive wildcard reliance" in m:
            return "W0303"
        if "reference to temporary" in m:
            return "W0304"
        return "W9999"

    return "E9999"


def _enrich_diagnostic(
    d: Diagnostic,
    *,
    source_text: str | None,
    known_names: set[str],
    known_call_arities: dict[str, set[int]],
) -> Diagnostic:
    raw_message = d.message
    span = _refine_primary_span(raw_message, d.span, source_text)
    message = _friendly_message_for(raw_message, d.code)
    notes = list(d.notes)
    suggestions = list(d.suggestions)

    notes.extend(_notes_for(raw_message))
    notes.extend(_related_notes_for(raw_message, span, source_text))
    suggestions.extend(_suggestions_for(raw_message, span, source_text, known_names, known_call_arities))

    notes = _dedupe_notes(notes)
    suggestions = _dedupe_suggestions(suggestions)

    return replace(d, message=message, span=span, notes=tuple(notes), suggestions=tuple(suggestions))


def _friendly_message_for(message: str, code: str) -> str:
    mismatch = _TYPE_MISMATCH_RE.match(message)
    if mismatch is not None:
        context, expected, got = mismatch.groups()
        if context == "return":
            return f"expected `{expected}` but found `{got}` in return value"
        if context.startswith("assignment"):
            return f"cannot assign `{got}` to a value of type `{expected}`"
        if context.startswith("function call"):
            return f"cannot pass `{got}` to parameter expecting `{expected}`"
        if context.startswith("binary operation"):
            return f"cannot perform operation on `{got}` and `{expected}` types"
        return f"expected `{expected}` but found `{got}`"

    if message.startswith("expected ;"):
        return "expected `;`"

    expected_got = _EXPECTED_GOT_RE.match(message)
    if expected_got is not None:
        expected, got = expected_got.groups()
        if code in {"E0300", "E0301", "E0002", "E0001"}:
            return f"expected `{expected}`"
        return f"expected `{expected}` but found `{got}`"

    fn_m = _UNDEFINED_FN_RE.search(message)
    if fn_m is not None:
        return f"cannot find function `{fn_m.group(1)}`"

    name_m = _UNDEFINED_NAME_RE.search(message)
    if name_m is not None:
        return f"cannot find value `{name_m.group(1)}` in this scope"

    fs_m = _FREESTANDING_BUILTIN_RE.search(message)
    if fs_m is not None:
        return f"`{fs_m.group(1)}` is not available in freestanding mode"

    if message.startswith("non-exhaustive match for Bool"):
        return "non-exhaustive `match` for `Bool`"
    non_exhaustive_enum = _NON_EXHAUSTIVE_ENUM_RE.match(message)
    if non_exhaustive_enum is not None:
        enum_name, missing_variants = non_exhaustive_enum.groups()
        if missing_variants:
            return f"non-exhaustive `match` for enum `{enum_name}` (missing: {missing_variants})"
        return f"non-exhaustive `match` for enum `{enum_name}`"

    no_impl = _NO_MATCHING_IMPL_RE.match(message)
    if no_impl is not None:
        name, args = no_impl.groups()
        arg_count = 0 if not args.strip() else len([p for p in args.split(",") if p.strip()])
        return f"no overload of `{name}` matches {arg_count} argument(s)"

    # Enhanced error messages for common issues
    if "cannot implicitly convert" in message:
        return message.replace("cannot implicitly convert", "cannot implicitly convert") + "; use explicit cast with `as`"
    
    if "unsupported cast from" in message:
        return message + "; this cast type is not supported in Astra"
    
    if "borrow" in message and "cannot" in message:
        if "mutably borrow" in message:
            return "cannot create mutable reference while other references exist"
        if "immutably borrow" in message:
            return "cannot create immutable reference while mutable reference exists"
        return "borrow checker error: " + message.replace("cannot", "")
    
    if "use-after-" in message:
        if "move" in message:
            return "value was moved and cannot be used again"
        if "free" in message:
            return "value was freed and cannot be used again"
    
    if "integer overflow" in message:
        return "integer overflow detected; consider using a wider type or checking bounds"
    
    if "division by zero" in message:
        return "division by zero; add a check or use conditional logic"
    
    if "modulo by zero" in message:
        return "modulo by zero; add a check or use conditional logic"
    
    if "negative shift count" in message:
        return "shift count cannot be negative; use absolute value or check sign"
    
    if "shift count" in message and "out of range" in message:
        return "shift count exceeds bit width; use smaller shift or wider type"

    if message.startswith("break used outside loop"):
        return "`break` can only be used inside a loop"
    if message.startswith("continue used outside loop"):
        return "`continue` can only be used inside a loop"

    if message.startswith("cannot assign to immutable binding "):
        name = message.removeprefix("cannot assign to immutable binding ").strip()
        return f"cannot assign to immutable binding `{name}`"

    entry_sig = _ENTRY_SIG_RE.match(message)
    if entry_sig is not None:
        name, requirement = entry_sig.groups()
        if requirement == "must not take parameters":
            return f"`{name}` must not take parameters"
        if requirement == "must return Int":
            return "`main` must return `Int`"
        return f"`{name}` has an invalid entrypoint declaration"

    field_m = _UNKNOWN_FIELD_RE.search(message)
    if field_m is not None:
        return f"unknown field `{field_m.group(1)}`"
    missing_field_m = _MISSING_FIELD_RE.search(message)
    if missing_field_m is not None:
        return f"missing field `{missing_field_m.group(1)}`"

    if code == "E0103" and "must return" in message:
        return message

    return message


def _notes_for(message: str) -> list[DiagNote]:
    out: list[DiagNote] = []
    mismatch = _TYPE_MISMATCH_RE.match(message)
    if mismatch is not None:
        context, expected, got = mismatch.groups()
        out.append(DiagNote(message=f"context: {context}"))
        out.append(DiagNote(message=f"expected: {expected}"))
        out.append(DiagNote(message=f"found: {got}"))
    if "cannot assign to immutable binding" in message:
        out.append(DiagNote(message="in Astra, bindings are immutable unless declared with `mut`"))
    if "mixed int/float" in message:
        out.append(DiagNote(message="Astra does not perform implicit numeric widening between Int and Float"))
    if "cannot resolve import" in message:
        out.append(DiagNote(message="imports are path-validated; ensure the module file exists and matches the import path"))
    if "must return" in message:
        out.append(DiagNote(message="every control-flow path in this function must produce a return value"))
    if "integer overflow" in message:
        out.append(DiagNote(message="overflow checks are enabled in debug-like modes to catch silent wraparound"))
    return out


def _related_notes_for(message: str, span: DiagSpan, source_text: str | None) -> list[DiagNote]:
    if source_text is None:
        return []
    lines = source_text.splitlines()
    if span.line < 1 or span.line > len(lines):
        return []
    related: list[DiagNote] = []

    if message.startswith("type mismatch for assignment"):
        cur = lines[span.line - 1]
        assign = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", cur)
        if assign is not None:
            name = assign.group(1)
            decl_span = _find_binding_declaration_span(lines, span.filename, span.line, name)
            if decl_span is not None:
                related.append(DiagNote(message=f"variable `{name}` declared with this type", span=decl_span))

    if message.startswith("type mismatch for return"):
        ret_span = _find_enclosing_fn_return_span(lines, span.filename, span.line)
        if ret_span is not None:
            related.append(DiagNote(message="function return type declared here", span=ret_span))

    borrow_name = _borrow_related_name(message)
    if borrow_name is not None:
        decl_span = _find_binding_declaration_span(lines, span.filename, span.line, borrow_name)
        if decl_span is not None:
            related.append(DiagNote(message=f"`{borrow_name}` is declared here", span=decl_span))

    return related


def _suggestions_for(
    message: str,
    span: DiagSpan,
    source_text: str | None,
    known_names: set[str],
    known_call_arities: dict[str, set[int]],
) -> list[DiagSuggestion]:
    out: list[DiagSuggestion] = []
    m = message.lower()

    if message.startswith("expected ;"):
        semicolon_span = _line_end_span(span, source_text)
        out.append(DiagSuggestion(message="add `;` at the end of the statement", span=semicolon_span, replacement=";"))

    if message.startswith("type mismatch"):
        out.append(DiagSuggestion(message="convert the value to the expected type, or update the declared type"))

    if "mixed int/float" in m:
        out.append(DiagSuggestion(message="use an explicit cast with `as`, for example `x as Float` or `y as Int`"))

    if "cannot implicitly convert" in m:
        out.append(DiagSuggestion(message="use explicit cast with `as`, for example `value as TargetType`"))

    if "unsupported cast from" in m:
        out.append(DiagSuggestion(message="check if the cast is supported or use intermediate conversions"))

    if "borrow" in m and "cannot" in m:
        if "mutably borrow" in m:
            out.append(DiagSuggestion(message="reduce the scope of existing references or use interior mutability"))
        if "immutably borrow" in m:
            out.append(DiagSuggestion(message="wait for mutable references to go out of scope or clone the value"))

    if "use-after-" in m:
        if "move" in m:
            out.append(DiagSuggestion(message="clone the value before moving if you need to use it later"))
        if "free" in m:
            out.append(DiagSuggestion(message="don't free the value if you need to use it again"))

    if "integer overflow" in m:
        out.append(DiagSuggestion(message="use a wider integer type, clamp the value, or build with `--overflow wrap` if wrapping is intended"))

    if "division by zero" in m or "modulo by zero" in m:
        out.append(DiagSuggestion(message="add a zero check before the operation, e.g., `if divisor != 0 { ... }`"))

    if "negative shift count" in m:
        out.append(DiagSuggestion(message="use `abs(shift_count)` or check if the value is negative before shifting"))

    if "shift count" in m and "out of range" in m:
        out.append(DiagSuggestion(message="use a wider integer type or mask the shift count"))

    if "missing main()" in m:
        out.append(DiagSuggestion(message="add `fn main() Int { ... }` as the program entrypoint"))

    if "missing _start()" in m:
        out.append(DiagSuggestion(message="add `fn _start() { ... }` for freestanding executable builds"))

    entry_sig = _ENTRY_SIG_RE.match(message)
    if entry_sig is not None:
        name, requirement = entry_sig.groups()
        if requirement == "must return Int":
            out.append(DiagSuggestion(message=f"change `{name}` to return `Int`"))
        elif requirement == "must not take parameters":
            out.append(DiagSuggestion(message=f"remove all parameters from `{name}`"))
        else:
            out.append(DiagSuggestion(message=f"entrypoints must be plain functions"))

    if "break used outside loop" in m:
        out.append(DiagSuggestion(message="move `break` inside a `while` or `for` loop"))

    if "continue used outside loop" in m:
        out.append(DiagSuggestion(message="move `continue` inside a `while` or `for` loop"))

    if "cannot assign to immutable binding" in m:
        out.append(DiagSuggestion(message="declare the binding with `mut` if it needs to be reassigned"))

    fn_m = _UNDEFINED_FN_RE.search(message)
    if fn_m is not None:
        name = fn_m.group(1)
        replacement = _closest_name(name, known_names)
        if replacement is not None:
            out.append(
                DiagSuggestion(
                    message=f"did you mean `{replacement}`?",
                    span=_name_span(span, name, source_text),
                    replacement=replacement,
                )
            )

    name_m = _UNDEFINED_NAME_RE.search(message)
    if name_m is not None:
        name = name_m.group(1)
        replacement = _closest_name(name, known_names)
        if replacement is not None:
            out.append(
                DiagSuggestion(
                    message=f"did you mean `{replacement}`?",
                    span=_name_span(span, name, source_text),
                    replacement=replacement,
                )
            )

    if "duplicate wildcard match arm" in m:
        out.append(DiagSuggestion(message="remove the duplicate `_ => ...` match arm"))

    if "integer overflow" in m:
        out.append(DiagSuggestion(message="use a wider integer type, clamp the value, or build with `--overflow wrap` if wrapping is intended"))

    if "requires unsafe context" in m:
        out.append(DiagSuggestion(message="wrap this operation in an `unsafe { ... }` block after validating the safety requirements"))

    return out


def _find_binding_declaration_span(lines: list[str], filename: str, start_line: int, name: str) -> DiagSpan | None:
    decl_re = re.compile(rf"\b(?:mut\s+)?({re.escape(name)})\s*(?::[^=;]+)?=")
    for idx in range(min(start_line - 2, len(lines) - 1), -1, -1):
        m = decl_re.search(lines[idx])
        if m is not None:
            return DiagSpan(filename, idx + 1, m.start(1) + 1, idx + 1, m.end(1) + 1)
    return None


def _borrow_related_name(message: str) -> str | None:
    for pat in [
        r"cannot (?:immutably|mutably) borrow ([A-Za-z_][A-Za-z0-9_]*)\b",
        r"cannot use ([A-Za-z_][A-Za-z0-9_]*) while",
        r"cannot mutate ([A-Za-z_][A-Za-z0-9_]*) while",
        r"use-after-(?:move|free) of ([A-Za-z_][A-Za-z0-9_]*)\b",
    ]:
        m = re.search(pat, message)
        if m is not None:
            return m.group(1)
    return None


def _find_binding_declaration_span(lines: list[str], filename: str, start_line: int, name: str) -> DiagSpan | None:
    decl_re = re.compile(rf"\b(?:mut\s+)?({re.escape(name)})\s*(?::[^=;]+)?=")
    for idx in range(min(start_line - 2, len(lines) - 1), -1, -1):
        m = decl_re.search(lines[idx])
        if m is None:
            continue
        c1 = m.start(1) + 1
        return DiagSpan(filename, idx + 1, c1, idx + 1, c1 + len(name))
    return None


def _find_enclosing_fn_return_span(lines: list[str], filename: str, start_line: int) -> DiagSpan | None:
    for idx in range(min(start_line - 1, len(lines) - 1), -1, -1):
        line = lines[idx]
        if "fn " not in line:
            continue
        # Look for return type after ) in current syntax: fn name(params) ReturnType {
        fn_match = re.search(r"fn\s+\w+\s*\([^)]*\)\s+([A-Za-z_][A-Za-z0-9_<>&\[\], ]*)\s*{", line)
        if fn_match is None:
            continue
        typ = fn_match.group(1).strip()
        if not typ:
            continue
        c1 = fn_match.start(1) + 1
        c2 = c1 + max(1, len(typ))
        return DiagSpan(filename, idx + 1, c1, idx + 1, c2)
    return None


def _refine_primary_span(message: str, span: DiagSpan, source_text: str | None) -> DiagSpan:
    if source_text is None:
        return span

    if message.startswith("expected ;"):
        return _line_end_span(span, source_text)

    fn_m = _UNDEFINED_FN_RE.search(message)
    if fn_m is not None:
        name_span = _name_span(span, fn_m.group(1), source_text)
        if name_span is not None:
            return name_span

    name_m = _UNDEFINED_NAME_RE.search(message)
    if name_m is not None:
        name_span = _name_span(span, name_m.group(1), source_text)
        if name_span is not None:
            return name_span

    fs_m = _FREESTANDING_BUILTIN_RE.search(message)
    if fs_m is not None:
        name_span = _name_span(span, fs_m.group(1), source_text)
        if name_span is not None:
            return name_span

    assign_m = re.search(r"cannot assign to immutable binding ([A-Za-z_][A-Za-z0-9_]*)", message)
    if assign_m is not None:
        name_span = _name_span(span, assign_m.group(1), source_text)
        if name_span is not None:
            return name_span

    return span


def _format_span_block(span: DiagSpan, label: str, *, arrow: str, include_leading_divider: bool = True) -> list[str]:
    src = _source_line_for_span(span)
    line_txt = str(span.line)
    width = max(2, len(line_txt))
    caret_len = max(1, span.end_col - span.col) if span.end_line == span.line else 1
    caret = " " * max(0, span.col - 1) + "^" * caret_len
    if label:
        caret += f" {label}"

    out = [f"  {arrow} {span.filename}:{span.line}:{span.col}"]
    if include_leading_divider:
        out.append("   |")
    out.append(f"{line_txt.rjust(width)} | {src}")
    out.append(f"{' ' * width} | {caret}")
    return out


def _source_line_for_span(span: DiagSpan) -> str:
    if span.filename in _SOURCE_CACHE:
        lines = _SOURCE_CACHE[span.filename].splitlines()
        if 1 <= span.line <= len(lines):
            return lines[span.line - 1]
    try:
        lines = Path(span.filename).read_text().splitlines()
    except OSError:
        return "<source unavailable>"
    if 1 <= span.line <= len(lines):
        return lines[span.line - 1]
    return "<source unavailable>"


def _primary_label_for(d: Diagnostic) -> str:
    if d.code == "E0100":
        for n in d.notes:
            if n.message.startswith("expected: "):
                return n.message
        return "type mismatch"
    if d.code == "E0301":
        return "missing `;`"
    if d.code in {"E0200", "E0201"}:
        return "unknown identifier"
    if d.code == "E0501":
        return "hosted API in freestanding mode"
    return ""


def _dedupe_notes(notes: list[DiagNote]) -> list[DiagNote]:
    out: list[DiagNote] = []
    seen: set[tuple] = set()
    for n in notes:
        key = (
            n.kind,
            n.message,
            None if n.span is None else (n.span.filename, n.span.line, n.span.col, n.span.end_line, n.span.end_col),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _dedupe_suggestions(suggestions: list[DiagSuggestion]) -> list[DiagSuggestion]:
    out: list[DiagSuggestion] = []
    seen: set[tuple] = set()
    for s in suggestions:
        key = (
            s.message,
            s.replacement,
            None if s.span is None else (s.span.filename, s.span.line, s.span.col, s.span.end_line, s.span.end_col),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _line_end_span(span: DiagSpan, source_text: str | None) -> DiagSpan:
    if source_text is None:
        return span
    lines = source_text.splitlines()
    if not (1 <= span.line <= len(lines)):
        return span
    end = len(lines[span.line - 1]) + 1
    return DiagSpan(span.filename, span.line, end, span.line, end + 1)


def _name_span(span: DiagSpan, name: str, source_text: str | None) -> DiagSpan | None:
    if source_text is None:
        return None
    lines = source_text.splitlines()
    if not (1 <= span.line <= len(lines)):
        return None
    line = lines[span.line - 1]
    # Prefer occurrence near reported column.
    best_start = -1
    best_dist = 10**9
    for m in re.finditer(rf"\b{re.escape(name)}\b", line):
        start = m.start() + 1
        dist = abs(start - span.col)
        if dist < best_dist:
            best_dist = dist
            best_start = start
    if best_start < 1:
        return None
    return DiagSpan(span.filename, span.line, best_start, span.line, best_start + len(name))


def _known_names_from_source(source: str) -> set[str]:
    names = {m.group(0) for m in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", source)}
    names |= {k.removeprefix("__") for k in BUILTIN_SIGS.keys()}
    names |= {"print", "len", "main", "alloc", "free", "spawn", "join", "read_file", "write_file"}
    return names


def _known_call_arities_from_source(source: str) -> dict[str, set[int]]:
    out = {k.removeprefix("__"): set() for k in BUILTIN_SIGS.keys()}
    for name, sig in BUILTIN_SIGS.items():
        base = name.removeprefix("__")
        if sig.args is not None:
            out.setdefault(base, set()).add(len(sig.args))
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s+([A-Za-z_][A-Za-z0-9_<>&\[\], ]*)\s*{", source):
        name = m.group(1)
        params = m.group(2).strip()
        count = 0 if not params else len([p for p in params.split(",") if p.strip()])
        out.setdefault(name, set()).add(count)
    return out


def _known_names_from_program(prog) -> set[str]:
    names: set[str] = set()
    for item in getattr(prog, "items", []):
        item_name = getattr(item, "name", None)
        if isinstance(item_name, str):
            names.add(item_name)
        alias = getattr(item, "alias", None)
        if isinstance(alias, str):
            names.add(alias)
        if isinstance(item, FnDecl):
            for pname, _ in item.params:
                names.add(pname)
            _collect_stmt_decl_names(item.body, names)
    return names


def _known_call_arities_from_program(prog) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for item in getattr(prog, "items", []):
        if isinstance(item, FnDecl):
            out.setdefault(item.name, set()).add(len(item.params))
    return out


def _merge_call_arity_maps(*maps: dict[str, set[int]]) -> dict[str, set[int]]:
    merged: dict[str, set[int]] = {}
    for mapping in maps:
        for name, arities in mapping.items():
            merged.setdefault(name, set()).update(arities)
    return merged


def _collect_stmt_decl_names(body: list, out: set[str]) -> None:
    for st in body:
        if isinstance(st, LetStmt):
            out.add(st.name)
        if isinstance(st, ForStmt):
            out.add(st.var)
            _collect_stmt_decl_names(st.body, out)
        elif isinstance(st, IfStmt):
            _collect_stmt_decl_names(st.then_body, out)
            _collect_stmt_decl_names(st.else_body, out)
        elif isinstance(st, WhileStmt):
            _collect_stmt_decl_names(st.body, out)
        elif isinstance(st, MatchStmt):
            for _, arm in st.arms:
                _collect_stmt_decl_names(arm, out)
        elif isinstance(st, (ComptimeStmt, UnsafeStmt)):
            _collect_stmt_decl_names(st.body, out)


def _closest_name(name: str, known_names: set[str]) -> str | None:
    best: tuple[int, str] | None = None
    for candidate in known_names:
        if not candidate or candidate == name:
            continue
        dist = _levenshtein(name, candidate)
        if best is None or dist < best[0] or (dist == best[0] and candidate < best[1]):
            best = (dist, candidate)
    if best is None:
        return None
    max_dist = 2 if len(name) <= 6 else max(2, len(name) // 3)
    if best[0] <= max_dist:
        return best[1]
    return None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _warning_diagnostics(prog, filename: str, source_text: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for item in getattr(prog, "items", []):
        if not isinstance(item, FnDecl):
            continue
        out.extend(_unreachable_warnings(item.body, filename))
        out.extend(_unused_variable_warnings(item, filename, source_text))
        out.extend(_dead_code_warnings(item.body, filename))
        out.extend(_shadowing_warnings(item.body, filename, source_text))
        out.extend(_constant_bounds_warnings(item.body, filename))
        out.extend(_performance_warnings(item.body, filename, source_text))
    return out


def _unreachable_warnings(body: list, filename: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []

    terminated = False
    for st in body:
        if terminated:
            span = DiagSpan(filename, max(1, getattr(st, "line", 1)), max(1, getattr(st, "col", 1)), max(1, getattr(st, "line", 1)), max(2, getattr(st, "col", 1) + 1))
            out.append(
                Diagnostic(
                    phase="LINT",
                    code="W0001",
                    message="unreachable statement",
                    span=span,
                    severity="warning",
                    suggestions=(DiagSuggestion(message="remove the statement or move it before the terminating control-flow statement"),),
                )
            )

        for nested in _nested_blocks(st):
            out.extend(_unreachable_warnings(nested, filename))

        if _stmt_terminates(st):
            terminated = True

    return out


def _nested_blocks(st) -> list[list]:
    if isinstance(st, IfStmt):
        return [st.then_body, st.else_body]
    if isinstance(st, WhileStmt):
        return [st.body]
    if isinstance(st, ForStmt):
        return [st.body]
    if isinstance(st, MatchStmt):
        return [arm for _, arm in st.arms]
    if isinstance(st, (ComptimeStmt, UnsafeStmt)):
        return [st.body]
    return []


def _stmt_terminates(st) -> bool:
    if isinstance(st, (ReturnStmt, BreakStmt, ContinueStmt)):
        return True
    if isinstance(st, IfStmt):
        return bool(st.then_body) and bool(st.else_body) and _block_terminates(st.then_body) and _block_terminates(st.else_body)
    if isinstance(st, MatchStmt):
        return bool(st.arms) and all(_block_terminates(arm) for _, arm in st.arms)
    if isinstance(st, (ComptimeStmt, UnsafeStmt)):
        return _block_terminates(st.body)
    return False


def _block_terminates(body: list) -> bool:
    if not body:
        return False
    return _stmt_terminates(body[-1])


def _unused_variable_warnings(fn: FnDecl, filename: str, source_text: str) -> list[Diagnostic]:
    bindings: list[tuple[str, DiagSpan]] = []

    def walk(body: list) -> None:
        for st in body:
            if isinstance(st, LetStmt):
                span = DiagSpan(filename, max(1, st.line), max(1, st.col), max(1, st.line), max(2, st.col + len(st.name)))
                bindings.append((st.name, span))
            for nested in _nested_blocks(st):
                walk(nested)

    walk(fn.body)

    out: list[Diagnostic] = []
    for name, span in bindings:
        if name.startswith("_"):
            continue
        # Conservative source-level reference count: declaration + uses.
        count = len(re.findall(rf"\b{re.escape(name)}\b", source_text))
        if count <= 1:
            out.append(
                Diagnostic(
                    phase="LINT",
                    code="W0002",
                    message=f"unused variable `{name}`",
                    span=span,
                    severity="warning",
                    suggestions=(DiagSuggestion(message=f"remove `{name}`, or rename it to `_{name}` to mark it intentionally unused"),),
                )
            )
    return out


def _dead_code_warnings(body: list, filename: str) -> list[Diagnostic]:
    """Detect dead code that will never be executed."""
    out: list[Diagnostic] = []
    
    def check_condition(expr) -> bool:
        """Check if a condition is always true or false."""
        if isinstance(expr, BoolLit):
            return True
        # Add more constant folding checks here
        return False
    
    def walk(stmts: list) -> None:
        for st in stmts:
            if isinstance(st, IfStmt):
                if check_condition(st.cond):
                    span = DiagSpan(filename, max(1, getattr(st, "line", 1)), max(1, getattr(st, "col", 1)), max(1, getattr(st, "line", 1)), max(2, getattr(st, "col", 1) + 1))
                    out.append(
                        Diagnostic(
                            phase="LINT",
                            code="W0102",
                            message="dead code detected: condition is always true or false",
                            span=span,
                            severity="warning",
                            suggestions=(DiagSuggestion(message="remove the dead code or fix the condition"),),
                        )
                    )
                for nested in _nested_blocks(st):
                    walk(nested)
            elif isinstance(st, WhileStmt):
                if check_condition(st.cond):
                    span = DiagSpan(filename, max(1, getattr(st, "line", 1)), max(1, getattr(st, "col", 1)), max(1, getattr(st, "line", 1)), max(2, getattr(st, "col", 1) + 1))
                    out.append(
                        Diagnostic(
                            phase="LINT",
                            code="W0102",
                            message="dead code detected: loop condition is always true or false",
                            span=span,
                            severity="warning",
                            suggestions=(DiagSuggestion(message="remove the dead code or fix the condition"),),
                        )
                    )
                walk(st.body)
            else:
                for nested in _nested_blocks(st):
                    walk(nested)
    
    walk(body)
    return out


def _shadowing_warnings(body: list, filename: str, source_text: str) -> list[Diagnostic]:
    """Detect variable shadowing that can cause confusion."""
    out: list[Diagnostic] = []
    declared_vars: dict[str, DiagSpan] = {}
    
    def walk(stmts: list, scope_level: int = 0) -> None:
        nonlocal declared_vars
        current_scope = {}
        
        for st in stmts:
            if isinstance(st, LetStmt):
                if st.name in declared_vars:
                    original_span = declared_vars[st.name]
                    span = DiagSpan(filename, max(1, st.line), max(1, st.col), max(1, st.line), max(2, st.col + len(st.name)))
                    out.append(
                        Diagnostic(
                            phase="LINT",
                            code="W0104",
                            message=f"variable `{st.name}` shadows a previous declaration",
                            span=span,
                            severity="warning",
                            notes=(
                                DiagNote(message=f"previous declaration of `{st.name}`", span=original_span),
                            ),
                            suggestions=(DiagSuggestion(message=f"rename `{st.name}` to avoid shadowing"),),
                        )
                    )
                current_scope[st.name] = DiagSpan(filename, max(1, st.line), max(1, st.col), max(1, st.line), max(2, st.col + len(st.name)))
            
            for nested in _nested_blocks(st):
                walk(nested, scope_level + 1)
        
        # Merge current scope back to parent
        declared_vars.update(current_scope)
    
    walk(body)
    return out


def _constant_bounds_warnings(body: list, filename: str) -> list[Diagnostic]:
    """Detect constant array bounds violations at compile time."""
    out: list[Diagnostic] = []
    
    def check_array_access(expr) -> None:
        if isinstance(expr, IndexExpr):
            # Check if index is a constant literal
            if isinstance(expr.index, Literal) and isinstance(expr.index.value, int):
                if expr.index.value < 0:
                    span = DiagSpan(filename, max(1, getattr(expr.index, "line", 1)), max(1, getattr(expr.index, "col", 1)), max(1, getattr(expr.index, "line", 1)), max(2, getattr(expr.index, "col", 1) + 1))
                    out.append(
                        Diagnostic(
                            phase="LINT",
                            code="W0101",
                            message="array index is negative and will always cause bounds error",
                            span=span,
                            severity="warning",
                            suggestions=(DiagSuggestion(message="use a non-negative index or check bounds before access"),),
                        )
                    )
                elif expr.index.value > 1000:  # Reasonable threshold for suspicious large indices
                    span = DiagSpan(filename, max(1, getattr(expr.index, "line", 1)), max(1, getattr(expr.index, "col", 1)), max(1, getattr(expr.index, "line", 1)), max(2, getattr(expr.index, "col", 1) + 1))
                    out.append(
                        Diagnostic(
                            phase="LINT",
                            code="W0101",
                            message="array index is very large and may cause bounds error",
                            span=span,
                            severity="warning",
                            suggestions=(DiagSuggestion(message="verify the array size or add bounds checking"),),
                        )
                    )
    
    def walk_exprs(expr) -> None:
        if isinstance(expr, IndexExpr):
            check_array_access(expr)
        # Recursively check nested expressions
        for child in getattr(expr, "__dict__", {}).values():
            if isinstance(child, (list, tuple)):
                for item in child:
                    if hasattr(item, "__dict__"):
                        walk_exprs(item)
            elif hasattr(child, "__dict__"):
                walk_exprs(child)
    
    def walk(stmts: list) -> None:
        for st in stmts:
            # Check expressions in statements
            if hasattr(st, "expr"):
                walk_exprs(st.expr)
            if hasattr(st, "cond"):
                walk_exprs(st.cond)
            if hasattr(st, "iterable"):
                walk_exprs(st.iterable)
            
            for nested in _nested_blocks(st):
                walk(nested)
    
    walk(body)
    return out


def _performance_warnings(body: list, filename: str, source_text: str) -> list[Diagnostic]:
    """Detect performance issues like suboptimal 2D array iteration."""
    out: list[Diagnostic] = []
    
    def detect_2d_iteration_pattern(stmts: list) -> None:
        """Detect suboptimal 2D array iteration patterns."""
        for i, st in enumerate(stmts):
            if isinstance(st, ForStmt) and i + 1 < len(stmts):
                next_st = stmts[i + 1]
                if isinstance(next_st, ForStmt):
                    # Check for nested for loops that might be accessing 2D arrays
                    # This is a simplified detection - a full implementation would need
                    # more sophisticated analysis of array access patterns
                    outer_var = st.var
                    inner_var = next_st.var
                    
                    # Look for array access patterns in the inner loop body
                    for inner_stmt in next_st.body:
                        if hasattr(inner_stmt, "expr"):
                            # Check for patterns like arr[col][row] where col is outer, row is inner
                            # This is a placeholder for more sophisticated analysis
                            pass
    
    def walk(stmts: list) -> None:
        for st in stmts:
            if isinstance(st, ForStmt):
                detect_2d_iteration_pattern(st.body)
            
            for nested in _nested_blocks(st):
                walk(nested)
    
    walk(body)
    return out
