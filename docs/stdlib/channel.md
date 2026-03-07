# std.channel

Source: `stdlib/channel.astra`

Status: `experimental` (runtime-backed hosted FIFO channel)

Types:

- `Channel`

Functions:

- `channel_new() -> Channel`
- `channel_close(&mut Channel) -> Int`
- `channel_send(&mut Channel, value Any) -> Int`
- `channel_recv(&mut Channel) -> Any?`
- `channel_try_recv(&mut Channel) -> Any?`
- `channel_recv_blocking(&mut Channel) -> Any`

Notes:

- FIFO semantics.
- `channel_recv`/`channel_try_recv` return `none` when currently empty.
- Backed by runtime channel primitives in hosted backends (not cooperative list/sleep wrappers).
