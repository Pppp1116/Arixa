import pytest

from astra.asm_assert import assert_valid_llvm_ir
from astra.llvm_codegen import to_llvm_ir
from astra.parser import parse


LLVM_PROGRAMS = [
    "fn main() Int{ return 0; }",
    "fn inc(x Int) Int{ return x + 1; } fn main() Int{ return inc(9); }",
    "fn main() Int{ mut x = 0; while x < 4 { x += 1; } return x; }",
    "fn main() Int{ x = 7; if x > 3 { return 1; } return 0; }",
]


@pytest.mark.parametrize("src", LLVM_PROGRAMS)
def test_llvm_output_is_always_validated(src: str):
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)


def test_llvm_freestanding_output_is_validated():
    src = "fn _start() Int{ return 0; }"
    mod = to_llvm_ir(parse(src), freestanding=True)
    assert_valid_llvm_ir(mod)
    assert "define i64 @_start()" in mod
