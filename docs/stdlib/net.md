# std.net

Source: `stdlib/net.astra`

Status: `experimental` (hosted runtime wrapper)

Hosted TCP helpers:

- `tcp_connect(addr) -> Int`
- `tcp_send(conn, data) -> Int`
- `tcp_send_line(conn, data) -> Int`
- `tcp_recv(conn, size) -> String`
- `tcp_close(conn) -> Int`

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported on POSIX
- Freestanding mode: not supported

Notes:

- Address format: `host:port` or `[ipv6]:port`
- Return values are low-level status/byte counts (`-1` indicates error)
- API is synchronous and connection-handle based
