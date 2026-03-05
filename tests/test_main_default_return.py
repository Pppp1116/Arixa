import pytest

from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def test_main_without_return_type_defaults_to_int():
    prog = parse("fn main() { return 0; }")
    fn = prog.items[0]
    assert fn.ret == "Int"
    analyze(prog)


def test_main_without_return_type_requires_int_return_value():
    prog = parse("fn main() { }")
    with pytest.raises(SemanticError, match="function main must return Int"):
        analyze(prog)


def test_main_with_explicit_int_return_still_works():
    prog = parse("fn main() -> Int { return 0; }")
    analyze(prog)


def test_non_main_function_cannot_omit_return_type():
    with pytest.raises(ParseError, match="expected -> return type"):
        parse("fn helper() { return 0; }")


def test_impl_main_cannot_omit_return_type():
    with pytest.raises(ParseError, match="expected -> return type"):
        parse("impl fn main() { return 0; }")
