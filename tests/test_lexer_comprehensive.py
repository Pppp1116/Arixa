"""Comprehensive lexer tests aligned with the current ASTRA token contract."""

from astra.lexer import Token, lex


def _kinds(src: str) -> list[str]:
    return [t.kind for t in lex(src)]


def test_empty_input_emits_only_eof() -> None:
    toks = lex("")
    assert len(toks) == 1
    assert toks[0].kind == "EOF"


def test_whitespace_only_emits_only_eof() -> None:
    toks = lex("  \n\t  \n")
    assert len(toks) == 1
    assert toks[0].kind == "EOF"


def test_keywords_identifiers_and_symbols() -> None:
    ks = _kinds("fn main() Int{ mut x = 1; if x > 0 { return x; } }")
    for required in ["fn", "IDENT", "(", ")", "{", "mut", "if", "return", "}", "EOF"]:
        assert required in ks


def test_operators_and_compound_tokens() -> None:
    ks = _kinds("a += 1; b = a ?? 0; c = x << 2; d = y >= 1 && y <= 9;")
    for required in ["+=", "??", "<<", ">=", "&&", "<=", "EOF"]:
        assert required in ks


def test_numeric_literals_and_type_suffixes() -> None:
    toks = lex("a = 0xFF; b = 1_000; c = 1u32; d: u4 = 7u4;")
    ints = [t.text for t in toks if t.kind == "INT"]
    assert "0xFF" in ints
    assert "1_000" in ints
    assert "1" in ints
    assert any(t.kind == "INT_TYPE" and t.text == "u32" for t in toks)
    assert any(t.kind == "ARBITRARY_INT_TYPE" and t.text == "u4" for t in toks)


def test_string_char_and_multiline_literals() -> None:
    toks = lex('a = "hi"; b = "value {x}"; c = \'z\'; d = """m\\nn""";')
    assert any(t.kind == "STR" and t.text == "hi" for t in toks)
    assert any(t.kind == "STR_INTERP" for t in toks)
    assert any(t.kind == "CHAR" and t.text == "z" for t in toks)
    assert any(t.kind == "STR_MULTI" for t in toks)


def test_comments_and_positions() -> None:
    toks = lex("/// docs\n// line\n# shell\n@")
    assert toks[0] == Token("DOC_COMMENT", "docs", 0, 1, 1)
    at = [t for t in toks if t.kind == "@"][0]
    assert (at.line, at.col) == (4, 1)


def test_invalid_tokens_emit_error() -> None:
    toks = lex("$ 1__2 0b")
    errs = [t for t in toks if t.kind == "ERROR"]
    assert errs
    assert errs[0].text == "$"
    assert any("invalid numeric literal" in t.text for t in errs)


def test_boolean_literals_are_bool_tokens() -> None:
    toks = lex("true false")
    bools = [t for t in toks if t.kind == "BOOL"]
    assert [t.text for t in bools] == ["true", "false"]


def test_removed_keywords_lex_as_identifiers() -> None:
    toks = lex("let defer drop")
    idents = [t.text for t in toks if t.kind == "IDENT"]
    assert idents == ["let", "defer", "drop"]
