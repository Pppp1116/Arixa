import json
from pathlib import Path

from astra.layout_optimizer import load_profile, optimize_llvm_layout, write_profile_template


def test_profile_template_is_written(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ir = '''define i64 @foo() {
entry:
  br label %bb1
bb1:
  br label %bb2
bb2:
  ret i64 0
}
'''
    payload = write_profile_template(["foo", "bar"], ir)
    profile = tmp_path / ".build" / "astra-profile.json"
    assert profile.exists()
    parsed = json.loads(profile.read_text())
    assert parsed == payload
    assert "foo" in parsed["functions"]
    assert any(k.startswith("foo:") for k in parsed["edges"])


def test_optimize_layout_reorders_functions_by_hotness():
    ir = '''; ModuleID = 'x'

define i64 @cold() {
entry:
  ret i64 0
}

define i64 @hot() {
entry:
  ret i64 1
}
'''
    profile = {"functions": {"hot": 1000, "cold": 1}, "edges": {}, "indirect_calls": {}}
    out = optimize_llvm_layout(ir, profile)
    assert out.find("define i64 @hot()") < out.find("define i64 @cold()")


def test_load_profile_defaults_when_missing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = load_profile()
    assert data == {"functions": {}, "edges": {}, "indirect_calls": {}}


def test_profile_template_accepts_symbol_and_llvm_name_keys(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ir = '''define i64 @__astra_user_main() {
entry:
  ret i64 0
}

define i64 @foo__impl0() {
entry:
  ret i64 0
}
'''
    payload = write_profile_template(["__astra_user_main", "foo__impl0"], ir)
    assert "__astra_user_main" in payload["functions"]
    assert "foo__impl0" in payload["functions"]


def test_build_profile_layout_uses_codegen_function_keys(tmp_path: Path, monkeypatch):
    from astra.build import build

    monkeypatch.chdir(tmp_path)
    src = tmp_path / "m.astra"
    out = tmp_path / "m.ll"
    src.write_text("fn main() -> Int { return 0; }")
    st = build(str(src), str(out), "llvm", profile_layout=True)
    assert st in {"built", "cached"}
    profile = json.loads((tmp_path / ".build" / "astra-profile.json").read_text())
    assert "__astra_user_main" in profile["functions"]


def test_split_blocks_handles_pred_comments_on_labels():
    ir = '''define i64 @f() {
entry:
  br label %bb1
bb1:                                              ; preds = %entry
  ret i64 0
}
'''
    out = optimize_llvm_layout(ir, {"functions": {"f": 1}, "edges": {}, "indirect_calls": {}})
    assert "bb1:" in out


def test_function_name_extractor_handles_quoted_symbols():
    ir = '''define i64 @"with.dot-name"() {
entry:
  ret i64 0
}

define i64 @plain() {
entry:
  ret i64 0
}
'''
    out = optimize_llvm_layout(ir, {"functions": {"with.dot-name": 10, "plain": 1}, "edges": {}, "indirect_calls": {}})
    assert out.find('define i64 @"with.dot-name"()') < out.find('define i64 @plain()')


def test_block_weight_does_not_confuse_bb1_with_bb10():
    ir = '''define i64 @f() {
entry:
  br label %bb1
bb1:
  br label %bb10
bb10:
  ret i64 0
}
'''
    profile = {"functions": {"f": 1}, "edges": {"f:bb10->bb1": 100, "f:bb1->bb10": 1}, "indirect_calls": {}}
    out = optimize_llvm_layout(ir, profile)
    assert "bb1:" in out and "bb10:" in out
