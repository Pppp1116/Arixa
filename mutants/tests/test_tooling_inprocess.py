import asyncio
import logging
from pathlib import Path

import astra.__main__
import astra.cli
import astra.debugger
import astra.docgen
import astra.linter
import astra.lsp
import astra.pkg
import astra.profiler
import astra.runtime


def test_docgen_main_writes_output(tmp_path: Path):
    src = tmp_path / "a.arixa"
    out = tmp_path / "api.md"
    src.write_text("/// docs\nfn main() Int{ return 0; }\n")
    astra.docgen.main([str(src), "-o", str(out)])
    text = out.read_text()
    assert "# API" in text
    assert "main()" in text
    assert "docs" in text


def test_linter_main_json_output(tmp_path: Path, capsys):
    src = tmp_path / "bad.arixa"
    src.write_text("fn main() Int{\treturn 0;\n}\n")
    try:
        astra.linter.main([str(src), "--json", "--no-semantic"])
        assert False
    except SystemExit as e:
        assert e.code == 1
    out = capsys.readouterr().out
    assert "tab character not allowed" in out


def test_linter_main_accepts_directory(tmp_path: Path, capsys):
    src = tmp_path / "bad.arixa"
    src.write_text("fn main() Int{\treturn 0;\n}\n")
    try:
        astra.linter.main([str(tmp_path), "--json", "--no-semantic"])
        assert False
    except SystemExit as e:
        assert e.code == 1
    out = capsys.readouterr().out
    assert "tab character not allowed" in out


def test_pkg_main_roundtrip(tmp_path: Path):
    prev = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        astra.pkg.main(["init", "demo"])
        astra.pkg.main(["add", "dep_a", "0.1.0"])
        astra.pkg.main(["lock"])
        assert (tmp_path / "Astra.toml").exists()
        assert (tmp_path / "Astra.lock").exists()
    finally:
        os.chdir(prev)


def test_cli_pkg_dispatch_roundtrip(tmp_path: Path):
    prev = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        astra.cli.main(["pkg", "init", "demo"])
        astra.cli.main(["pkg", "add", "dep_a", "0.1.0"])
        astra.cli.main(["pkg", "verify"])
        assert (tmp_path / "Astra.toml").exists()
        assert (tmp_path / "Astra.lock").exists()
    finally:
        os.chdir(prev)


def test_cli_main_check_and_build(tmp_path: Path):
    src = tmp_path / "a.arixa"
    out = tmp_path / "a.py"
    src.write_text("fn main() Int{ return 0; }")
    astra.cli.main(["check", str(src)])
    astra.cli.main(["build", str(src), "-o", str(out)])
    assert out.exists()
    try:
        astra.__main__.main(["--help"])
        assert False
    except SystemExit as e:
        assert e.code == 0


def test_lsp_helpers_and_main_dispatch(monkeypatch):
    assert astra.lsp._word_at("fn main() Int{}", 0, 1) == "fn"
    diags = astra.lsp._parse_diagnostics('fn main() Int{ return "x"; }', "<mem>")
    assert diags
    assert diags[0]["code"] == "E0100"

    src = (
        "fn add(x Int) Int{ return x; }\n"
        "struct S { v: Int }\n"
        "enum E { A }\n"
        "fn main() Int{\n"
        "  y = add(1);\n"
        "  return y;\n"
        "}\n"
    )

    sent = []
    def fake_send(msg):
        sent.append(msg)

    monkeypatch.setattr(astra.lsp, "send", fake_send)
    log = logging.getLogger("astlsp-test")
    log.handlers.clear()
    log.addHandler(logging.NullHandler())
    srv = astra.lsp.LSPServer(log=log, debounce_ms=1)
    srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    srv.handle({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": "u", "version": 1, "text": src}}})
    srv._due_tasks()
    srv.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/hover",
            "params": {"textDocument": {"uri": "u"}, "position": {"line": 5, "character": 9}},
        }
    )
    srv.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "textDocument/completion",
            "params": {"textDocument": {"uri": "u"}, "position": {"line": 5, "character": 3}},
        }
    )
    srv.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "textDocument/definition",
            "params": {"textDocument": {"uri": "u"}, "position": {"line": 4, "character": 7}},
        }
    )
    by_id = {m.get("id"): m for m in sent if m.get("id") is not None}
    assert by_id[1]["result"]["capabilities"]["definitionProvider"] is True
    assert by_id[1]["result"]["capabilities"]["codeActionProvider"] is True
    assert "Int" in by_id[2]["result"]["contents"]["value"]
    labels = {x["label"] for x in by_id[3]["result"]}
    assert {"y", "add", "S", "E", "print", "fn"} <= labels
    assert by_id[4]["result"] is not None

    semicolon_diags = astra.lsp._parse_diagnostics("fn main() Int{ x = 1 return 0; }", "u")
    assert semicolon_diags
    assert semicolon_diags[0]["code"] == "E0301"
    action_result = srv._code_actions(
        {
            "textDocument": {"uri": "u"},
            "context": {"diagnostics": semicolon_diags},
        }
    )
    assert action_result
    assert action_result[0]["kind"] == "quickfix"


def test_debugger_and_profiler_and_runtime(tmp_path: Path):
    script = tmp_path / "s.py"
    script.write_text("x = 1 + 2\n")
    astra.profiler.main([str(script)])
    astra.debugger.main([str(script)])

    fut = astra.runtime.spawn(lambda x: x + 1, 41)
    assert fut.result(timeout=2) == 42
    out = asyncio.run(astra.runtime.run_async(asyncio.sleep(0, result=7)))
    assert out == 7
    astra.runtime.shutdown()
