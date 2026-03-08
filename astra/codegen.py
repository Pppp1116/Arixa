"""Python backend code generation from analyzed Astra AST programs."""

from __future__ import annotations

import re
from typing import Any

from astra.ast import *
from astra.for_lowering import lower_for_loops
from astra.gpu.kernel_lowering import lower_gpu_kernels
from astra.int_types import parse_int_type_name
from astra.layout import LayoutError, layout_of_type


class CodegenError(Exception):
    """Error type raised by the codegen subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pass


def _diag(node: Any, msg: str) -> str:
    line = getattr(node, "line", 0)
    col = getattr(node, "col", 0)
    return f"CODEGEN <input>:{line}:{col}: {msg}"


BIN_OP_MAP = {"&&": "and", "||": "or"}
_PY_STRUCTS: dict[str, StructDecl] = {}


def _canonical_type(typ: str) -> str:
    t = type_text(typ)
    if t == "Bytes":
        return "Vec<u8>"
    if t.startswith("&mut "):
        return f"&mut {_canonical_type(t[5:])}"
    if t.startswith("&"):
        return f"&{_canonical_type(t[1:])}"
    return t


def _is_gpu_memory_type_name(typ: str) -> bool:
    t = _canonical_type(type_text(typ)).replace(" ", "")
    return t.startswith("GpuBuffer<") or t.startswith("GpuSlice<") or t.startswith("GpuMutSlice<")


def _gpu_barrier_expr(expr: Any) -> bool:
    return (
        isinstance(expr, Call)
        and isinstance(expr.fn, FieldExpr)
        and isinstance(expr.fn.obj, Name)
        and expr.fn.obj.value == "gpu"
        and expr.fn.field == "barrier"
        and len(expr.args) == 0
    )


def _gpu_cuda_expr(expr: Any, *, array_params: set[str]) -> str:
    if isinstance(expr, Name):
        return expr.value
    if isinstance(expr, BoolLit):
        return "True" if expr.value else "False"
    if isinstance(expr, Literal):
        if isinstance(expr.value, (int, float)):
            return repr(expr.value)
        raise CodegenError(_diag(expr, "CUDA lowering only supports numeric literals in kernels"))
    if isinstance(expr, Unary):
        if expr.op == "!":
            return f"(not {_gpu_cuda_expr(expr.expr, array_params=array_params)})"
        if expr.op in {"-", "+", "~"}:
            return f"({expr.op}{_gpu_cuda_expr(expr.expr, array_params=array_params)})"
        raise CodegenError(_diag(expr, f"unsupported unary op `{expr.op}` in CUDA kernel lowering"))
    if isinstance(expr, CastExpr):
        return _gpu_cuda_expr(expr.expr, array_params=array_params)
    if isinstance(expr, TypeAnnotated):
        return _gpu_cuda_expr(expr.expr, array_params=array_params)
    if isinstance(expr, Binary):
        if expr.op == "??":
            raise CodegenError(_diag(expr, "CUDA lowering does not support `??` in kernels"))
        op = BIN_OP_MAP.get(expr.op, expr.op)
        return (
            f"({_gpu_cuda_expr(expr.left, array_params=array_params)} "
            f"{op} "
            f"{_gpu_cuda_expr(expr.right, array_params=array_params)})"
        )
    if isinstance(expr, IndexExpr):
        return (
            f"{_gpu_cuda_expr(expr.obj, array_params=array_params)}"
            f"[{_gpu_cuda_expr(expr.index, array_params=array_params)}]"
        )
    if isinstance(expr, Call):
        if isinstance(expr.fn, FieldExpr) and isinstance(expr.fn.obj, Name):
            obj = expr.fn.obj.value
            field = expr.fn.field
            if obj == "gpu":
                if expr.args:
                    raise CodegenError(_diag(expr, f"gpu.{field} expects 0 args in CUDA lowering"))
                mapping = {
                    "global_id": "cuda.grid(1)",
                    "thread_id": "cuda.threadIdx.x",
                    "block_id": "cuda.blockIdx.x",
                    "block_dim": "cuda.blockDim.x",
                    "grid_dim": "cuda.gridDim.x",
                }
                if field in mapping:
                    return mapping[field]
                if field == "barrier":
                    raise CodegenError(_diag(expr, "gpu.barrier must be used as statement in CUDA lowering"))
            if obj in array_params and field == "len" and len(expr.args) == 0:
                return f"{obj}.shape[0]"
        raise CodegenError(_diag(expr, "unsupported call form in CUDA kernel lowering"))
    if isinstance(expr, MethodCall):
        # Handle method calls like gpu.global_id()
        if isinstance(expr.obj, Name) and expr.obj.value == "gpu":
            if expr.args:
                raise CodegenError(_diag(expr, f"gpu.{expr.method} expects 0 args in CUDA lowering"))
            mapping = {
                "global_id": "cuda.grid(1)",
                "thread_id": "cuda.threadIdx.x",
                "block_id": "cuda.blockIdx.x",
                "block_dim": "cuda.blockDim.x",
                "grid_dim": "cuda.gridDim.x",
            }
            if expr.method in mapping:
                return mapping[expr.method]
            if expr.method == "barrier":
                raise CodegenError(_diag(expr, "gpu.barrier must be used as statement in CUDA lowering"))
        # For other method calls, convert to regular function calls for now
        args_str = ', '.join(_gpu_cuda_expr(a, array_params=array_params) for a in expr.args)
        obj_str = _gpu_cuda_expr(expr.obj, array_params=array_params)
        if args_str:
            return f"{expr.method}({obj_str}, {args_str})"
        return f"{expr.method}({obj_str})"
    raise CodegenError(_diag(expr, f"unsupported CUDA kernel expression {type(expr).__name__}"))


def _gpu_cuda_target(target: Any, *, array_params: set[str]) -> str:
    if isinstance(target, Name):
        return target.value
    if isinstance(target, IndexExpr):
        return (
            f"{_gpu_cuda_expr(target.obj, array_params=array_params)}"
            f"[{_gpu_cuda_expr(target.index, array_params=array_params)}]"
        )
    raise CodegenError(_diag(target, f"unsupported CUDA assignment target {type(target).__name__}"))


def _gpu_cuda_stmts(body: list[Any], *, ind: int, array_params: set[str]) -> list[str]:
    p = "    " * ind
    out: list[str] = []
    for st in body:
        if isinstance(st, LetStmt):
            out.append(f"{p}{st.name} = {_gpu_cuda_expr(st.expr, array_params=array_params)}")
            continue
        if isinstance(st, AssignStmt):
            out.append(
                f"{p}{_gpu_cuda_target(st.target, array_params=array_params)} "
                f"{st.op} "
                f"{_gpu_cuda_expr(st.expr, array_params=array_params)}"
            )
            continue
        if isinstance(st, ExprStmt):
            if _gpu_barrier_expr(st.expr):
                out.append(f"{p}cuda.syncthreads()")
            else:
                out.append(f"{p}{_gpu_cuda_expr(st.expr, array_params=array_params)}")
            continue
        if isinstance(st, IfStmt):
            out.append(f"{p}if {_gpu_cuda_expr(st.cond, array_params=array_params)}:")
            then_lines = _gpu_cuda_stmts(st.then_body, ind=ind + 1, array_params=array_params)
            out.extend(then_lines or [f"{p}    pass"])
            if st.else_body:
                out.append(f"{p}else:")
                else_lines = _gpu_cuda_stmts(st.else_body, ind=ind + 1, array_params=array_params)
                out.extend(else_lines or [f"{p}    pass"])
            continue
        if isinstance(st, WhileStmt):
            out.append(f"{p}while {_gpu_cuda_expr(st.cond, array_params=array_params)}:")
            loop_lines = _gpu_cuda_stmts(st.body, ind=ind + 1, array_params=array_params)
            out.extend(loop_lines or [f"{p}    pass"])
            continue
        if isinstance(st, ReturnStmt):
            if st.expr is None:
                out.append(f"{p}return")
            else:
                out.append(f"{p}return {_gpu_cuda_expr(st.expr, array_params=array_params)}")
            continue
        if isinstance(st, BreakStmt):
            out.append(f"{p}break")
            continue
        if isinstance(st, ContinueStmt):
            out.append(f"{p}continue")
            continue
        raise CodegenError(_diag(st, f"unsupported CUDA kernel statement {type(st).__name__}"))
    return out


def _emit_cuda_kernel_source(item: FnDecl, symbol: str) -> tuple[str, str]:
    if not bool(getattr(item, "gpu_kernel", False)):
        return "", ""
    array_params = {name for name, typ in item.params if _is_gpu_memory_type_name(typ)}
    safe_name = re.sub(r"[^0-9A-Za-z_]", "_", symbol)
    fn_name = f"__astra_cuda_kernel_{safe_name}"
    params = ", ".join(name for name, _ in item.params)
    try:
        body_lines = _gpu_cuda_stmts(item.body, ind=1, array_params=array_params)
    except CodegenError:
        return "", ""
    if not body_lines:
        body_lines = ["    return"]
    src = "\n".join([f"def {fn_name}({params}):", *body_lines, ""]) + "\n"
    return src, fn_name


def to_python(
    prog: Program,
    freestanding: bool = False,
    overflow_mode: str = "trap",
    *,
    emit_entrypoint: bool = True,
) -> str:
    """Lower an analyzed AST program into executable Python source code.
    
    Parameters:
        prog: Program AST to read or mutate.
        freestanding: Whether hosted-runtime features are disallowed.
        overflow_mode: Integer overflow behavior mode requested by the caller.
        emit_entrypoint: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    import sys
    global _PY_STRUCTS
    
    # Note: lower_for_loops is already called in build.py, so we don't call it here again
    gpu_ir_payload = lower_gpu_kernels(prog).to_dict()
    _PY_STRUCTS = {item.name: item for item in prog.items if isinstance(item, StructDecl)}
    main_entry = "main"
    for item in prog.items:
        if isinstance(item, FnDecl) and item.name == "main":
            main_entry = item.symbol or item.name
            break
    lines = [
        "# generated by astra",
        "import asyncio, collections, ctypes, hashlib, hmac, inspect, json, os, pathlib, socket, subprocess, sys, threading, time",
    ]
    
    # Only import GPU runtime if there are GPU kernels
    if gpu_ir_payload.get('kernels'):
        lines.append("from astra.gpu.runtime import get_runtime as _astra_gpu_get_runtime")
    
    lines += [
        "_astra_gpu_runtime = _astra_gpu_get_runtime() if '_astra_gpu_get_runtime' in globals() else None",
        "_astra_heap = {}",
        "_astra_next_ptr = 1",
        "_astra_threads = {}",
        "_astra_next_tid = 1",
        "_astra_atomics = {}",
        "_astra_next_atomic = 1",
        "_astra_mutexes = {}",
        "_astra_next_mutex = 1",
        "_astra_channels = {}",
        "_astra_next_chan = 1",
        "_astra_sockets = {}",
        "_astra_next_sock = 1",
        "_astra_registry_lock = threading.Lock()",
        "_astra_libs = {}",
        "def __astra_cast(v, t):",
        "    if t in ('Float', 'f32', 'f64'):",
        "        return float(v)",
        "    if t in ('Int', 'isize'): bits, signed = 64, True",
        "    elif t == 'usize': bits, signed = 64, False",
        "    elif t.startswith('i') and t[1:].isdigit(): bits, signed = int(t[1:]), True",
        "    elif t.startswith('u') and t[1:].isdigit(): bits, signed = int(t[1:]), False",
        "    else: return v",
        "    if isinstance(v, float):",
        "        if v != v: return 0",
        "        if v == float('inf'):",
        "            return (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1",
        "        if v == float('-inf'):",
        "            return (-(1 << (bits - 1))) if signed else 0",
        "        v = int(v)",
        "    else:",
        "        v = int(v)",
        "    mask = (1 << bits) - 1",
        "    out = v & mask",
        "    if signed and out >= (1 << (bits - 1)):",
        "        out -= (1 << bits)",
        "    return out",
        "def print_(*args): print(*args); return None",
        "def format_(*args): return ' '.join(str(arg) for arg in args)",
        "class _AstraTryNone(Exception):",
        "    pass",
        "class _AstraTryResultErr(Exception):",
        "    def __init__(self, value):",
        "        super().__init__('result-err')",
        "        self.value = value",
        "def __astra_result_err(v):",
        "    return {'__enum__': 'Result', 'tag': 'Err', 'values': [v]}",
        "def __astra_try_unwrap(v):",
        "    if v is None:",
        "        raise _AstraTryNone()",
        "    return v",
        "def __astra_try_unwrap_result(v):",
        "    if isinstance(v, dict) and v.get('__enum__') == 'Result':",
        "        tag = v.get('tag')",
        "        vals = v.get('values')",
        "        if not isinstance(vals, list):",
        "            vals = []",
        "        if tag == 'Ok':",
        "            return vals[0] if vals else None",
        "        if tag == 'Err':",
        "            raise _AstraTryResultErr(vals[0] if vals else None)",
        "    raise TypeError('`!` on Result expected Result.Ok/Result.Err value')",
        "def len_(x): return len(x)",
        "def read_file(p): return pathlib.Path(p).read_text()",
        "def write_file(p,s): pathlib.Path(p).write_text(str(s)); return 0",
        "def args(): return sys.argv",
        "def arg(i): return sys.argv[i] if 0 <= int(i) < len(sys.argv) else ''",
        "def alloc(n):",
        "    global _astra_next_ptr",
        "    with _astra_registry_lock:",
        "        ptr = _astra_next_ptr",
        "        _astra_next_ptr += 1",
        "        _astra_heap[ptr] = bytearray(max(0, int(n)))",
        "        return ptr",
        "def free(ptr):",
        "    _astra_heap.pop(ptr, None)",
        "    return None",
        "def spawn(fn, *a):",
        "    global _astra_next_tid",
        "    with _astra_registry_lock:",
        "        tid = _astra_next_tid",
        "        _astra_next_tid += 1",
        "    state = {'done': False, 'result': 0, 'thread': None}",
        "    def _runner():",
        "        try:",
        "            out = fn(*a)",
        "            if inspect.isawaitable(out):",
        "                out = asyncio.run(out)",
        "            state['result'] = out",
        "        except Exception:",
        "            state['result'] = 0",
        "        finally:",
        "            state['done'] = True",
        "    th = threading.Thread(target=_runner, daemon=False)",
        "    state['thread'] = th",
        "    _astra_threads[tid] = state",
        "    th.start()",
        "    return tid",
        "def join(tid):",
        "    state = _astra_threads.get(int(tid))",
        "    if state is None:",
        "        return 0",
        "    th = state.get('thread')",
        "    if th is not None:",
        "        th.join()",
        "    return state['result']",
        "def await_result(v):",
        "    if inspect.isawaitable(v):",
        "        return asyncio.run(v)",
        "    return v",
        "def atomic_int_new(v):",
        "    global _astra_next_atomic",
        "    with _astra_registry_lock:",
        "        h = _astra_next_atomic",
        "        _astra_next_atomic += 1",
        "        _astra_atomics[h] = int(v)",
        "    return h",
        "def atomic_load(h):",
        "    with _astra_registry_lock:",
        "        return int(_astra_atomics.get(int(h), 0))",
        "def atomic_store(h, v):",
        "    with _astra_registry_lock:",
        "        _astra_atomics[int(h)] = int(v)",
        "    return 0",
        "def atomic_fetch_add(h, delta):",
        "    with _astra_registry_lock:",
        "        key = int(h)",
        "        old = int(_astra_atomics.get(key, 0))",
        "        _astra_atomics[key] = old + int(delta)",
        "    return old",
        "def atomic_compare_exchange(h, expected, desired):",
        "    with _astra_registry_lock:",
        "        key = int(h)",
        "        cur = int(_astra_atomics.get(key, 0))",
        "        if cur == int(expected):",
        "            _astra_atomics[key] = int(desired)",
        "            return True",
        "    return False",
        "def mutex_new():",
        "    global _astra_next_mutex",
        "    with _astra_registry_lock:",
        "        mid = _astra_next_mutex",
        "        _astra_next_mutex += 1",
        "        _astra_mutexes[mid] = threading.Lock()",
        "        return mid",
        "def mutex_lock(mid, owner_tid):",
        "    lk = _astra_mutexes.get(int(mid))",
        "    if lk is None:",
        "        return 1",
        "    lk.acquire()",
        "    return 0",
        "def mutex_unlock(mid, owner_tid):",
        "    lk = _astra_mutexes.get(int(mid))",
        "    if lk is None:",
        "        return 1",
        "    try:",
        "        lk.release()",
        "        return 0",
        "    except RuntimeError:",
        "        return 1",
        "def chan_new():",
        "    global _astra_next_chan",
        "    with _astra_registry_lock:",
        "        cid = _astra_next_chan",
        "        _astra_next_chan += 1",
        "        cv = threading.Condition()",
        "        _astra_channels[cid] = {'q': collections.deque(), 'closed': False, 'cv': cv}",
        "        return cid",
        "def chan_send(cid, v):",
        "    ch = _astra_channels.get(int(cid))",
        "    if ch is None:",
        "        return 1",
        "    cv = ch['cv']",
        "    with cv:",
        "        if ch['closed']:",
        "            return 1",
        "        ch['q'].append(v)",
        "        cv.notify(1)",
        "    return 0",
        "def chan_recv_try(cid):",
        "    ch = _astra_channels.get(int(cid))",
        "    if ch is None:",
        "        return None",
        "    cv = ch['cv']",
        "    with cv:",
        "        if ch['q']:",
        "            return ch['q'].popleft()",
        "        return None",
        "def chan_recv_blocking(cid):",
        "    ch = _astra_channels.get(int(cid))",
        "    if ch is None:",
        "        return None",
        "    cv = ch['cv']",
        "    with cv:",
        "        while not ch['q'] and not ch['closed']:",
        "            cv.wait()",
        "        if ch['q']:",
        "            return ch['q'].popleft()",
        "        return None",
        "def chan_close(cid):",
        "    ch = _astra_channels.get(int(cid))",
        "    if ch is None:",
        "        return 1",
        "    cv = ch['cv']",
        "    with cv:",
        "        ch['closed'] = True",
        "        cv.notify_all()",
        "    return 0",
        "def list_new(): return []",
        "def list_push(xs, v): xs.append(v); return 0",
        "def list_get(xs, i): return xs[int(i)]",
        "def list_set(xs, i, v): xs[int(i)] = v; return 0",
        "def list_len(xs): return len(xs)",
        "def vec_new(): return []",
        "def vec_from(xs): return list(xs)",
        "def vec_len(xs): return len(xs)",
        "def vec_get(xs, i):",
        "    ii = int(i)",
        "    return xs[ii] if 0 <= ii < len(xs) else None",
        "def vec_set(xs, i, v): xs[int(i)] = v; return 0",
        "def vec_push(xs, v): xs.append(v); return 0",
        "def map_new(): return {}",
        "def map_has(m, k): return k in m",
        "def map_get(m, k): return m.get(k)",
        "def map_set(m, k, v): m[k] = v; return 0",
        "def file_exists(p): return pathlib.Path(p).exists()",
        "def file_remove(p):",
        "    try:",
        "        pathlib.Path(p).unlink()",
        "        return 0",
        "    except FileNotFoundError:",
        "        return 1",
        "def _sock_new(s):",
        "    global _astra_next_sock",
        "    with _astra_registry_lock:",
        "        sid = _astra_next_sock",
        "        _astra_next_sock += 1",
        "        _astra_sockets[sid] = s",
        "        return sid",
        "def tcp_connect(addr):",
        "    try:",
        "        host, port = str(addr).rsplit(':', 1)",
        "        s = socket.create_connection((host, int(port)), timeout=5.0)",
        "        return _sock_new(s)",
        "    except Exception:",
        "        return -1",
        "def tcp_send(sid, data):",
        "    s = _astra_sockets.get(int(sid))",
        "    if s is None: return -1",
        "    try:",
        "        return s.send(str(data).encode())",
        "    except Exception:",
        "        return -1",
        "def tcp_recv(sid, n):",
        "    s = _astra_sockets.get(int(sid))",
        "    if s is None: return ''",
        "    try:",
        "        return s.recv(max(1, int(n))).decode(errors='replace')",
        "    except Exception:",
        "        return ''",
        "def tcp_close(sid):",
        "    s = _astra_sockets.pop(int(sid), None)",
        "    if s is None: return 0",
        "    try:",
        "        s.close()",
        "    except Exception:",
        "        return -1",
        "    return 0",
        "def to_json(v): return json.dumps(v, sort_keys=True)",
        "def from_json(s): return json.loads(s)",
        "def sha256(s): return hashlib.sha256(str(s).encode()).hexdigest()",
        "def hmac_sha256(k, s): return hmac.new(str(k).encode(), str(s).encode(), hashlib.sha256).hexdigest()",
        "def rand_bytes(n):",
        "    n = int(n)",
        "    if n < 0:",
        "        return None",
        "    return list(os.urandom(n))",
        "def proc_exit(code): raise SystemExit(int(code))",
        "def panic(msg): import sys; print(f'panic: {msg}', file=sys.stderr); sys.exit(101)",
        "def env_get(k): return os.environ.get(str(k), '')",
        "def cwd(): return os.getcwd()",
        "def proc_run(cmd):",
        "    import shlex",
        "    try:",
        "        if isinstance(cmd, str):",
        "            cmd_list = shlex.split(str(cmd))",
        "        else:",
        "            cmd_list = list(str(arg) for arg in cmd)",
        "        return subprocess.call(cmd_list, shell=False)",
        "    except (ValueError, OSError, subprocess.SubprocessError):",
        "        return -1",
        "def now_unix(): return int(time.time())",
        "def monotonic_ms(): return int(time.monotonic() * 1000)",
        "def sleep_ms(ms): time.sleep(max(0, int(ms)) / 1000.0); return 0",
        "def astra_str_concat(a, b): return str(a) + str(b)",
        "def countOnes(x, bits=64):",
        "    width = max(1, int(bits))",
        "    v = int(x) & ((1 << width) - 1)",
        "    return v.bit_count()",
        "def leadingZeros(x, bits=64):",
        "    width = max(1, int(bits))",
        "    v = int(x) & ((1 << width) - 1)",
        "    if v == 0: return width",
        "    return max(0, width - v.bit_length())",
        "def trailingZeros(x, bits=64):",
        "    width = max(1, int(bits))",
        "    v = int(x) & ((1 << width) - 1)",
        "    if v == 0: return width",
        "    tz = 0",
        "    while (v & 1) == 0:",
        "        v >>= 1",
        "        tz += 1",
        "    return tz",
        "def popcnt(x, bits=64): return countOnes(x, bits)",
        "def clz(x, bits=64): return leadingZeros(x, bits)",
        "def ctz(x, bits=64): return trailingZeros(x, bits)",
        "def rotl(x, n, bits=64):",
        "    width = max(1, int(bits))",
        "    mask = (1 << width) - 1",
        "    v = int(x) & mask",
        "    k = int(n) % width",
        "    return ((v << k) | (v >> ((width - k) % width))) & mask",
        "def rotr(x, n, bits=64):",
        "    width = max(1, int(bits))",
        "    mask = (1 << width) - 1",
        "    v = int(x) & mask",
        "    k = int(n) % width",
        "    return ((v >> k) | (v << ((width - k) % width))) & mask",
        f"_astra_gpu_runtime.register_ir({gpu_ir_payload!r}) if _astra_gpu_runtime is not None else None",
        "class _AstraGpuNamespace:",
        "    def __init__(self, runtime):",
        "        self._runtime = runtime",
        "    def available(self):",
        "        return self._runtime.available() if self._runtime is not None else False",
        "    def device_count(self):",
        "        return self._runtime.device_count() if self._runtime is not None else 0",
        "    def device_name(self, index):",
        "        return self._runtime.device_name(index) if self._runtime is not None else ''",
        "    def alloc(self, size):",
        "        return self._runtime.alloc(size) if self._runtime is not None else None",
        "    def copy(self, host_values):",
        "        return self._runtime.copy(host_values) if self._runtime is not None else None",
        "    def read(self, memory):",
        "        return self._runtime.read(memory) if self._runtime is not None else None",
        "    def launch(self, kernel, grid_size, block_size, *args):",
        "        return self._runtime.launch(kernel, grid_size, block_size, *args) if self._runtime is not None else None",
        "    def global_id(self):",
        "        return self._runtime.global_id() if self._runtime is not None else 0",
        "    def thread_id(self):",
        "        return self._runtime.thread_id() if self._runtime is not None else 0",
        "    def block_id(self):",
        "        return self._runtime.block_id() if self._runtime is not None else 0",
        "    def block_dim(self):",
        "        return self._runtime.block_dim() if self._runtime is not None else 0",
        "    def grid_dim(self):",
        "        return self._runtime.grid_dim() if self._runtime is not None else 0",
        "    def barrier(self):",
        "        return self._runtime.barrier() if self._runtime is not None else None",
        "gpu = _AstraGpuNamespace(_astra_gpu_runtime)",
        "_astra_host_list_new = list_new",
        "_astra_host_list_push = list_push",
        "_astra_host_list_get = list_get",
        "_astra_host_list_set = list_set",
        "_astra_host_list_len = list_len",
        "_astra_host_vec_new = vec_new",
        "_astra_host_vec_from = vec_from",
        "_astra_host_vec_len = vec_len",
        "_astra_host_vec_get = vec_get",
        "_astra_host_vec_set = vec_set",
        "_astra_host_vec_push = vec_push",
        "_astra_host_map_new = map_new",
        "_astra_host_map_has = map_has",
        "_astra_host_map_get = map_get",
        "_astra_host_map_set = map_set",
        "_astra_host_file_exists = file_exists",
        "_astra_host_file_remove = file_remove",
        "_astra_host_tcp_connect = tcp_connect",
        "_astra_host_tcp_send = tcp_send",
        "_astra_host_tcp_recv = tcp_recv",
        "_astra_host_tcp_close = tcp_close",
        "_astra_host_to_json = to_json",
        "_astra_host_from_json = from_json",
        "_astra_host_sha256 = sha256",
        "_astra_host_hmac_sha256 = hmac_sha256",
        "_astra_host_rand_bytes = rand_bytes",
        "_astra_host_proc_exit = proc_exit",
        "_astra_host_env_get = env_get",
        "_astra_host_cwd = cwd",
        "_astra_host_proc_run = proc_run",
        "_astra_host_now_unix = now_unix",
        "_astra_host_monotonic_ms = monotonic_ms",
        "_astra_host_sleep_ms = sleep_ms",
        "_astra_host_countOnes = countOnes",
        "_astra_host_leadingZeros = leadingZeros",
        "_astra_host_trailingZeros = trailingZeros",
        "_astra_host_popcnt = popcnt",
        "_astra_host_clz = clz",
        "_astra_host_ctz = ctz",
        "_astra_host_rotl = rotl",
        "_astra_host_rotr = rotr",
        "_astra_host_atomic_int_new = atomic_int_new",
        "_astra_host_atomic_load = atomic_load",
        "_astra_host_atomic_store = atomic_store",
        "_astra_host_atomic_fetch_add = atomic_fetch_add",
        "_astra_host_atomic_compare_exchange = atomic_compare_exchange",
        "_astra_host_mutex_new = mutex_new",
        "_astra_host_mutex_lock = mutex_lock",
        "_astra_host_mutex_unlock = mutex_unlock",
        "_astra_host_chan_new = chan_new",
        "_astra_host_chan_send = chan_send",
        "_astra_host_chan_recv_try = chan_recv_try",
        "_astra_host_chan_recv_blocking = chan_recv_blocking",
        "_astra_host_chan_close = chan_close",
        "def __list_new(): return _astra_host_list_new()",
        "def __list_push(xs, v): return _astra_host_list_push(xs, v)",
        "def __list_get(xs, i): return _astra_host_list_get(xs, i)",
        "def __list_set(xs, i, v): return _astra_host_list_set(xs, i, v)",
        "def __list_len(xs): return _astra_host_list_len(xs)",
        "def __vec_new(): return _astra_host_vec_new()",
        "def __vec_from(xs): return _astra_host_vec_from(xs)",
        "def __vec_len(xs): return _astra_host_vec_len(xs)",
        "def __vec_get(xs, i): return _astra_host_vec_get(xs, i)",
        "def __vec_set(xs, i, v): return _astra_host_vec_set(xs, i, v)",
        "def __vec_push(xs, v): return _astra_host_vec_push(xs, v)",
        "def __map_new(): return _astra_host_map_new()",
        "def __map_has(m, k): return _astra_host_map_has(m, k)",
        "def __map_get(m, k): return _astra_host_map_get(m, k)",
        "def __map_set(m, k, v): return _astra_host_map_set(m, k, v)",
        "def __file_exists(p): return _astra_host_file_exists(p)",
        "def __file_remove(p): return _astra_host_file_remove(p)",
        "def __tcp_connect(addr): return _astra_host_tcp_connect(addr)",
        "def __tcp_send(sid, data): return _astra_host_tcp_send(sid, data)",
        "def __tcp_recv(sid, n): return _astra_host_tcp_recv(sid, n)",
        "def __tcp_close(sid): return _astra_host_tcp_close(sid)",
        "def __to_json(v): return _astra_host_to_json(v)",
        "def __from_json(s): return _astra_host_from_json(s)",
        "def __sha256(s): return _astra_host_sha256(s)",
        "def __hmac_sha256(k, s): return _astra_host_hmac_sha256(k, s)",
        "def __rand_bytes(n): return _astra_host_rand_bytes(n)",
        "def __proc_exit(code): return _astra_host_proc_exit(code)",
        "def __env_get(k): return _astra_host_env_get(k)",
        "def __cwd(): return _astra_host_cwd()",
        "def __proc_run(cmd): return _astra_host_proc_run(cmd)",
        "def __now_unix(): return _astra_host_now_unix()",
        "def __monotonic_ms(): return _astra_host_monotonic_ms()",
        "def __sleep_ms(ms): return _astra_host_sleep_ms(ms)",
        "def __countOnes(x, bits=64): return _astra_host_countOnes(x, bits)",
        "def __leadingZeros(x, bits=64): return _astra_host_leadingZeros(x, bits)",
        "def __trailingZeros(x, bits=64): return _astra_host_trailingZeros(x, bits)",
        "def __popcnt(x, bits=64): return _astra_host_popcnt(x, bits)",
        "def __clz(x, bits=64): return _astra_host_clz(x, bits)",
        "def __ctz(x, bits=64): return _astra_host_ctz(x, bits)",
        "def __rotl(x, n, bits=64): return _astra_host_rotl(x, n, bits)",
        "def __rotr(x, n, bits=64): return _astra_host_rotr(x, n, bits)",
        "def __atomic_int_new(v): return _astra_host_atomic_int_new(v)",
        "def __atomic_load(h): return _astra_host_atomic_load(h)",
        "def __atomic_store(h, v): return _astra_host_atomic_store(h, v)",
        "def __atomic_fetch_add(h, delta): return _astra_host_atomic_fetch_add(h, delta)",
        "def __atomic_compare_exchange(h, expected, desired): return _astra_host_atomic_compare_exchange(h, expected, desired)",
        "def __mutex_new(): return _astra_host_mutex_new()",
        "def __mutex_lock(mid, owner_tid): return _astra_host_mutex_lock(mid, owner_tid)",
        "def __mutex_unlock(mid, owner_tid): return _astra_host_mutex_unlock(mid, owner_tid)",
        "def __chan_new(): return _astra_host_chan_new()",
        "def __chan_send(cid, v): return _astra_host_chan_send(cid, v)",
        "def __chan_recv_try(cid): return _astra_host_chan_recv_try(cid)",
        "def __chan_recv_blocking(cid): return _astra_host_chan_recv_blocking(cid)",
        "def __chan_close(cid): return _astra_host_chan_close(cid)",
        "def _astra_load_lib(name):",
        "    if name in _astra_libs:",
        "        return _astra_libs[name]",
        "    if name == 'c':",
        "        _astra_libs[name] = ctypes.CDLL(None)",
        "        return _astra_libs[name]",
        "    if sys.platform == 'win32':",
        "        candidates = [f'{name}.dll', f'lib{name}.dll']",
        "    elif sys.platform == 'darwin':",
        "        candidates = [f'lib{name}.dylib', f'lib{name}.so']",
        "    else:",
        "        candidates = [f'lib{name}.so', f'lib{name}.so.0', f'lib{name}.so.1']",
        "    for c in candidates:",
        "        try:",
        "            _astra_libs[name] = ctypes.CDLL(c)",
        "            return _astra_libs[name]",
        "        except OSError:",
        "            continue",
        "    raise OSError(f\"ASTRA FFI: cannot find native library '{name}'\")",
        "def _astra_load_first_lib(names):",
        "    last = None",
        "    for n in names:",
        "        try:",
        "            return _astra_load_lib(n)",
        "        except OSError as err:",
        "            last = err",
        "    if last is not None:",
        "        raise last",
        "    raise OSError('ASTRA FFI: no link libraries were provided')",
    ]
    for item in prog.items:
        if isinstance(item, StructDecl):
            lines.extend(_emit_py_struct(item))
        if isinstance(item, EnumDecl):
            lines.extend(_emit_py_enum(item))
    for item in prog.items:
        if isinstance(item, ExternFnDecl):
            lines.extend(_emit_py_extern(item))
    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        fn_name = item.symbol or item.name
        params = ", ".join(n for n, _ in item.params)
        param_types = [typ for _, typ in item.params]
        if item.async_fn:
            lines.append(f"async def {fn_name}({params}):")
        else:
            lines.append(f"def {fn_name}({params}):")
        lines.append("    _astra_defer_stack = []")
        lines.append("    try:")
        if not item.body:
            lines.append("        pass")
        for st in item.body:
            lines.extend(_stmt_py(st, 2))
        lines.append("    except _AstraTryNone:")
        lines.append("        return None")
        lines.append("    except _AstraTryResultErr as __astra_err:")
        lines.append("        return __astra_result_err(__astra_err.value)")
        lines.append("    finally:")
        lines.append("        for _d in reversed(_astra_defer_stack):")
        lines.append("            _d()")
        cuda_source, cuda_kernel_name = _emit_cuda_kernel_source(item, fn_name)
        if cuda_kernel_name and cuda_source:
            # Emit the CUDA kernel as a Python function
            lines.append(cuda_source)
        if cuda_kernel_name:
            lines.append(
                f"if _astra_gpu_runtime is not None: _astra_gpu_runtime.register_kernel({cuda_kernel_name}, name={item.name!r}, symbol={fn_name!r}, "
                f"params={param_types!r}, ret={type_text(item.ret)!r}, cuda_source={cuda_source!r}, cuda_name={cuda_kernel_name!r})"
            )
            # Always set the kernel marker attribute, even if runtime is not available
            lines.append(
                f"else: setattr({cuda_kernel_name}, '__astra_gpu_kernel__', True); setattr({cuda_kernel_name}, '__astra_gpu_name__', {item.name!r}); setattr({cuda_kernel_name}, '__astra_gpu_symbol__', {fn_name!r})"
            )
    if emit_entrypoint and not freestanding:
        lines.append("if __name__ == '__main__':")
        lines.append(f"    _main_out = {main_entry}()")
        lines.append("    if inspect.isawaitable(_main_out):")
        lines.append("        _main_out = asyncio.run(_main_out)")
        lines.append("    raise SystemExit(_main_out if isinstance(_main_out, int) else 0)")
    return "\n".join(lines) + "\n"


