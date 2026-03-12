from astra.float_types import STANDARD_FLOAT_TYPES
from astra.lexer import KEYWORDS
from astra.token_metadata import FLOAT_TYPE_KEYWORDS, is_type_atom_token, is_type_start_token


def test_float_type_keywords_track_float_registry():
    assert FLOAT_TYPE_KEYWORDS == set(STANDARD_FLOAT_TYPES.keys())
    assert set(STANDARD_FLOAT_TYPES.keys()).issubset(KEYWORDS)


def test_type_token_helpers_accept_registered_float_kinds():
    for kind in STANDARD_FLOAT_TYPES.keys():
        assert is_type_start_token(kind)
        assert is_type_atom_token(kind)
