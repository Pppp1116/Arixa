"""Comprehensive semantic-analysis tests aligned with current language rules."""

from __future__ import annotations

import pytest

from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_basic_type_inference_and_annotations() -> None:
    src = "fn main() Int{ x = 1; y: Float = 2.0; return x; }"
    prog = parse(src)
    analyze(prog)


def test_type_mismatch_reports_context() -> None:
    src = 'fn main() Int{ x: Int = "hello"; return 0; }'
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "type mismatch" in str(exc.value)


def test_undefined_name_is_error() -> None:
    src = "fn main() Int{ return nope; }"
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "undefined" in str(exc.value)


def test_mutability_violation_is_error() -> None:
    src = "fn main() Int{ x = 1; x = 2; return x; }"
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "immutable" in str(exc.value)


def test_use_after_move_is_error() -> None:
    src = "fn main() Int{ s = \"hello\"; t = s; return len(s); }"
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "use-after-move" in str(exc.value)


def test_mutable_borrow_conflict_is_error() -> None:
    src = "fn main() Int{ mut x = 1; r1 = &x; r2 = &mut x; return 0; }"
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "mutable reference" in str(exc.value)


def test_match_bool_exhaustive_via_or_pattern() -> None:
    src = "fn main() Int{ b = true; match b { true | false => { return 1; } } return 0; }"
    analyze(parse(src))


def test_match_non_exhaustive_enum_is_error() -> None:
    src = """
enum Color { Red, Green, Blue }
fn main() Int{
  c = Color.Red;
  match c {
    Color.Red => { return 1; }
    Color.Green => { return 2; }
  }
  return 0;
}
"""
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "non-exhaustive" in str(exc.value)


def test_generic_where_clause_can_be_satisfied() -> None:
    src = """
trait Show { fn show(x Self) String; }
fn show(x Int) String { return \"ok\"; }
fn wrap<T>(x T) T where T: Show { return x; }
fn main() Int{ return wrap(1); }
"""
    analyze(parse(src))


def test_vec_builtin_type_checks() -> None:
    src = "fn main() Int{ mut v = vec_from([1, 2]); vec_push(v, 3); return vec_len(v); }"
    analyze(parse(src))


def test_import_string_resolves_relative_module_file(tmp_path) -> None:
    dep = tmp_path / "dep.arixa"
    dep.write_text("fn helper() Int{ return 42; }")
    src = tmp_path / "main.arixa"
    src.write_text('import "dep"; fn main() Int{ return helper(); }')
    prog = parse(src.read_text(), filename=str(src))
    analyze(prog, filename=str(src))


def test_missing_import_is_error() -> None:
    src = 'import "does-not-exist"; fn main() Int{ return 0; }'
    with pytest.raises(SemanticError) as exc:
        analyze(parse(src))
    assert "cannot resolve import" in str(exc.value)
