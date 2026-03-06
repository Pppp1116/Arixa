# std.thread

Source: `stdlib/thread.astra`

Status: `partial` (runtime-backed threads)

Functions:

- `spawn0(task) Int`
- `spawn1(task, arg) Int`
- `join_task(tid) Any`
- `yield_now() Int`

Notes:

- Task IDs are runtime handles.
- Native backend executes `spawn` work on OS threads and blocks in `join`.
- Worker signatures are currently `fn() -> Int` and `fn(Int) -> Int` function types via `spawn0`/`spawn1`.
