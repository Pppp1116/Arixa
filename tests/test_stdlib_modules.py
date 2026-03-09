from pathlib import Path

import pytest

from astra.ast import EnumDecl, FnDecl, StructDecl, TypeAliasDecl
from astra.parser import parse
from astra.semantic import SemanticError, analyze


def _load(path: str) -> str:
    return Path(path).read_text()


def test_core_stdlib_module_analyzes_in_freestanding_mode():
    modules = [
        "stdlib/atomic.arixa",
        "stdlib/boot.arixa",
        "stdlib/c.arixa",
        "stdlib/core.arixa",
        "stdlib/data.arixa",
        "stdlib/embedded.arixa",
        "stdlib/hardware.arixa",
        "stdlib/math.arixa",
        "stdlib/mem.arixa",
        "stdlib/memory.arixa",
        "stdlib/vec.arixa",
    ]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        analyze(prog, filename=module, freestanding=True)


def test_hosted_stdlib_modules_are_rejected_in_freestanding_mode():
    modules = [
        "stdlib/channel.arixa",
        "stdlib/collections.arixa",
        "stdlib/crypto.arixa",
        "stdlib/io.arixa",
        "stdlib/str.arixa",
        "stdlib/net.arixa",
        "stdlib/process.arixa",
        "stdlib/serde.arixa",
        "stdlib/sync.arixa",
        "stdlib/thread.arixa",
        "stdlib/time.arixa",
    ]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        with pytest.raises(SemanticError, match="freestanding mode forbids builtin"):
            analyze(prog, filename=module, freestanding=True)


def test_extended_stdlib_exports_exist():
    checks = {
        "stdlib/core.arixa": {"Bytes", "add_checked", "sub_checked", "mul_checked", "div_checked"},
        "stdlib/time.arixa": {"now_ms", "sleep_seconds"},
        "stdlib/io.arixa": {"read_or", "print_int", "print_bool", "print_float", "print_str", "print_any"},
        "stdlib/collections.arixa": {"map_get_or", "List", "Map", "list_new_typed", "map_new_typed", "push", "get", "put", "len", "has"},
        "stdlib/net.arixa": {"tcp_send_line"},
        "stdlib/thread.arixa": {"spawn0", "spawn1", "join_task", "join_timeout", "yield_now"},
        "stdlib/sync.arixa": {"mutex_new", "mutex_lock", "mutex_unlock"},
        "stdlib/channel.arixa": {"Channel", "channel_new", "channel_send", "channel_recv", "channel_try_recv", "channel_recv_blocking", "channel_close"},
        "stdlib/atomic.arixa": {"AtomicInt", "atomic_int_new", "atomic_load", "atomic_store", "atomic_fetch_add", "atomic_compare_exchange"},
        "stdlib/process.arixa": {"env_or", "run_ok", "eprintln"},
        "stdlib/crypto.arixa": {"CryptoError", "digest_pair", "rand_bytes"},
        "stdlib/serde.arixa": {"ParseError", "to_json", "from_json"},
        "stdlib/math.arixa": {"min_int", "max_int", "clamp_int", "abs_int"},
        "stdlib/vec.arixa": {"vec_new_typed", "vec_len_typed", "vec_push_typed", "vec_get_typed"},
        "stdlib/mem.arixa": {"fill_bytes", "copy_bytes"},
    }
    for path, expected in checks.items():
        prog = parse(_load(path), filename=path)
        exported = {item.name for item in prog.items if isinstance(item, FnDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, EnumDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, StructDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, TypeAliasDecl)}
        assert expected.issubset(exported)
