from astra import builtin_metadata as builtins
from astra import semantic


def test_builtin_name_recognition_handles_internal_aliases():
    assert builtins.is_builtin_name("len")
    assert builtins.is_builtin_name("__len")
    assert builtins.is_builtin_name("print")
    assert builtins.is_builtin_name("__print")


def test_builtin_effect_profile_normalizes_aliases():
    direct = builtins.builtin_effect_profile("print")
    internal = builtins.builtin_effect_profile("__print")
    assert direct["is_builtin"] is True
    assert internal["is_builtin"] is True
    assert direct["base"] == "print"
    assert internal["base"] == "print"
    assert direct["has_io"] is True
    assert internal["has_io"] is True


def test_builtin_detection_tracks_semantic_builtin_table():
    key = "future_intrinsic"
    semantic.BUILTIN_SIGS[key] = semantic.BuiltinSig(["Int"], "Int")
    try:
        assert builtins.is_builtin_name(key)
        assert builtins.is_builtin_name(f"__{key}")
        profile = builtins.builtin_effect_profile(f"__{key}")
        assert profile["is_builtin"] is True
        assert profile["base"] == key
    finally:
        semantic.BUILTIN_SIGS.pop(key, None)
