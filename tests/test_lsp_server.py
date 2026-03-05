from __future__ import annotations

import json
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from astra import lsp


class LspProc:
    def __init__(self):
        self.p = subprocess.Popen(
            [sys.executable, "-m", "astra.lsp", "--debounce-ms", "80"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def send(self, msg: dict):
        raw = json.dumps(msg)
        body = raw.encode("utf-8")
        payload = f"Content-Length: {len(body)}\r\n\r\n{raw}"
        assert self.p.stdin is not None
        self.p.stdin.write(payload)
        self.p.stdin.flush()

    def recv(self, timeout: float = 1.0):
        assert self.p.stdout is not None
        headers = {}
        ready, _, _ = select.select([self.p.stdout], [], [], timeout)
        if not ready:
            return None
        while True:
            line = self.p.stdout.readline()
            if not line:
                return None
            if line in ("\r\n", "\n", ""):
                break
            k, v = line.split(":", 1)
            headers[k.lower().strip()] = v.strip()
        if "content-length" not in headers:
            return None
        n = int(headers["content-length"])
        body = self.p.stdout.read(n)
        return json.loads(body)

    def close(self):
        try:
            self.send({"jsonrpc": "2.0", "id": 999, "method": "shutdown", "params": {}})
            self.recv(1.0)
            self.send({"jsonrpc": "2.0", "method": "exit", "params": {}})
        finally:
            self.p.kill()
            self.p.wait(timeout=2)


@pytest.mark.parametrize(
    "changes, expected",
    [
        ([{"text": "abc\n"}], "abc\n"),
        (
            [
                {"text": "hello\nworld\n"},
                {
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 5},
                    },
                    "text": "astra",
                },
            ],
            "hello\nastra\n",
        ),
    ],
)
def test_apply_content_changes(changes, expected):
    assert lsp._apply_content_changes("", changes) == expected


def test_apply_content_changes_utf16_positions_with_emoji():
    text = "a🙂b\n"
    out = lsp._apply_content_changes(
        text,
        [
            {
                "range": {
                    "start": {"line": 0, "character": 1},
                    "end": {"line": 0, "character": 3},
                },
                "text": "Z",
            }
        ],
    )
    assert out == "aZb\n"


def test_lsp_initialize_open_change_and_features(tmp_path: Path):
    proc = LspProc()
    try:
        proc.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"workspaceFolders": [{"uri": tmp_path.as_uri(), "name": "ws"}]},
            }
        )
        init = proc.recv(1.5)
        assert init["id"] == 1
        caps = init["result"]["capabilities"]
        assert caps["definitionProvider"] is True
        assert caps["referencesProvider"] is True
        assert caps["renameProvider"] is True

        src = "fn add(x Int) -> Int { return x; }\nfn main() -> Int { let y = add(1); return y; }\n"
        uri = (tmp_path / "a.astra").as_uri()
        proc.send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": uri, "languageId": "astra", "version": 1, "text": src}},
            }
        )

        # consume first diagnostics publish
        first_diag = proc.recv(2.0)
        assert first_diag["method"] == "textDocument/publishDiagnostics"
        assert first_diag["params"]["uri"] == uri

        proc.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "textDocument/definition",
                "params": {"textDocument": {"uri": uri}, "position": {"line": 1, "character": 28}},
            }
        )
        d = proc.recv(1.5)
        assert d["id"] == 2
        assert d["result"] is not None

        proc.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/completion",
                "params": {"textDocument": {"uri": uri}, "position": {"line": 1, "character": 24}},
            }
        )
        c = proc.recv(1.5)
        assert c["id"] == 3
        labels = {x["label"] for x in c["result"]}
        assert "add" in labels
        assert "fn" in labels

        proc.send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "textDocument/rename",
                "params": {
                    "textDocument": {"uri": uri},
                    "position": {"line": 1, "character": 42},
                    "newName": "sum_it",
                },
            }
        )
        r = proc.recv(1.5)
        assert r["id"] == 4
        assert "changes" in r["result"]

        # incremental edit introduces a type error
        proc.send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": 2},
                    "contentChanges": [
                        {
                                "range": {
                                    "start": {"line": 1, "character": 31},
                                    "end": {"line": 1, "character": 32},
                                },
                                "text": '"x"',
                        }
                    ],
                },
            }
        )

        got_semantic_diag = False
        deadline = time.time() + 3.0
        while time.time() < deadline:
            msg = proc.recv(0.5)
            if not msg or msg.get("method") != "textDocument/publishDiagnostics":
                continue
            codes = {d.get("code") for d in msg.get("params", {}).get("diagnostics", [])}
            if codes:
                got_semantic_diag = True
                break
        assert got_semantic_diag
    finally:
        proc.close()


def test_lsp_cancel_request_drops_response(tmp_path: Path):
    proc = LspProc()
    try:
        proc.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        proc.recv(1.5)
        uri = (tmp_path / "c.astra").as_uri()
        proc.send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": uri, "languageId": "astra", "version": 1, "text": "fn main() -> Int { return 0; }\n"}},
            }
        )
        proc.recv(1.5)

        req_id = 55
        proc.send({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": req_id}})
        proc.send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "textDocument/completion",
                "params": {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 3}},
            }
        )

        msg = proc.recv(0.6)
        assert not msg or msg.get("id") != req_id
    finally:
        proc.close()