def _emit_py_struct(item: StructDecl) -> list[str]:
    lines = [f"class {item.name}:"]
    fields = [n for n, _ in item.fields]
    args = ", ".join(fields)
    lines.append(f"    def __init__(self, {args}):" if args else "    def __init__(self):")
    if fields:
        for f in fields:
            lines.append(f"        self.{f} = {f}")
    else:
        lines.append("        pass")
    lines.append("    def __repr__(self):")
    if fields:
        fmt = ", ".join(f"{f}={{self.{f}!r}}" for f in fields)
        lines.append(f"        return f\"{item.name}({fmt})\"")
    else:
        lines.append(f"        return '{item.name}()'")
    lines.append("")
    return lines


def _emit_py_enum(item: EnumDecl) -> list[str]:
    lines: list[str] = [f"class {item.name}:"]
    if not item.variants:
        lines.append("    pass")
    for variant, vtypes in item.variants:
        if vtypes:
            lines.append("    @staticmethod")
            lines.append(f"    def {variant}(*values):")
            lines.append(f"        return {{'__enum__': '{item.name}', 'tag': '{variant}', 'values': list(values)}}")
        else:
            lines.append(f"    {variant} = {{'__enum__': '{item.name}', 'tag': '{variant}', 'values': []}}")
    lines.append("")
    return lines


