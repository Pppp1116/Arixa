# std.sync

Source: `stdlib/sync.astra`

Status: `experimental` (runtime-backed hosted mutex wrapper)

Functions:

- `mutex_new() -> Any`
- `mutex_lock(m Any, owner_tid Int) -> Int`
- `mutex_unlock(m Any, owner_tid Int) -> Int`

Notes:

- Backed by runtime mutex primitives in hosted backends.
- `owner_tid` is part of the API shape and is currently passed through as runtime metadata.
