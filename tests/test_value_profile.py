import json
from pathlib import Path

from astra.ast import FnDecl, Literal, MatchStmt, Name, Program, ReturnStmt
from astra.value_profile import apply_value_specialization, load_value_profile, write_value_profile_template


def test_value_profile_template_written(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prog = Program(
        items=[
            FnDecl(
                name='main',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[
                    MatchStmt(
                        expr=Name('x'),
                        arms=[
                            (Literal(0), [ReturnStmt(Literal(0))]),
                            (Literal(1), [ReturnStmt(Literal(1))]),
                        ],
                    )
                ],
                symbol='main__impl0',
            )
        ]
    )
    payload = write_value_profile_template(prog)
    f = tmp_path / '.build' / 'value_profile.json'
    assert f.exists()
    parsed = json.loads(f.read_text())
    assert parsed == payload
    assert 'main__impl0:x' in payload['switch_cases']


def test_value_profile_specializes_dominant_match_case():
    prog = Program(
        items=[
            FnDecl(
                name='main',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[
                    MatchStmt(
                        expr=Name('x'),
                        arms=[
                            (Literal(0), [ReturnStmt(Literal(10))]),
                            (Literal(1), [ReturnStmt(Literal(20))]),
                        ],
                        line=10,
                        col=5,
                    )
                ],
                symbol='main__impl0',
            )
        ]
    )
    profile = {'switch_cases': {'main__impl0:x': {'0': 10, '1': 950}}, 'indirect_calls': {}, 'array_lengths': {}, 'common_integers': {}}
    apply_value_specialization(prog, profile)
    stmt = prog.items[0].body[0]
    assert stmt.__class__.__name__ == 'IfStmt'
    assert stmt.cond.op == '=='
    assert stmt.cond.right.value == 1


def test_load_value_profile_defaults_when_missing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_value_profile() == {'switch_cases': {}, 'indirect_calls': {}, 'array_lengths': {}, 'common_integers': {}}


def test_build_llvm_opt_value_profile_specializes_hot_match(tmp_path: Path, monkeypatch):
    from astra.build import build

    monkeypatch.chdir(tmp_path)
    src = tmp_path / 'hot_match.astra'
    out = tmp_path / 'hot_match.ll'
    src.write_text(
        """
fn f(x: Int) -> Int {
  match x {
    0 => { return 1; }
    1 => { return 2; }
    _ => { return 3; }
  }
}
fn main() -> Int { return f(7); }
"""
    )
    (tmp_path / '.build').mkdir(exist_ok=True)
    (tmp_path / '.build' / 'value_profile.json').write_text(
        json.dumps({
            'switch_cases': {'f:x': {'0': 1, '1': 999}},
            'indirect_calls': {},
            'array_lengths': {},
            'common_integers': {},
        })
    )
    st = build(str(src), str(out), 'llvm', opt_value_profile=True)
    assert st in {'built', 'cached'}
    ir = out.read_text()
    icmp_lines = [line for line in ir.splitlines() if 'icmp eq i64' in line]
    assert icmp_lines
    assert ', 1' in icmp_lines[0]


def test_value_profile_uses_symbol_to_avoid_fn_name_collisions():
    prog = Program(
        items=[
            FnDecl(
                name='f',
                symbol='f__impl0',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[MatchStmt(expr=Name('x'), arms=[(Literal(0), [ReturnStmt(Literal(0))])])],
            ),
            FnDecl(
                name='f',
                symbol='f__impl1',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[MatchStmt(expr=Name('x'), arms=[(Literal(1), [ReturnStmt(Literal(1))])])],
            ),
        ]
    )
    payload = write_value_profile_template(prog)
    assert 'f__impl0:x' in payload['switch_cases']
    assert 'f__impl1:x' in payload['switch_cases']