def _emit_py_extern(item: ExternFnDecl) -> list[str]:
    args = ", ".join(n for n, _ in item.params)
    libs = list(item.link_libs)
    if not libs and item.lib:
        libs = [item.lib]
    if not libs:
        libs = ["c"]

    lines = [f"def {item.name}({args}):"]
    lines.append(f"    _lib = _astra_load_first_lib({libs!r})")
    lines.append(f"    _fn = getattr(_lib, {item.name!r})")
    ret_ctype = _extern_ctype_name(item.ret, is_return=True)
    if ret_ctype is None:
        lines.append("    _fn.restype = None")
    else:
        lines.append(f"    _fn.restype = {ret_ctype}")
    if not item.is_variadic:
        argtypes: list[str] = []
        for _, typ in item.params:
            ctype_name = _extern_ctype_name(typ, is_return=False)
            argtypes.append(ctype_name or "ctypes.c_void_p")
        lines.append(f"    _fn.argtypes = [{', '.join(argtypes)}]")
    lines.append(f"    return _fn({', '.join(n for n, _ in item.params)})")
    lines.append("")
    return lines


def _extern_ctype_name(typ: str, *, is_return: bool) -> str | None:
    c = _canonical_type(type_text(typ))
    if c in {"Void", "Never"}:
        return None if is_return else "ctypes.c_void_p"
    ints = {
        "i8": "ctypes.c_int8",
        "i16": "ctypes.c_int16",
        "i32": "ctypes.c_int32",
        "i64": "ctypes.c_int64",
        "u8": "ctypes.c_uint8",
        "u16": "ctypes.c_uint16",
        "u32": "ctypes.c_uint32",
        "u64": "ctypes.c_uint64",
        "Int": "ctypes.c_longlong",
        "isize": "ctypes.c_ssize_t",
        "usize": "ctypes.c_size_t",
        "f32": "ctypes.c_float",
        "Float": "ctypes.c_double",
        "f64": "ctypes.c_double",
        "Bool": "ctypes.c_bool",
    }
    if c in ints:
        return ints[c]
    if c.startswith("*"):
        base = c.lstrip("*")
        depth = len(c) - len(base)
        if depth == 1 and base == "u8":
            return "ctypes.c_char_p"
        return "ctypes.c_void_p"
    return "ctypes.c_void_p"


