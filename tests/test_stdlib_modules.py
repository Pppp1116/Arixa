from pathlib import Path

import pytest

from astra.ast import EnumDecl, FnDecl, StructDecl, TypeAliasDecl
from astra.parser import parse
from astra.semantic import SemanticError, analyze


def _load(path: str) -> str:
    return Path(path).read_text()


def test_core_stdlib_module_analyzes_in_freestanding_mode():
    modules = [
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
        "stdlib/collections.astra",
        "stdlib/crypto.astra",
        "stdlib/random.astra",
        "stdlib/crypto/otp.astra",
        "stdlib/io.astra",
        "stdlib/str.astra",
        "stdlib/bytes.astra",
        "stdlib/net.astra",
        "stdlib/process.astra",
        "stdlib/serde.astra",
        "stdlib/time.astra",
    ]
    for module in modules:
        src = _load(module)
        prog = parse(src, filename=module)
        with pytest.raises(SemanticError, match="freestanding mode forbids builtin"):
            analyze(prog, filename=module, freestanding=True)


def test_extended_stdlib_exports_exist():
    checks = {
        "stdlib/core.astra": {"Option", "Result", "Bytes", "add_checked", "sub_checked", "mul_checked", "div_checked"},
        "stdlib/time.astra": {"now_ms", "sleep_seconds"},
        "stdlib/io.astra": {"read_or", "print_int", "print_bool", "print_float", "print_str", "print_any"},
        "stdlib/collections.astra": {"map_get_or"},
        "stdlib/bytes.astra": {"Bytes", "len_view", "is_empty_view", "get_view", "eq_view", "starts_with_view", "str_len_view", "str_is_empty_view", "utf8_is_valid", "utf8_decode_view", "utf8_encode_view"},
        "stdlib/net.astra": {"tcp_send_line"},
        "stdlib/process.astra": {"env_or", "run_ok", "eprintln"},
        "stdlib/crypto.astra": {"digest_pair"},
        "stdlib/random.astra": {"secure_bytes"},
        "stdlib/crypto/otp.astra": {"OtpError", "OtpKey", "secure_bytes", "xor_bytes", "xor_in_place", "new_random", "from_bytes", "encrypt", "decrypt", "encrypt_utf8", "decrypt_utf8"},
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
