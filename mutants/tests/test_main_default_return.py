from astra.parser import parse
from astra.semantic import analyze


def test_main_without_return_type_defaults_to_void():
    prog = parse("fn main() { }")
    fn = prog.items[0]
    assert fn.ret == "Void"
    analyze(prog)


def test_main_with_explicit_int_return_still_works():
    prog = parse("fn main() Int{ return 0; }")
    analyze(prog)


def test_non_main_function_can_omit_return_type_and_is_void():
    prog = parse("fn helper() { x = 1; }")
    fn = prog.items[0]
    assert fn.ret == "Void"
    analyze(prog)