def _call_name(fn: Any) -> str:
    if isinstance(fn, Name):
        return fn.value
    if isinstance(fn, str):
        return fn
    return _expr(fn)


def _known_py_int_bits(e: Any) -> int:
    inferred = getattr(e, "inferred_type", None)
    if isinstance(inferred, str):
        info = parse_int_type_name(_canonical_type(inferred))
        if info is not None:
            return info[0]
    if isinstance(e, CastExpr):
        info = parse_int_type_name(_canonical_type(e.type_name))
        if info is not None:
            return info[0]
    return 64


def _is_text_expr(e: Any) -> bool:
    if isinstance(e, Literal) and isinstance(e.value, str):
        return True
    inferred = getattr(e, "inferred_type", None)
    if not isinstance(inferred, str):
        return False
    return _canonical_type(inferred) in {"String", "str", "&str"}


def _expr(e: Any) -> str:
    if isinstance(e, BoolLit):
        return "True" if e.value else "False"
    if isinstance(e, NilLit):
        return "None"
    if isinstance(e, SizeOfTypeExpr):
        try:
            return str(layout_of_type(e.type_name, _PY_STRUCTS, mode="query").size)
        except LayoutError as err:
            raise CodegenError(_diag(e, str(err))) from err
    if isinstance(e, AlignOfTypeExpr):
        try:
            return str(layout_of_type(e.type_name, _PY_STRUCTS, mode="query").align)
        except LayoutError as err:
            raise CodegenError(_diag(e, str(err))) from err
    if isinstance(e, BitSizeOfTypeExpr):
        try:
            return str(layout_of_type(e.type_name, _PY_STRUCTS, mode="query").bits)
        except LayoutError as err:
            raise CodegenError(_diag(e, str(err))) from err
    if isinstance(e, MaxValTypeExpr):
        ty = _canonical_type(e.type_name)
        info = parse_int_type_name(ty)
        if info is None:
            raise CodegenError(_diag(e, f"maxVal expects integer type, got {ty}"))
        bits, signed = info
        if signed:
            return str((1 << (bits - 1)) - 1)
        return str((1 << bits) - 1)
    if isinstance(e, MinValTypeExpr):
        ty = _canonical_type(e.type_name)
        info = parse_int_type_name(ty)
        if info is None:
            raise CodegenError(_diag(e, f"minVal expects integer type, got {ty}"))
        bits, signed = info
        if signed:
            return str(-(1 << (bits - 1)))
        return "0"
    if isinstance(e, SizeOfValueExpr):
        ty = getattr(e, "query_type", None) or getattr(e.expr, "inferred_type", None)
        if not isinstance(ty, str):
            raise CodegenError(_diag(e, "unable to resolve static type for size_of(expr)"))
        try:
            return str(layout_of_type(ty, _PY_STRUCTS, mode="query").size)
        except LayoutError as err:
            raise CodegenError(_diag(e, str(err))) from err
    if isinstance(e, AlignOfValueExpr):
        ty = getattr(e, "query_type", None) or getattr(e.expr, "inferred_type", None)
        if not isinstance(ty, str):
            raise CodegenError(_diag(e, "unable to resolve static type for align_of(expr)"))
        try:
            return str(layout_of_type(ty, _PY_STRUCTS, mode="query").align)
        except LayoutError as err:
            raise CodegenError(_diag(e, str(err))) from err
    if isinstance(e, Literal):
        return repr(e.value)
    if isinstance(e, StringInterpolation):
        # Convert to Python f-string equivalent with proper type conversion
        parts = []
        for i, part in enumerate(e.parts):
            if part:
                parts.append(repr(part))
            if i < len(e.exprs):
                expr = e.exprs[i]
                expr_code = _expr(expr)
                # Convert to string if needed
                expr_type = getattr(expr, 'inferred_type', 'Any')
                numeric_types = {
                    'Int', 'isize', 'usize', 'Float', 'f32', 'f64', 'Bool',
                    'i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64'
                }
                if expr_type in numeric_types or (isinstance(expr_type, str) and expr_type.startswith(('i', 'u', 'f'))):
                    expr_code = f"str({expr_code})"
                parts.append(expr_code)
        if not parts:
            return '""'
        if len(parts) == 1:
            return parts[0]
        return " + ".join(parts)
    if isinstance(e, Name):
        return e.value
    if isinstance(e, WildcardPattern):
        raise CodegenError(_diag(e, "wildcard pattern `_` is only valid in match arms"))
    if isinstance(e, OrPattern):
        raise CodegenError(_diag(e, "or-patterns are only valid in match arms"))
    if isinstance(e, GuardedPattern):
        raise CodegenError(_diag(e, "match guards are only valid in match arms"))
    if isinstance(e, AwaitExpr):
        return f"await_result({_expr(e.expr)})"
    if isinstance(e, TryExpr):
        kind = getattr(e, "try_kind", "")
        if kind == "result":
            return f"__astra_try_unwrap_result({_expr(e.expr)})"
        inferred = getattr(e.expr, "inferred_type", "")
        if isinstance(inferred, str) and inferred.startswith("Result<"):
            return f"__astra_try_unwrap_result({_expr(e.expr)})"
        return f"__astra_try_unwrap({_expr(e.expr)})"
    if isinstance(e, CastExpr):
        return f"__astra_cast({_expr(e.expr)}, {_canonical_type(e.type_name)!r})"
    if isinstance(e, TypeAnnotated):
        return f"__astra_cast({_expr(e.expr)}, {_canonical_type(e.type_name)!r})"
    if isinstance(e, Unary):
        if e.op in {"&", "&mut", "*"}:
            # Python backend models references as plain object aliases.
            return _expr(e.expr)
        if e.op == "!":
            return f"(not {_expr(e.expr)})"
        return f"({e.op}{_expr(e.expr)})"
    if isinstance(e, Binary):
        if e.op == "??":
            return f"((lambda __v: __v if __v is not None else {_expr(e.right)})({_expr(e.left)}))"
        if e.op == "+" and _is_text_expr(e.left) and _is_text_expr(e.right):
            return f"astra_str_concat({_expr(e.left)}, {_expr(e.right)})"
        op = BIN_OP_MAP.get(e.op, e.op)
        return f"({_expr(e.left)} {op} {_expr(e.right)})"
    if isinstance(e, Call):
        name = e.resolved_name or _call_name(e.fn)
        args = list(e.args)
        ufcs_receiver = getattr(e, "ufcs_receiver", None)
        if ufcs_receiver is not None:
            args = [ufcs_receiver] + args
        if name == "panic" and len(args) == 1:
            return f"panic({_expr(args[0])})"
        if name == "format":
            # Handle format function with string interpolation support
            if len(args) == 1 and isinstance(args[0], StringInterpolation):
                # Single string interpolation argument
                return _expr(args[0])
            else:
                # Multiple arguments - join with spaces
                exprs = [_expr(arg) for arg in args]
                # Convert non-string expressions to string
                for i, (arg, expr) in enumerate(zip(args, exprs)):
                    arg_type = getattr(arg, 'inferred_type', 'Any')
                    # Also check literal values
                    if isinstance(arg, Literal):
                        if isinstance(arg.value, (int, float, bool)):
                            exprs[i] = f"str({expr})"
                    elif arg_type in {'Int', 'isize', 'usize', 'Float', 'f64', 'Bool'}:
                        exprs[i] = f"str({expr})"
                    # Handle boolean literals that might have lost type info
                    elif expr == "True" or expr == "False":
                        exprs[i] = f"str({expr})"
                return " + ' ' + ".join(exprs) if len(exprs) > 1 else exprs[0]
        if name in {
            "countOnes",
            "__countOnes",
            "leadingZeros",
            "__leadingZeros",
            "trailingZeros",
            "__trailingZeros",
            "popcnt",
            "__popcnt",
            "clz",
            "__clz",
            "ctz",
            "__ctz",
        } and len(args) == 1:
            bits = _known_py_int_bits(args[0])
            return f"{name}({_expr(args[0])}, {bits})"
        if name in {"rotl", "__rotl", "rotr", "__rotr"} and len(args) == 2:
            bits = _known_py_int_bits(args[0])
            return f"{name}({_expr(args[0])}, {_expr(args[1])}, {bits})"
        name = {"print": "print_", "format": "format_", "len": "len_"}.get(name, name)
        return f"{name}({', '.join(_expr(a) for a in args)})"
    if isinstance(e, IndexExpr):
        return f"({_expr(e.obj)})[{_expr(e.index)}]"
    if isinstance(e, FieldExpr):
        return f"({_expr(e.obj)}).{e.field}"
    if isinstance(e, ArrayLit):
        return f"[{', '.join(_expr(x) for x in e.elements)}]"
    if isinstance(e, StructLit):
        decl = _PY_STRUCTS.get(e.name)
        field_map: dict[str, Any] = {}
        for fname, fexpr in e.fields:
            if fname in field_map:
                raise CodegenError(_diag(e, f"duplicate field {fname} in struct literal {e.name}"))
            field_map[fname] = fexpr
        if decl is not None:
            ordered_args: list[str] = []
            declared = {fname for fname, _ in decl.fields}
            for fname in field_map:
                if fname not in declared:
                    raise CodegenError(_diag(e, f"unknown field {fname} in struct literal {e.name}"))
            for fname, _ in decl.fields:
                if fname not in field_map:
                    raise CodegenError(_diag(e, f"missing field {fname} in struct literal {e.name}"))
                ordered_args.append(_expr(field_map[fname]))
            return f"{e.name}({', '.join(ordered_args)})"
        return f"{e.name}({', '.join(_expr(v) for _, v in e.fields)})"
    if isinstance(e, MethodCall):
        # Handle method calls like gpu.global_id()
        if isinstance(e.obj, Name) and e.obj.value == "gpu":
            # Convert GPU method calls to regular function calls
            args_str = ', '.join(_expr(a) for a in e.args)
            return f"gpu.{e.method}({args_str})"
        # For other method calls, convert to regular function calls for now
        args_str = ', '.join(_expr(a) for a in e.args)
        obj_str = _expr(e.obj)
        if args_str:
            return f"{e.method}({obj_str}, {args_str})"
        return f"{e.method}({obj_str})"
    if isinstance(e, VectorLiteral):
        # Convert vector literals to Python lists
        return f"[{', '.join(_expr(x) for x in e.elements)}]"
    raise CodegenError(_diag(e, f"unsupported expression {type(e).__name__}"))


