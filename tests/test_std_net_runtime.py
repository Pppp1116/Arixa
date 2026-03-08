import shutil
import socket
import sys
import threading

import pytest

from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="std.net parity roundtrip requires clang",
)
def test_std_net_runtime_roundtrip_parity(tmp_path) -> None:
    ready = threading.Event()
    port_box: list[int] = []

    def _server() -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        srv.settimeout(3.0)
        port_box.append(int(srv.getsockname()[1]))
        ready.set()
        try:
            for _ in range(2):
                conn, _ = srv.accept()
                try:
                    _ = conn.recv(16)
                    conn.sendall(b"pong")
                finally:
                    conn.close()
        finally:
            srv.close()

    th = threading.Thread(target=_server, daemon=True)
    th.start()
    assert ready.wait(timeout=3.0)
    assert port_box
    port = port_box[0]

    src = f"""
import "net";

fn main() Int {{
  conn = tcp_connect("127.0.0.1:{port}");
  if conn < 0 {{
    return 101;
  }}
  else {{}}
  sent = tcp_send(conn, "ping");
  recv_len = len(tcp_recv(conn, 4));
  closed = tcp_close(conn);
  if sent == 4 && recv_len == 4 && closed == 0 {{
    return 0;
  }}
  else {{}}
  return 1;
}}
"""
    results = compile_and_run_program(
        tmp_path,
        name="std_net_roundtrip_parity",
        src_text=src,
        backends=("py", "native"),
        timeout=5.0,
    )
    th.join(timeout=3.0)
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=0)


def test_std_net_runtime_error_path_parity(tmp_path) -> None:
    src = """
import "net";

fn main() Int {
  conn = tcp_connect("bad-address");
  sent = tcp_send(99999, "x");
  recv_len = len(tcp_recv(99999, 8));
  closed = tcp_close(99999);
  if conn == -1 && sent == -1 && recv_len == 0 && closed == 0 {
    return 0;
  }
  else {}
  return 1;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="std_net_error_path_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=0)
