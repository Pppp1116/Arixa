from astra.check import diagnostics_to_json_list, format_diagnostic, run_check_source


def test_check_emits_structured_type_mismatch_diagnostic_with_notes():
    src = 'fn main() Int{ return "x"; }'
    res = run_check_source(src, filename="<mem>")
    assert not res.ok
    assert res.diagnostics
    first = res.diagnostics[0]
    assert first.code == "E0100"
    assert first.message == "expected `i64` but found `String` in return value"
    note_messages = {n.message for n in first.notes}
    assert any(msg.startswith("expected:") for msg in note_messages)
    assert any(msg.startswith("found:") for msg in note_messages)


def test_check_collects_multiple_semantic_errors():
    src = """
fn a() Int{ return "x"; }
fn b() Int{ return true; }
fn main() Int{ return 0; }
"""
    res = run_check_source(src, filename="<mem>", collect_errors=True)
    assert not res.ok
    assert len(res.diagnostics) >= 2


def test_check_reports_lex_error_with_phase_code_and_span():
    src = 'fn main() Int{ s = "unterminated; return 0; }'
    res = run_check_source(src, filename="mem://lex.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert first.phase == "LEX"
    assert first.code == "E0002"
    assert first.span.filename == "mem://lex.astra"
    assert first.span.line == 1
    assert first.span.col > 1


def test_check_reports_parse_error_with_phase_code_and_span():
    src = "fn main() Int{ x = ; return 0; }"
    res = run_check_source(src, filename="mem://parse.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert first.phase == "PARSE"
    assert first.code in {"E0300", "E0002"}
    assert first.span.filename == "mem://parse.astra"
    assert first.span.line == 1
    assert first.span.col > 1


def test_check_reports_c_style_for_as_parse_error():
    src = "fn main() Int{ for i = 0; i < 3; i += 1 { } return 0; }"
    res = run_check_source(src, filename="mem://for.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert first.phase == "PARSE"
    assert first.code == "E0302"
    assert "for expects `for <ident> in <expr> { ... }`" in first.message


def test_check_reports_missing_semicolon_with_fixit():
    src = "fn main() Int{ x = 1 return 0; }"
    res = run_check_source(src, filename="mem://semi.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert first.code == "E0301"
    assert first.message == "expected `;`"
    assert first.suggestions
    assert first.suggestions[0].replacement == ";"


def test_check_reports_typo_with_edit_distance_suggestion():
    src = "fn main() Int{ pritn(1); return 0; }"
    res = run_check_source(src, filename="mem://typo.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert first.code == "E0201"
    assert any("did you mean `print`?" == s.message for s in first.suggestions)


def test_check_emits_multi_location_note_for_assignment_mismatch():
    src = """
fn main() Int{
  mut x: Int = 10;
  x = "hello";
  return 0;
}
"""
    res = run_check_source(src, filename="mem://assign.astra")
    assert not res.ok
    mismatch = next(d for d in res.diagnostics if d.code == "E0100")
    assert any(n.span is not None and "declared with this type" in n.message for n in mismatch.notes)


def test_check_json_payload_contains_required_fields():
    src = "fn main() Int{ x = 1 return 0; }"
    res = run_check_source(src, filename="mem://json.astra")
    payload = diagnostics_to_json_list(res.diagnostics)
    assert payload
    first = payload[0]
    assert first["code"] == "E0301"
    assert first["severity"] == "error"
    assert first["file"] == "mem://json.astra"
    assert "range" in first
    assert "suggestions" in first
    assert "notes" in first


def test_check_formats_diagnostic_in_rust_like_style():
    src = "fn main() Int{ x = 1 return 0; }"
    res = run_check_source(src, filename="mem://fmt.astra")
    first = res.diagnostics[0]
    rendered = format_diagnostic(first)
    assert rendered.startswith("error[E0301]: expected `;`")
    assert "  --> mem://fmt.astra:1:" in rendered
    assert "   = help: add `;` at the end of the statement" in rendered


def test_check_reports_non_exhaustive_enum_match_with_suggestion():
    src = """
enum Color {
  Red,
  Green,
  Blue,
}
fn main() Int{
  c: Color = Color.Red;
  match c {
    Color.Red => { return 1; }
    Color.Green => { return 2; }
  }
  return 0;
}
"""
    res = run_check_source(src, filename="mem://enum_match.astra")
    assert not res.ok
    first = res.diagnostics[0]
    assert "non-exhaustive `match` for enum `Color`" in first.message
    assert any("remaining enum variants" in s.message for s in first.suggestions)