def _target_expr(t: Any) -> str:
    if isinstance(t, Name):
        return t.value
    if isinstance(t, IndexExpr):
        return f"({_expr(t.obj)})[{_expr(t.index)}]"
    if isinstance(t, FieldExpr):
        return f"({_expr(t.obj)}).{t.field}"
    return _expr(t)


def _match_cond_py(match_value_name: str, pat: Any) -> str:
    if isinstance(pat, Name):
        return "True"
    if isinstance(pat, WildcardPattern):
        return "True"
    if isinstance(pat, OrPattern):
        conds = [_match_cond_py(match_value_name, p) for p in pat.patterns]
        if not conds:
            return "False"
        return f"({' or '.join(conds)})"
    if isinstance(pat, GuardedPattern):
        return _match_cond_py(match_value_name, pat.pattern)
    if isinstance(pat, FieldExpr) and isinstance(pat.obj, Name):
        enum_name = pat.obj.value
        variant_name = pat.field
        return (
            f"(isinstance({match_value_name}, dict) and "
            f"{match_value_name}.get('__enum__') == {enum_name!r} and "
            f"{match_value_name}.get('tag') == {variant_name!r} and "
            f"len({match_value_name}.get('values', [])) == 0)"
        )
    if isinstance(pat, Call) and isinstance(pat.fn, FieldExpr) and isinstance(pat.fn.obj, Name):
        enum_name = pat.fn.obj.value
        variant_name = pat.fn.field
        vals = f"{match_value_name}.get('values', [])"
        parts = [
            f"isinstance({match_value_name}, dict)",
            f"{match_value_name}.get('__enum__') == {enum_name!r}",
            f"{match_value_name}.get('tag') == {variant_name!r}",
            f"len({vals}) == {len(pat.args)}",
        ]
        for i, sub in enumerate(pat.args):
            parts.append(_match_cond_py(f"{vals}[{i}]", sub))
        return f"({' and '.join(parts)})"
    if isinstance(pat, Call) and isinstance(pat.fn, Name) and pat.fn.value in _PY_STRUCTS:
        struct_name = pat.fn.value
        decl = _PY_STRUCTS[struct_name]
        if len(pat.args) != len(decl.fields):
            return "False"
        parts = [f"isinstance({match_value_name}, {struct_name})"]
        for (fname, _), sub in zip(decl.fields, pat.args):
            parts.append(_match_cond_py(f"({match_value_name}).{fname}", sub))
        return f"({' and '.join(parts)})"
    return f"{match_value_name} == {_expr(pat)}"


