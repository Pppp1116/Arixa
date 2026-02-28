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

def build(src_path: str, out_path: str, target: str='py'):
    src = Path(src_path).read_text()
    digest = _hash(src + target)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get(src_path) == digest and Path(out_path).exists():
        return 'cached'
    prog = parse(src)
    analyze(prog)
    optimize(lower(prog))
    out = to_python(prog) if target=='py' else to_x86_64(prog)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(out)
    cache[src_path] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    return 'built'
