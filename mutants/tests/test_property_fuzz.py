import pytest

from astra.lexer import lex
from astra.parser import ParseError, parse

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except Exception:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason="hypothesis is not installed")
else:

    @settings(max_examples=100)
    @given(st.text())
    def test_lexer_never_crashes(src: str):
        toks = lex(src)
        assert toks[-1].kind == "EOF"

    @settings(max_examples=100)
    @given(st.text())
    def test_parser_either_parses_or_raises_parse_error(src: str):
        try:
            parse(src)
        except ParseError:
            return