def _split_match_pattern_py(pat: Any) -> tuple[list[Any], Any | None]:
    if isinstance(pat, GuardedPattern):
        return _flatten_or_pattern_py(pat.pattern), pat.guard
    return _flatten_or_pattern_py(pat), None


def _flatten_or_pattern_py(pat: Any) -> list[Any]:
    if isinstance(pat, OrPattern):
        out: list[Any] = []
        for p in pat.patterns:
            out.extend(_flatten_or_pattern_py(p))
        return out
    return [pat]


def _match_bindings_py(match_value_name: str, pat: Any) -> list[tuple[str, str]]:
    if isinstance(pat, Name):
        if pat.value == "_":
            return []
        return [(pat.value, match_value_name)]
    if isinstance(pat, WildcardPattern):
        return []
    if isinstance(pat, GuardedPattern):
        return _match_bindings_py(match_value_name, pat.pattern)
    if isinstance(pat, FieldExpr) and isinstance(pat.obj, Name):
        return []
    if isinstance(pat, Call) and isinstance(pat.fn, FieldExpr) and isinstance(pat.fn.obj, Name):
        vals = f"{match_value_name}.get('values', [])"
        out: list[tuple[str, str]] = []
        for i, sub in enumerate(pat.args):
            out.extend(_match_bindings_py(f"{vals}[{i}]", sub))
        return out
    if isinstance(pat, Call) and isinstance(pat.fn, Name) and pat.fn.value in _PY_STRUCTS:
        struct_name = pat.fn.value
        decl = _PY_STRUCTS[struct_name]
        if len(pat.args) != len(decl.fields):
            return []
        out: list[tuple[str, str]] = []
        for (fname, _), sub in zip(decl.fields, pat.args):
            out.extend(_match_bindings_py(f"({match_value_name}).{fname}", sub))
        return out
    return []


