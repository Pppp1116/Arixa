"""Static checking pipeline that reports normalized diagnostics for Astra sources."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from astra.comptime import ComptimeError, run_comptime
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


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
    overflow_mode = "trap" if overflow == "debug" else overflow
    diagnostics: list[Diagnostic] = []
    try:
        prog = parse(source, filename=filename)
    except ParseError as err:
        diagnostics.extend(_parse_diag_lines(str(err), default_filename=filename))
        return _result(False, diagnostics, [filename])
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
    return _result(len(diagnostics) == 0, diagnostics, [filename])


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
        res = run_check_source(
            src,
            filename=path,
            freestanding=freestanding,
            overflow=overflow,
            collect_errors=collect_errors,
        )
        files.extend(res.files_checked)
        diagnostics.extend(res.diagnostics)
    return _result(len(diagnostics) == 0, diagnostics, files)


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
                "span": {
                    "filename": d.span.filename,
                    "line": d.span.line,
                    "col": d.span.col,
                    "end_line": d.span.end_line,
                    "end_col": d.span.end_col,
                },
                "notes": [
                    {
                        "message": n.message,
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
    return f"{d.phase}[{d.code}] {d.span.filename}:{d.span.line}:{d.span.col}: {d.message}"


def _result(ok: bool, diagnostics: list[Diagnostic], files: list[str]) -> CheckResult:
    normalized = _dedupe_and_sort(diagnostics)
    return CheckResult(ok=ok, diagnostics=tuple(normalized), files_checked=tuple(files))


def _dedupe_and_sort(diags: list[Diagnostic]) -> list[Diagnostic]:
    by_key: dict[tuple, Diagnostic] = {}
    for d in diags:
        key = (d.phase, d.code, d.message, d.span.filename, d.span.line, d.span.col, d.span.end_line, d.span.end_col)
        if key not in by_key:
            by_key[key] = d
    return sorted(
        by_key.values(),
        key=lambda d: (
            d.span.filename,
            d.span.line,
            d.span.col,
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
            code="ASTRA-SEM-9999",
            message=text.strip() or "unknown compiler error",
            span=fallback_span,
        )
    ]


def _parse_one_diag_line(line: str, *, default_filename: str) -> Diagnostic:
    if " " not in line:
        span = DiagSpan(default_filename, 1, 1, 1, 2)
        return Diagnostic(phase="SEM", code="ASTRA-SEM-9999", message=line, span=span)
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
    return Diagnostic(
        phase=phase,
        code=_code_for(phase, msg),
        message=msg,
        span=span,
        notes=tuple(_notes_for(msg, span)),
    )


def _code_for(phase: str, message: str) -> str:
    m = message.lower()
    if phase == "LEX":
        if "unterminated string" in m:
            return "ASTRA-LEX-0001"
        if "unterminated char" in m:
            return "ASTRA-LEX-0002"
        if "unterminated block comment" in m:
            return "ASTRA-LEX-0003"
        if "invalid numeric literal" in m:
            return "ASTRA-LEX-0004"
        return "ASTRA-LEX-9999"
    if phase == "PARSE":
        if m.startswith("expected "):
            return "ASTRA-PARSE-0001"
        if "unexpected top-level token" in m or "unexpected atom" in m:
            return "ASTRA-PARSE-0002"
        if "unexpected eof" in m:
            return "ASTRA-PARSE-0003"
        return "ASTRA-PARSE-9999"
    if phase == "SEM":
        if "type mismatch" in m:
            return "ASTRA-TYPE-0001"
        if "cannot resolve import" in m:
            return "ASTRA-MOD-0001"
        if "undefined name" in m:
            return "ASTRA-NAME-0001"
        if "undefined function" in m:
            return "ASTRA-NAME-0002"
        if "missing main()" in m or "missing _start()" in m:
            return "ASTRA-ENTRY-0001"
        if "outside loop" in m:
            return "ASTRA-CFG-0001"
        if "comptime:" in m:
            return "ASTRA-COMPTIME-0001"
        return "ASTRA-SEM-9999"
    return "ASTRA-UNKNOWN-9999"


def _notes_for(message: str, span: DiagSpan) -> list[DiagNote]:
    match = _TYPE_MISMATCH_RE.match(message)
    if match is not None:
        context, expected, got = match.groups()
        return [
            DiagNote(message=f"context: {context}", span=span),
            DiagNote(message=f"expected: {expected}", span=span),
            DiagNote(message=f"got: {got}", span=span),
        ]
    if "cannot resolve import" in message:
        return [DiagNote(message="hint: verify import path and stdlib packaging configuration")]
    return []
