# std.channel

Source: `stdlib/channel.astra`

Status: `experimental` (cooperative queue channel)

Types:

- `Channel`

Functions:

- `channel_new() -> Channel`
- `channel_close(&mut Channel) -> Int`
- `channel_send(&mut Channel, value) -> Int`
- `channel_recv(&mut Channel) -> Option<Any>`

Notes:

- FIFO semantics.
- `channel_recv` returns `none` when currently empty.
