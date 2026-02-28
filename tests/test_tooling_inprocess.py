import asyncio
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
    src = tmp_path / "a.astra"
    out = tmp_path / "api.md"
    src.write_text("/// docs\nfn main() -> Int { return 0; }\n")
    astra.docgen.main([str(src), "-o", str(out)])
    text = out.read_text()
    assert "# API" in text
    assert "main()" in text
    assert "docs" in text


def test_linter_main_json_output(tmp_path: Path, capsys):
    src = tmp_path / "bad.astra"
    src.write_text("fn main() -> Int {\treturn 0;\n}\n")
    try:
        astra.linter.main([str(src), "--json", "--no-semantic"])
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


def test_cli_main_check_and_build(tmp_path: Path):
    src = tmp_path / "a.astra"
    out = tmp_path / "a.py"
    src.write_text("fn main() -> Int { return 0; }")
    astra.cli.main(["check", str(src)])
    astra.cli.main(["build", str(src), "-o", str(out)])
    assert out.exists()
    try:
        astra.__main__.main(["--help"])
        assert False
    except SystemExit as e:
        assert e.code == 0


def test_lsp_helpers_and_main_dispatch(monkeypatch):
    assert astra.lsp._word_at("fn main() -> Int {}", 0, 1) == "fn"
    diags = astra.lsp._parse_diagnostics('fn main() -> Int { return "x"; }', "<mem>")
    assert diags

    sent = []
    msgs = iter(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": "u", "text": "fn main() -> Int { return 0; }"}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/hover",
                "params": {"textDocument": {"uri": "u"}, "position": {"line": 0, "character": 1}},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "textDocument/completion", "params": {}},
            None,
        ]
    )

    def fake_read():
        return next(msgs)

    def fake_send(msg):
        sent.append(msg)

    monkeypatch.setattr(astra.lsp, "read_msg", fake_read)
    monkeypatch.setattr(astra.lsp, "send", fake_send)
    astra.lsp.main()
    assert any(m.get("id") == 1 for m in sent)
    assert any(m.get("id") == 2 for m in sent)
    assert any(m.get("id") == 3 for m in sent)


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
