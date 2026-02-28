from astra.parser import parse
from astra.semantic import analyze

SRC = '''
fn main() -> Int {
  let x = 1 + 2;
  print(x);
  return 0;
}
'''

def test_parse_and_analyze():
    prog = parse(SRC)
    analyze(prog)
    assert len(prog.items) == 1
