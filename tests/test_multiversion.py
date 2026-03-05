from astra.parser import parse
from astra.llvm_codegen import to_llvm_ir


def test_parse_multiversion_attribute_on_fn():
    prog = parse(
        """
@multiversion
fn hash(x: Int) -> Int {
  let acc = 0;
  for let i = 0; i < x; i += 1 {
    acc += i;
  }
  return acc;
}
fn main() -> Int { return hash(4); }
"""
    )
    fn = prog.items[0]
    assert getattr(fn, "multiversion", False) is True


def test_llvm_cpu_dispatch_generates_variants_and_dispatch():
    prog = parse(
        """
@multiversion
fn hash(x: Int) -> Int {
  let acc = 0;
  for let i = 0; i < x; i += 1 {
    acc += i;
  }
  return acc;
}
fn main() -> Int { return hash(4); }
"""
    )
    ir = to_llvm_ir(prog, cpu_dispatch=True, cpu_target="native")
    assert "@hash_baseline" in ir
    assert "@hash_sse4" in ir
    assert "@hash_avx2" in ir
    assert "@hash_avx512" in ir
    assert "@astra_cpu_has_avx2" in ir
    assert "@astra_cpu_has_avx512" in ir


def test_llvm_cpu_target_avx2_limits_variants():
    prog = parse(
        """
@multiversion
fn hash(x: Int) -> Int {
  let acc = 0;
  for let i = 0; i < x; i += 1 {
    acc += i;
  }
  return acc;
}
fn main() -> Int { return hash(4); }
"""
    )
    ir = to_llvm_ir(prog, cpu_dispatch=True, cpu_target="avx2")
    assert "@hash_avx2" in ir
    assert "@hash_avx512" not in ir


def test_cpu_probe_declarations_use_i32_and_cmp_to_zero():
    prog = parse(
        """
@multiversion
fn hash(x: Int) -> Int {
  let acc = 0;
  for let i = 0; i < x; i += 1 {
    acc += i;
  }
  return acc;
}
fn main() -> Int { return hash(4); }
"""
    )
    ir = to_llvm_ir(prog, cpu_dispatch=True, cpu_target="native")
    assert "declare i32 @astra_cpu_has_avx2()" in ir
    assert "icmp ne i32" in ir


def test_multiversion_candidate_detects_loop_inside_match_arm():
    prog = parse(
        """
@multiversion
fn hash(x: Int) -> Int {
  match x {
    0 => {
      let mut i = 0;
      while i < 3 { i += 1; }
      return i;
    }
    _ => { return x; }
  }
}
fn main() -> Int { return hash(4); }
"""
    )
    ir = to_llvm_ir(prog, cpu_dispatch=True, cpu_target="native")
    assert "@hash_baseline" in ir
