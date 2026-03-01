import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from astra.comptime import run_comptime
from astra.codegen import to_python, to_x86_64
from astra.ir import lower
from astra.optimizer import optimize, optimize_program
from astra.parser import parse
from astra.semantic import analyze

CACHE = Path('.astra-cache.json')

def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _build_native_x86_64(asm: str, out_path: str, src_file: Path):
    nasm = shutil.which("nasm")
    ld = shutil.which("ld")
    if nasm is None or ld is None:
        raise RuntimeError(f"CODEGEN {src_file}:1:1: native target requires `nasm` and `ld` in PATH")
    runtime_asm = Path(__file__).resolve().parent.parent / "runtime" / "x86_64_linux_runtime.s"
    if not runtime_asm.exists():
        raise RuntimeError(f"CODEGEN {src_file}:1:1: missing runtime object source at {runtime_asm}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="astra-native-") as td:
        asm_path = Path(td) / "module.s"
        obj_path = Path(td) / "module.o"
        rt_obj_path = Path(td) / "runtime.o"
        asm_path.write_text(asm)
        cp = subprocess.run([nasm, "-felf64", str(asm_path), "-o", str(obj_path)], capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: nasm failed{': ' + detail if detail else ''}")
        cp = subprocess.run([nasm, "-felf64", str(runtime_asm), "-o", str(rt_obj_path)], capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: runtime assemble failed{': ' + detail if detail else ''}")
        cp = subprocess.run([ld, str(obj_path), str(rt_obj_path), "-o", str(out)], capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: ld failed{': ' + detail if detail else ''}")
    out.chmod(out.stat().st_mode | 0o111)

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
    run_comptime(prog, filename=str(src_file))
    analyze(prog, filename=str(src_file), freestanding=freestanding)
    optimize_program(prog)
    ir = optimize(lower(prog))
    if emit_ir:
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([{"name": f.name, "ops": f.ops} for f in ir.funcs], indent=2))
    if target == "py":
        out = to_python(prog, freestanding=freestanding)
        if strict and "pass\n" in out:
            raise RuntimeError(f"CODEGEN {src_file}:1:1: strict mode rejected generated placeholder code")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "x86_64":
        out = to_x86_64(prog, freestanding=freestanding)
        if strict and "pass\n" in out:
            raise RuntimeError(f"CODEGEN {src_file}:1:1: strict mode rejected generated placeholder code")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "native":
        asm = to_x86_64(prog, freestanding=freestanding)
        _build_native_x86_64(asm, out_path, src_file)
    else:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported target {target}")
    cache[src_path] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    return 'built'
