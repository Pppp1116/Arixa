from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from astra.ast import ArrayLit, Binary, BoolLit, Call, ExprStmt, FnDecl, IfStmt, Literal, MatchStmt, Name, Program


VALUE_PROFILE_PATH = Path('.build') / 'value_profile.json'


def write_value_profile_template(prog: Program) -> dict[str, dict[str, Any]]:
    """Write a zero-initialized value-profile template for the analyzed program."""
    payload: dict[str, dict[str, Any]] = {
        'switch_cases': {},
        'indirect_calls': {},
        'array_lengths': {},
        'common_integers': {},
    }
    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        fn = item.symbol or item.name
        _collect_stmt_profiles(item.body, fn, payload)
    VALUE_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    VALUE_PROFILE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def load_value_profile() -> dict[str, dict[str, Any]]:
    """Load value-profile data from disk with empty defaults when unavailable."""
    if not VALUE_PROFILE_PATH.exists():
        return {'switch_cases': {}, 'indirect_calls': {}, 'array_lengths': {}, 'common_integers': {}}
    data = json.loads(VALUE_PROFILE_PATH.read_text())
    return {
        'switch_cases': dict(data.get('switch_cases', {})),
        'indirect_calls': dict(data.get('indirect_calls', {})),
        'array_lengths': dict(data.get('array_lengths', {})),
        'common_integers': dict(data.get('common_integers', {})),
    }


def apply_value_specialization(prog: Program, profile: dict[str, dict[str, Any]]) -> None:
    """Rewrite match-heavy code with profile-guided hot-value fast paths."""
    for item in prog.items:
        if isinstance(item, FnDecl):
            item.body = _rewrite_stmts(item.body, item.symbol or item.name, profile)


def _collect_stmt_profiles(stmts: list[Any], fn_name: str, out: dict[str, dict[str, Any]]) -> None:
    """Collect statement-level profiling buckets for a function body."""
    for stmt in stmts:
        if isinstance(stmt, MatchStmt):
            key = _switch_key(fn_name, stmt)
            bucket: dict[str, int] = out['switch_cases'].setdefault(key, {})
            for pattern, _ in stmt.arms:
                lit = _literal_key(pattern)
                if lit is not None:
                    bucket.setdefault(lit, 0)
        elif isinstance(stmt, ExprStmt) and isinstance(stmt.expr, Call):
            call = stmt.expr
            if not isinstance(call.fn, Name):
                out['indirect_calls'].setdefault(_call_key(fn_name, call), {})
            for arg in call.args:
                _collect_expr_profiles(arg, fn_name, out)
            _collect_expr_profiles(call.fn, fn_name, out)
        elif isinstance(stmt, IfStmt):
            _collect_stmt_profiles(stmt.then_body, fn_name, out)
            _collect_stmt_profiles(stmt.else_body, fn_name, out)
            _collect_expr_profiles(stmt.cond, fn_name, out)
        elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
            _collect_stmt_profiles(stmt.body, fn_name, out)
        if hasattr(stmt, 'expr') and stmt.expr is not None:
            _collect_expr_profiles(stmt.expr, fn_name, out)
        if hasattr(stmt, 'cond') and stmt.cond is not None:
            _collect_expr_profiles(stmt.cond, fn_name, out)
        if hasattr(stmt, 'init') and stmt.init is not None:
            _collect_expr_profiles(stmt.init, fn_name, out)
        if hasattr(stmt, 'step') and stmt.step is not None:
            _collect_expr_profiles(stmt.step, fn_name, out)
        if hasattr(stmt, 'target') and stmt.target is not None:
            _collect_expr_profiles(stmt.target, fn_name, out)
        if hasattr(stmt, 'right') and stmt.right is not None:
            _collect_expr_profiles(stmt.right, fn_name, out)
        if hasattr(stmt, 'left') and stmt.left is not None:
            _collect_expr_profiles(stmt.left, fn_name, out)


def _collect_expr_profiles(expr: Any, fn_name: str, out: dict[str, dict[str, Any]]) -> None:
    """Collect expression-level profiling buckets (literals, arrays, calls)."""
    if isinstance(expr, ArrayLit):
        key = f'{fn_name}:array_literal'
        b = out['array_lengths'].setdefault(key, {})
        b[str(len(expr.elements))] = b.get(str(len(expr.elements)), 0)
        for e in expr.elements:
            _collect_expr_profiles(e, fn_name, out)
    elif isinstance(expr, Literal) and isinstance(expr.value, int):
        key = f'{fn_name}:int_literal'
        b = out['common_integers'].setdefault(key, {})
        b[str(expr.value)] = b.get(str(expr.value), 0)
    elif isinstance(expr, Call):
        if not isinstance(expr.fn, Name):
            out['indirect_calls'].setdefault(_call_key(fn_name, expr), {})
        _collect_expr_profiles(expr.fn, fn_name, out)
        for a in expr.args:
            _collect_expr_profiles(a, fn_name, out)
    elif isinstance(expr, Binary):
        _collect_expr_profiles(expr.left, fn_name, out)
        _collect_expr_profiles(expr.right, fn_name, out)


