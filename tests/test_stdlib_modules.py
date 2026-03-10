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
        "stdlib/os.arixa",
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
        "stdlib/core.arixa": {
            "Bytes",
            "add_checked",
            "sub_checked",
            "mul_checked",
            "div_checked",
            "min_int2",
            "max_int2",
            "clamp_int2",
            "is_power_of_two",
            "align_up_checked",
            "align_down_checked",
            "saturating_add",
            "saturating_sub",
        },
        "stdlib/time.arixa": {"now_ms", "sleep_seconds"},
        "stdlib/io.arixa": {"read_or", "read_lines", "write_lines", "append_line", "print"},
        "stdlib/collections.arixa": {"map_get_or", "map_get_opt", "List", "Map", "list_new_typed", "map_new_typed", "push", "get", "put", "len", "has"},
        "stdlib/net.arixa": {"tcp_send_line", "tcp_send_ok", "tcp_recv_or"},
        "stdlib/os.arixa": {
            "Errno",
            "DeviceId",
            "SpinLock",
            "is_ok",
            "is_error",
            "make_device_id",
            "device_major",
            "device_minor",
            "is_page_aligned",
            "align_up_page",
            "align_down_page",
            "poll_until",
            "spin_lock_new",
            "spin_lock_try_acquire",
            "spin_lock_acquire",
            "spin_lock_release",
            "spin_lock_is_locked",
        },
        "stdlib/thread.arixa": {"spawn0", "spawn1", "join_task", "join_timeout", "yield_now"},
        "stdlib/sync.arixa": {"mutex_new", "mutex_lock", "mutex_unlock"},
        "stdlib/channel.arixa": {"Channel", "channel_new", "channel_send", "channel_recv", "channel_try_recv", "channel_recv_blocking", "channel_close"},
        "stdlib/atomic.arixa": {"AtomicInt", "atomic_int_new", "atomic_load", "atomic_store", "atomic_fetch_add", "atomic_compare_exchange"},
        "stdlib/process.arixa": {"env_or", "env_opt", "run_ok", "run_code", "eprintln", "exit_success", "exit_failure"},
        "stdlib/crypto.arixa": {"CryptoError", "digest_pair", "rand_bytes"},
        "stdlib/serde.arixa": {"ParseError", "to_json", "from_json"},
        "stdlib/math.arixa": {"min_int", "max_int", "clamp_int", "abs_int", "gcd_int", "lcm_int"},
        "stdlib/vec.arixa": {"vec_new_typed", "vec_len_typed", "vec_push_typed", "vec_get_typed", "vec_set_typed", "vec_last_typed"},
        "stdlib/mem.arixa": {"fill_bytes", "copy_bytes", "zero_bytes", "bytes_equal", "compare_bytes"},
        "stdlib/bytes.arixa": {"compare", "join", "count_byte", "index_of_byte"},
        "stdlib/algorithm.arixa": {"sum_int", "all_non_negative_int", "is_sorted_int"},
        "stdlib/data.arixa": {"ring_buffer_len", "ring_buffer_is_empty", "ring_buffer_is_full"},
        "stdlib/str.arixa": {"format", "to_string", "parse_int_checked", "parse_float_checked", "parse_bool_checked", "lines", "substring", "starts_with", "ends_with"},
        "stdlib/encoding.arixa": {"utf8_encode", "utf8_decode", "hex_encode", "hex_encode_upper", "hex_decode", "base64_encode", "base64_decode", "url_encode", "url_decode"},
    }
    for path, expected in checks.items():
        prog = parse(_load(path), filename=path)
        exported = {item.name for item in prog.items if isinstance(item, FnDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, EnumDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, StructDecl)}
        exported |= {item.name for item in prog.items if isinstance(item, TypeAliasDecl)}
        assert expected.issubset(exported)


def test_encoding_and_io_modules_analyze_after_regressions():
    modules = ["stdlib/encoding.arixa", "stdlib/io.arixa"]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        analyze(prog, filename=module, freestanding=False)