def _has_unconditional_wildcard(pat: Any) -> bool:
    if isinstance(pat, WildcardPattern):
        return True
    if isinstance(pat, GuardedPattern):
        return False
    return False


def _stmt_py(st: Any, ind: int) -> list[str]:
    p = "    " * ind
    if isinstance(st, LetStmt):
        return [f"{p}{st.name} = {_expr(st.expr)}"]
    if isinstance(st, AssignStmt):
        return [f"{p}{_target_expr(st.target)} {st.op} {_expr(st.expr)}"]
    if isinstance(st, ReturnStmt):
        return [f"{p}return {_expr(st.expr) if st.expr else 'None'}"]
    if isinstance(st, BreakStmt):
        return [f"{p}break"]
    if isinstance(st, ContinueStmt):
        return [f"{p}continue"]
    if isinstance(st, DeferStmt):
        return [f"{p}_astra_defer_stack.append(lambda: {_expr(st.expr)})"]
    if isinstance(st, UnsafeStmt):
        lines: list[str] = []
        for s in st.body:
            lines.extend(_stmt_py(s, ind))
        return lines
    if isinstance(st, ComptimeStmt):
        return []
    if isinstance(st, ExprStmt):
        return [f"{p}{_expr(st.expr)}"]
    if isinstance(st, IfStmt):
        lines = [f"{p}if {_expr(st.cond)}:"]
        if st.then_body:
            for s in st.then_body:
                lines.extend(_stmt_py(s, ind + 1))
        else:
            lines.append(f"{'    ' * (ind + 1)}pass")
        if st.else_body:
            lines.append(f"{p}else:")
            for s in st.else_body:
                lines.extend(_stmt_py(s, ind + 1))
        return lines
    if isinstance(st, MatchStmt):
        match_name = f"__match_value_{ind}"
        matched_name = f"__match_done_{ind}"
        lines = [f"{p}{match_name} = {_expr(st.expr)}", f"{p}{matched_name} = False"]
        for _, (pat, body) in enumerate(st.arms):
            alts, guard = _split_match_pattern_py(pat)
            lines.append(f"{p}if not {matched_name}:")
            for j, alt in enumerate(alts):
                head = "if" if j == 0 else "elif"
                lines.append(f"{'    ' * (ind + 1)}{head} {_match_cond_py(match_name, alt)}:")
                bindings = _match_bindings_py(match_name, alt)
                for bname, bexpr in bindings:
                    lines.append(f"{'    ' * (ind + 2)}{bname} = {bexpr}")
                if guard is not None:
                    lines.append(f"{'    ' * (ind + 2)}if {_expr(guard)}:")
                    lines.append(f"{'    ' * (ind + 3)}{matched_name} = True")
                    if body:
                        for s in body:
                            lines.extend(_stmt_py(s, ind + 3))
                    else:
                        lines.append(f"{'    ' * (ind + 3)}pass")
                else:
                    lines.append(f"{'    ' * (ind + 2)}{matched_name} = True")
                    if body:
                        for s in body:
                            lines.extend(_stmt_py(s, ind + 2))
                    else:
                        lines.append(f"{'    ' * (ind + 2)}pass")
            if not alts:
                lines.append(f"{'    ' * (ind + 1)}pass")
        return lines
    if isinstance(st, WhileStmt):
        lines = [f"{p}while {_expr(st.cond)}:"]
        for s in st.body:
            lines.extend(_stmt_py(s, ind + 1))
        if not st.body:
            lines.append(f"{'    ' * (ind + 1)}pass")
        return lines
    if isinstance(st, ForStmt):
        raise CodegenError(_diag(st, "internal: unlowered for-in loop"))
    raise CodegenError(_diag(st, f"unsupported statement {type(st).__name__}"))
