import json
import re
import sys

from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


KEYWORDS = [
    "fn",
    "let",
    "return",
    "if",
    "else",
    "while",
    "for",
    "break",
    "continue",
    "struct",
    "enum",
    "type",
    "import",
    "mut",
    "pub",
    "extern",
    "async",
    "await",
    "unsafe",
    "match",
    "nil",
]


def send(msg):
    b = json.dumps(msg).encode()
    sys.stdout.write(f"Content-Length: {len(b)}\r\n\r\n")
    sys.stdout.write(b.decode())
    sys.stdout.flush()


def read_msg():
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        if line in ("\r\n", "\n", ""):
            break
        k, v = line.split(":", 1)
        headers[k.lower().strip()] = v.strip()
    n = int(headers.get("content-length", "0"))
    if n == 0:
        return None
    return json.loads(sys.stdin.read(n))


def _parse_diagnostics(text: str, uri: str):
    try:
        prog = parse(text, filename=uri)
        analyze(prog, filename=uri)
        return []
    except (ParseError, SemanticError) as e:
        out = []
        for line in str(e).splitlines():
            m = re.match(r"^[A-Z]+\s+(.+):(\d+):(\d+):\s+(.*)$", line.strip())
            if not m:
                continue
            ln = max(1, int(m.group(2)))
            col = max(1, int(m.group(3)))
            msg = m.group(4)
            out.append(
                {
                    "range": {
                        "start": {"line": ln - 1, "character": col - 1},
                        "end": {"line": ln - 1, "character": col},
                    },
                    "severity": 1,
                    "source": "astra",
                    "message": msg,
                }
            )
        return out


def _word_at(text: str, line: int, character: int) -> str:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    row = lines[line]
    if not row:
        return ""
    pos = min(max(0, character), len(row) - 1)
    if not (row[pos].isalnum() or row[pos] == "_"):
        return ""
    s = pos
    e = pos
    while s > 0 and (row[s - 1].isalnum() or row[s - 1] == "_"):
        s -= 1
    while e + 1 < len(row) and (row[e + 1].isalnum() or row[e + 1] == "_"):
        e += 1
    return row[s : e + 1]


def main(argv=None):
    docs: dict[str, str] = {}
    while True:
        msg = read_msg()
        if not msg:
            break
        method = msg.get("method")
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {
                        "capabilities": {
                            "textDocumentSync": 1,
                            "hoverProvider": True,
                            "completionProvider": {"resolveProvider": False},
                        }
                    },
                }
            )
            continue
        if method == "textDocument/didOpen":
            td = msg.get("params", {}).get("textDocument", {})
            uri = td.get("uri", "<memory>")
            text = td.get("text", "")
            docs[uri] = text
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": _parse_diagnostics(text, uri)}})
            continue
        if method == "textDocument/didChange":
            params = msg.get("params", {})
            uri = params.get("textDocument", {}).get("uri", "<memory>")
            changes = params.get("contentChanges", [])
            if changes:
                docs[uri] = changes[-1].get("text", "")
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics", "params": {"uri": uri, "diagnostics": _parse_diagnostics(docs.get(uri, ""), uri)}})
            continue
        if method == "textDocument/hover":
            params = msg.get("params", {})
            uri = params.get("textDocument", {}).get("uri", "<memory>")
            pos = params.get("position", {})
            symbol = _word_at(docs.get(uri, ""), pos.get("line", 0), pos.get("character", 0))
            if symbol in KEYWORDS:
                contents = f"`{symbol}` keyword"
            elif symbol:
                contents = f"Astra symbol `{symbol}`"
            else:
                contents = "Astra source"
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"contents": contents}})
            continue
        if method == "textDocument/completion":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": [{"label": k, "kind": 14, "detail": "keyword"} for k in KEYWORDS],
                }
            )
            continue
        if "id" in msg:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": None})


if __name__ == "__main__":
    main()
