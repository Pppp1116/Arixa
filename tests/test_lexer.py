from astra.lexer import lex


def kinds(src: str) -> list[str]:
    return [t.kind for t in lex(src)]


def test_new_keywords_and_bool():
    ks = kinds("for break continue struct enum type import mut pub match nil true false")
    assert "for" in ks
    assert "break" in ks
    assert "continue" in ks
    assert "BOOL" in ks
    assert ks.count("BOOL") == 2


def test_float_doc_comment_and_symbols():
    toks = lex('/// docs\nlet x = 1.5 && true; x += 1; a[0].b:c')
    assert toks[0].kind == "DOC_COMMENT"
    assert any(t.kind == "FLOAT" for t in toks)
    seen = {t.kind for t in toks}
    for sym in ["&&", "+=", "[", "]", ".", ":"]:
        assert sym in seen


def test_line_col_and_block_comment_and_error():
    toks = lex("let x = 1;\n/* ok */\n@");
    at = [t for t in toks if t.kind == "@"][0]
    assert (at.line, at.col) == (3, 1)

    err = [t for t in lex("$") if t.kind == "ERROR"]
    assert err and err[0].text == "$"
