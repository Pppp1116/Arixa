from pathlib import Path

import pytest

from astra.ast import EnumDecl, FnDecl, StructDecl, TypeAliasDecl
from astra.parser import parse
from astra.semantic import SemanticError, analyze


def _load(path: str) -> str:
    return Path(path).read_text()


def test_core_stdlib_module_analyzes_in_freestanding_mode():
    modules = [
        "stdlib/atomic.astra",
        "stdlib/core.astra",
        "stdlib/math.astra",
        "stdlib/vec.astra",
        "stdlib/mem.astra",
    ]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        analyze(prog, filename=module, freestanding=True)


def test_hosted_stdlib_modules_are_rejected_in_freestanding_mode():
    modules = [
        "stdlib/channel.astra",
        "stdlib/collections.astra",
        "stdlib/crypto.astra",
        "stdlib/io.astra",
        "stdlib/str.astra",
        "stdlib/net.astra",
        "stdlib/process.astra",
        "stdlib/serde.astra",
        "stdlib/sync.astra",
        "stdlib/thread.astra",
        "stdlib/time.astra",
    ]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        with pytest.raises(SemanticError, match="freestanding mode forbids builtin"):
            analyze(prog, filename=module, freestanding=True)


def test_extended_stdlib_exports_exist():
    checks = {
        "stdlib/core.astra": {"Bytes", "add_checked", "sub_checked", "mul_checked", "div_checked"},
        "stdlib/time.astra": {"now_ms", "sleep_seconds"},
        "stdlib/io.astra": {"read_or", "print_int", "print_bool", "print_float", "print_str", "print_any"},
        "stdlib/collections.astra": {"map_get_or", "List", "Map", "list_new_typed", "map_new_typed", "push", "get", "put", "len", "has"},
        "stdlib/net.astra": {"tcp_send_line"},
        "stdlib/thread.astra": {"spawn0", "spawn1", "join_task", "join_timeout", "yield_now"},
        "stdlib/sync.astra": {"mutex_new", "mutex_lock", "mutex_unlock"},
        "stdlib/channel.astra": {"Channel", "channel_new", "channel_send", "channel_recv", "channel_try_recv", "channel_recv_blocking", "channel_close"},
        "stdlib/atomic.astra": {"AtomicInt", "atomic_int_new", "atomic_load", "atomic_store", "atomic_fetch_add", "atomic_compare_exchange"},
        "stdlib/process.astra": {"env_or", "run_ok", "eprintln"},
        "stdlib/crypto.astra": {"CryptoError", "digest_pair", "rand_bytes"},
        "stdlib/serde.astra": {"ParseError", "to_json", "from_json"},
        "stdlib/math.astra": {"min_int", "max_int", "clamp_int", "abs_int"},
        "stdlib/vec.astra": {"vec_new_typed", "vec_len_typed", "vec_push_typed", "vec_get_typed"},
        "stdlib/mem.astra": {"fill_bytes", "copy_bytes"},
    }
    for path, expected in checks.items():
        prog = parse(_load(path), filename=path)
        exported = {item.name for item in prog.items if isinstance(item, FnDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, EnumDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, StructDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, TypeAliasDecl)}
        assert expected.issubset(exported)
