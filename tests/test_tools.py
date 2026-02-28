from astra.formatter import fmt
from astra.linter import lint_text


def test_formatter():
    out = fmt('fn main() -> Int {\nprint(1);\n}\n')
    assert 'print(1);' in out


def test_linter_clean():
    assert lint_text('a\n') == []
