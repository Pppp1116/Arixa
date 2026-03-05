import json
from pathlib import Path

from astra.ast import ArrayLit, ExprStmt, FnDecl, Literal, MatchStmt, Name, Program, ReturnStmt
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
    assert any(k.startswith('main__impl0:x:') for k in payload['switch_cases'])


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
    assert any(', 1' in line for line in icmp_lines)


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
    assert any(k.startswith('f__impl0:x:') for k in payload['switch_cases'])
    assert any(k.startswith('f__impl1:x:') for k in payload['switch_cases'])


def test_value_profile_switch_key_includes_site_id_and_legacy_fallback():
    prog = Program(
        items=[
            FnDecl(
                name='main',
                symbol='main__impl0',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[
                    MatchStmt(
                        expr=Name('x'),
                        arms=[(Literal(0), [ReturnStmt(Literal(10))]), (Literal(1), [ReturnStmt(Literal(20))])],
                        line=12,
                        col=7,
                        pos=33,
                    )
                ],
            )
        ]
    )
    payload = write_value_profile_template(prog)
    site_keys = [k for k in payload['switch_cases'] if k.startswith('main__impl0:x:')]
    assert site_keys
    profile = {'switch_cases': {'main__impl0:x': {'0': 1, '1': 999}}, 'indirect_calls': {}, 'array_lengths': {}, 'common_integers': {}}
    apply_value_specialization(prog, profile)
    assert prog.items[0].body[0].__class__.__name__ == 'IfStmt'


def test_value_profile_collects_nested_signals_in_match_arm_body():
    prog = Program(
        items=[
            FnDecl(
                name='main',
                symbol='main__impl0',
                generics=[],
                params=[('x', 'Int')],
                ret='Int',
                body=[
                    MatchStmt(
                        expr=Name('x'),
                        arms=[
                            (Literal(0), [ExprStmt(ArrayLit([Literal(1), Literal(2)])), ReturnStmt(Literal(0))]),
                            (Literal(1), [ReturnStmt(Literal(1))]),
                        ],
                    )
                ],
            )
        ]
    )
    payload = write_value_profile_template(prog)
    assert any(k.startswith('main__impl0:array_literal') for k in payload['array_lengths'])
