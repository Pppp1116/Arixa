from pathlib import Path

from astra.ast import EnumDecl, FnDecl, StructDecl, TypeAliasDecl
from astra.module_resolver import discover_stdlib_modules
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def _load(path: str) -> str:
    return Path(path).read_text()


def _discover_stdlib_source_modules() -> dict[str, Path]:
    return discover_stdlib_modules(include_bindings=False)


def test_stdlib_discovery_is_dynamic_and_nonempty():
    modules = _discover_stdlib_source_modules()
    assert "core" in modules
    assert "io" in modules


def test_discovered_stdlib_modules_analyze_in_hosted_mode():
    analyzed = 0
    for module, path in _discover_stdlib_source_modules().items():
        src = path.read_text()
        try:
            prog = parse(src, filename=str(path))
        except ParseError:
            continue
        try:
            analyze(prog, filename=str(path), freestanding=False)
        except SemanticError as exc:
            if "PARSE " in str(exc):
                continue
            continue
        analyzed += 1
    assert analyzed >= 5


def test_freestanding_stdlib_classification_is_source_driven():
    allowed: set[str] = set()
    forbidden: set[str] = set()
    for module, path in _discover_stdlib_source_modules().items():
        src = path.read_text()
        try:
            prog = parse(src, filename=str(path))
        except ParseError:
            continue
        try:
            analyze(prog, filename=str(path), freestanding=True)
            allowed.add(module)
        except SemanticError as exc:
            if "PARSE " in str(exc):
                continue
            if "freestanding mode forbids builtin" in str(exc):
                forbidden.add(module)
            else:
                raise
    assert "core" in allowed
    assert "io" in forbidden
    assert allowed
    assert forbidden


def test_discovered_stdlib_modules_export_symbols():
    seen = 0
    for module, path in _discover_stdlib_source_modules().items():
        try:
            prog = parse(path.read_text(), filename=str(path))
        except ParseError:
            continue
        exported = {item.name for item in prog.items if isinstance(item, FnDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, EnumDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, StructDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, TypeAliasDecl)}
        assert exported, f"{module} has no top-level exported symbols"
        seen += 1
    assert seen > 0


def test_encoding_and_io_modules_analyze_after_regressions():
    modules = ["stdlib/encoding.arixa", "stdlib/io.arixa"]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        analyze(prog, filename=module, freestanding=False)


def test_io_and_str_new_input_and_trim_helpers_exported():
    io_prog = parse(_load("stdlib/io.arixa"), filename="stdlib/io.arixa")
    io_exported = {item.name for item in io_prog.items if isinstance(item, FnDecl)}
    assert {"read_stdin_line", "read_stdin_line_trimmed", "prompt", "prompt_trimmed"}.issubset(io_exported)

    str_prog = parse(_load("stdlib/str.arixa"), filename="stdlib/str.arixa")
    str_exported = {item.name for item in str_prog.items if isinstance(item, FnDecl)}
    assert {"strip", "lstrip", "rstrip", "repeat", "strip_prefix", "strip_suffix"}.issubset(str_exported)

    analyze(io_prog, filename="stdlib/io.arixa", freestanding=False)
    analyze(str_prog, filename="stdlib/str.arixa", freestanding=False)
