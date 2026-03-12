"""Shared builtin metadata helpers for semantics, optimizers, and backends."""

from __future__ import annotations

from typing import Any


def _builtin_sigs() -> dict[str, Any]:
    # Import lazily to avoid semantic<->backend import cycles.
    from astra.semantic import BUILTIN_SIGS

    return BUILTIN_SIGS


def normalize_builtin_name(name: str) -> str:
    return name[2:] if name.startswith("__") else name


def is_builtin_name(name: str) -> bool:
    sigs = _builtin_sigs()
    return name in sigs or normalize_builtin_name(name) in sigs


def builtin_variants(base_name: str) -> set[str]:
    return {base_name, f"__{base_name}"}


# Semantic builtin families used in multiple layers.
COUNT_LIKE_BUILTIN_BASES = frozenset({"countOnes", "leadingZeros", "trailingZeros", "popcnt", "clz", "ctz"})
ROTATE_BUILTIN_BASES = frozenset({"rotl", "rotr"})
VECTOR_BUILTIN_BASES = frozenset({"vec_new", "vec_from", "vec_len", "vec_get", "vec_set", "vec_push"})
LIST_BUILTIN_BASES = frozenset({"list_new", "list_push", "list_get", "list_set", "list_len"})
MAP_BUILTIN_BASES = frozenset({"map_new", "map_has", "map_get", "map_set"})
ASSERTION_BUILTIN_BASES = frozenset({"assert", "debug_assert", "assume", "likely", "unlikely", "static_assert", "panic"})

COUNT_LIKE_BUILTIN_NAMES = frozenset(
    variant for base in COUNT_LIKE_BUILTIN_BASES for variant in builtin_variants(base)
)
ROTATE_BUILTIN_NAMES = frozenset(
    variant for base in ROTATE_BUILTIN_BASES for variant in builtin_variants(base)
)


# Effect metadata for optimizer-level purity and side-effect analysis.
PURE_BUILTIN_BASES = frozenset(
    {
        "len",
        "format",
        "likely",
        "unlikely",
        "countOnes",
        "leadingZeros",
        "trailingZeros",
        "popcnt",
        "clz",
        "ctz",
        "rotl",
        "rotr",
        "vec_new",
        "vec_from",
        "vec_len",
        "vec_get",
    }
)

IO_BUILTIN_BASES = frozenset(
    {
        "print",
        "read_file",
        "write_file",
        "file_exists",
        "file_remove",
        "tcp_connect",
        "tcp_send",
        "tcp_recv",
        "tcp_close",
        "env_get",
        "cwd",
        "proc_run",
        "now_unix",
        "monotonic_ms",
        "sleep_ms",
        "to_json",
        "from_json",
        "sha256",
        "hmac_sha256",
        "rand_bytes",
        "panic",
        "proc_exit",
    }
)

ALLOCATING_BUILTIN_BASES = frozenset({"list_new", "map_new", "vec_new", "vec_from"})
TRAPPING_BUILTIN_BASES = frozenset({"assert", "debug_assert", "assume", "panic", "proc_exit"})
MUTATING_CONTAINER_BUILTIN_BASES = frozenset({"vec_set", "vec_push", "list_push", "list_set", "map_set"})

FREESTANDING_FORBIDDEN_BUILTIN_BASES = frozenset(
    {
        "print",
        "len",
        "read_file",
        "write_file",
        "args",
        "arg",
        "spawn",
        "join",
        "list_new",
        "list_push",
        "list_get",
        "list_set",
        "list_len",
        "map_new",
        "map_has",
        "map_get",
        "map_set",
        "file_exists",
        "file_remove",
        "tcp_connect",
        "tcp_send",
        "tcp_recv",
        "tcp_close",
        "to_json",
        "from_json",
        "sha256",
        "hmac_sha256",
        "rand_bytes",
        "mutex_new",
        "mutex_lock",
        "mutex_unlock",
        "chan_new",
        "chan_send",
        "chan_recv_try",
        "chan_recv_blocking",
        "chan_close",
        "env_get",
        "cwd",
        "proc_run",
        "now_unix",
        "monotonic_ms",
        "sleep_ms",
        "panic",
        "proc_exit",
    }
)


def builtin_effect_profile(name: str) -> dict[str, Any]:
    """Return normalized effect profile for a builtin name."""
    sigs = _builtin_sigs()
    base = normalize_builtin_name(name)
    if base not in sigs:
        return {
            "is_builtin": False,
            "base": base,
            "is_pure": False,
            "has_io": False,
            "can_trap": False,
            "allocates": False,
        }
    return {
        "is_builtin": True,
        "base": base,
        "is_pure": base in PURE_BUILTIN_BASES,
        "has_io": base in IO_BUILTIN_BASES,
        "can_trap": base in TRAPPING_BUILTIN_BASES,
        "allocates": base in ALLOCATING_BUILTIN_BASES,
    }