def _rewrite_stmts(stmts: list[Any], fn_name: str, profile: dict[str, dict[str, Any]]) -> list[Any]:
    """Apply profile-guided rewrites recursively across a statement list."""
    out: list[Any] = []
    for stmt in stmts:
        if isinstance(stmt, MatchStmt) and not getattr(stmt, '_value_specialized', False):
            specialized = _specialize_match_stmt(stmt, fn_name, profile)
            if isinstance(specialized, IfStmt):
                specialized.then_body = _rewrite_stmts(specialized.then_body, fn_name, profile)
                specialized.else_body = _rewrite_stmts(specialized.else_body, fn_name, profile)
            elif isinstance(specialized, MatchStmt):
                for i, (pat, body) in enumerate(specialized.arms):
                    specialized.arms[i] = (pat, _rewrite_stmts(body, fn_name, profile))
            elif hasattr(specialized, 'body') and isinstance(specialized.body, list):
                specialized.body = _rewrite_stmts(specialized.body, fn_name, profile)
            out.append(specialized)
            continue
        if isinstance(stmt, IfStmt):
            stmt.then_body = _rewrite_stmts(stmt.then_body, fn_name, profile)
            stmt.else_body = _rewrite_stmts(stmt.else_body, fn_name, profile)
        elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
            stmt.body = _rewrite_stmts(stmt.body, fn_name, profile)
        out.append(stmt)
    return out


def _specialize_match_stmt(stmt: MatchStmt, fn_name: str, profile: dict[str, dict[str, Any]]) -> Any:
    """Specialize one match statement when a dominant profiled value exists."""
    key = _switch_key(fn_name, stmt)
    legacy_key = _switch_key_legacy(fn_name, stmt)
    case_counts: dict[str, Any] = {}
    case_counts.update(profile.get('switch_cases', {}).get(legacy_key, {}))
    for k, v in profile.get('switch_cases', {}).get(key, {}).items():
        case_counts[k] = int(case_counts.get(k, 0)) + int(v)
    hot_value = _dominant_value(case_counts)
    if hot_value is None:
        return stmt
    hot_pattern, hot_body = _find_hot_arm(stmt.arms, hot_value)
    if hot_pattern is None:
        return stmt
    if not isinstance(stmt.expr, (Name, Literal, BoolLit)):
        return stmt
    fallback = copy.deepcopy(stmt)
    fallback._value_specialized = True
    cond = Binary(op='==', left=copy.deepcopy(stmt.expr), right=copy.deepcopy(hot_pattern), pos=stmt.pos, line=stmt.line, col=stmt.col)
    return IfStmt(cond=cond, then_body=copy.deepcopy(hot_body), else_body=[fallback], pos=stmt.pos, line=stmt.line, col=stmt.col)


def _find_hot_arm(arms: list[tuple[Any, list[Any]]], hot_value: str) -> tuple[Any | None, list[Any] | None]:
    """Locate the match arm corresponding to the selected hot literal value."""
    for p, body in arms:
        if _literal_key(p) == hot_value:
            return p, body
    return None, None


def _dominant_value(counts: dict[str, Any]) -> str | None:
    """Return a dominant key when one value contributes at least 90% of counts."""
    if not counts:
        return None
    total = sum(int(v) for v in counts.values())
    if total <= 0:
        return None
    hot_key, hot_count = max(counts.items(), key=lambda kv: int(kv[1]))
    if int(hot_count) / float(total) < 0.9:
        return None
    return str(hot_key)


def _switch_key(fn_name: str, stmt: MatchStmt) -> str:
    """Build a site-unique key for a match profile bucket."""
    site_id = f"{stmt.line}:{stmt.col}:{stmt.pos}"
    if isinstance(stmt.expr, Name):
        return f'{fn_name}:{stmt.expr.value}:{site_id}'
    return f'{fn_name}:match:{site_id}'


def _switch_key_legacy(fn_name: str, stmt: MatchStmt) -> str:
    """Build the pre-site-id key used for backward profile compatibility."""
    if isinstance(stmt.expr, Name):
        return f'{fn_name}:{stmt.expr.value}'
    return f'{fn_name}:match@{stmt.line}:{stmt.col}'


def _call_key(fn_name: str, call: Call) -> str:
    """Build a stable profile key for an indirect call site."""
    return f'{fn_name}:indirect@{call.line}:{call.col}'


def _literal_key(pat: Any) -> str | None:
    """Convert a literal-like pattern node into a serializable profile key."""
    if isinstance(pat, Literal):
        return str(pat.value)
    if isinstance(pat, BoolLit):
        return 'true' if pat.value else 'false'
    return None
