# std.sync

Source: `stdlib/sync.astra`

Status: `experimental` (cooperative hosted lock wrapper)

Functions:

- `mutex_new() -> Any`
- `mutex_lock(m, owner_tid) -> Int`
- `mutex_unlock(m, owner_tid) -> Int`

Notes:

- This is a cooperative lock built on hosted runtime map/sleep primitives.
- `owner_tid` is best-effort ownership metadata.
