from astra.lexer import lex


def kinds(src: str) -> list[str]:
    return [t.kind for t in lex(src)]


def test_new_keywords_and_bool():
    ks = kinds("for break continue struct enum type import let fixed mut pub extern async await unsafe impl match defer drop comptime none true false")
    assert "for" in ks
    assert "break" in ks
    assert "continue" in ks
    assert "extern" in ks
    assert "async" in ks
    assert "await" in ks
    assert "unsafe" in ks
    assert "impl" in ks
    assert "fixed" in ks
    assert "none" in ks
    assert "defer" in ks
    assert "drop" in ks
    assert "comptime" in ks
    assert "BOOL" in ks
    assert ks.count("BOOL") == 2


def test_float_doc_comment_and_symbols():
    toks = lex('/// docs\nlet x = 1.5 && true; x += 1; a[0].b:c; let y: Option<Int> = none; let z = y ?? 1;')
    assert toks[0].kind == "DOC_COMMENT"
    assert any(t.kind == "FLOAT" for t in toks)
    seen = {t.kind for t in toks}
    for sym in ["&&", "+=", "[", "]", ".", ":", "??"]:
        assert sym in seen


def test_line_col_and_block_comment_and_error():
    toks = lex("let x = 1;\n/* ok */\n@");
    at = [t for t in toks if t.kind == "@"][0]
    assert (at.line, at.col) == (3, 1)

    err = [t for t in lex("$") if t.kind == "ERROR"]
    assert err and err[0].text == "$"


def test_lexes_dynamic_integer_type_tokens():
    toks = lex("let a: u4 = 1u4; let b: i127 = 2;")
    kinds = [t.kind for t in toks]
    assert kinds.count("INT_TYPE") >= 3
    assert any(t.kind == "INT_TYPE" and t.text == "u4" for t in toks)
    assert any(t.kind == "INT_TYPE" and t.text == "i127" for t in toks)


def test_invalid_integer_width_tokens_emit_lex_error():
    toks = lex("let a: i0 = 1; let b: u65536 = 2;")
    errs = [t for t in toks if t.kind == "ERROR"]
    assert len(errs) >= 2
    assert all("integer width must be between" in t.text for t in errs[:2])


def test_lexes_prefixed_and_separator_integer_literals():
    toks = lex("let a = 0xFF_FF; let b = 0b1010_0101; let c = 1_000_000; let d = 123u32;")
    ints = [t.text for t in toks if t.kind == "INT"]
    assert "0xFF_FF" in ints
    assert "0b1010_0101" in ints
    assert "1_000_000" in ints
    assert "123" in ints
    assert any(t.kind == "INT_TYPE" and t.text == "u32" for t in toks)


def test_invalid_separator_literals_emit_lex_error():
    toks = lex("let a = 1__2; let b = 0x_FF; let c = 0b;")
    errs = [t for t in toks if t.kind == "ERROR"]
    assert len(errs) >= 3
    assert all("invalid numeric literal" in t.text for t in errs)


def test_lexes_multiline_string_literal():
    src = 'fn main() -> Int { let s = """a\nb"""; return 0; }'
    toks = lex(src)
    kinds = [t.kind for t in toks]
    assert "STR_MULTI" in kinds


def test_lexes_ellipsis_token_for_variadic_externs():
    toks = lex("extern fn printf(fmt: *u8, ...) -> i32;")
    assert any(t.kind == "..." for t in toks)
