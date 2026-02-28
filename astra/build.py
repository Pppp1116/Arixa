import hashlib, json
from pathlib import Path
from astra.parser import parse
from astra.semantic import analyze
from astra.ir import lower
from astra.optimizer import optimize
from astra.codegen import to_python, to_x86_64

CACHE = Path('.astra-cache.json')

def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()

def build(
    src_path: str,
    out_path: str,
    target: str = 'py',
    emit_ir: str | None = None,
    strict: bool = False,
    freestanding: bool = False,
):
    src_file = Path(src_path)
    src = src_file.read_text()
    digest = _hash(src + target + str(bool(emit_ir)) + str(bool(strict)) + str(bool(freestanding)))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get(src_path) == digest and Path(out_path).exists():
        return 'cached'
    prog = parse(src, filename=str(src_file))
    analyze(prog, filename=str(src_file), freestanding=freestanding)
    ir = optimize(lower(prog))
    if emit_ir:
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([{"name": f.name, "ops": f.ops} for f in ir.funcs], indent=2))
    out = to_python(prog, freestanding=freestanding) if target == 'py' else to_x86_64(prog, freestanding=freestanding)
    if strict and "pass\n" in out:
        raise RuntimeError(f"CODEGEN {src_file}:1:1: strict mode rejected generated placeholder code")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(out)
    cache[src_path] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    return 'built'
