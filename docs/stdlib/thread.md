# std.thread

Source: `stdlib/thread.astra`

Status: `experimental` (hosted runtime wrapper)

Functions:

- `spawn0(task) -> Int`
- `spawn1(task, arg) -> Int`
- `join_task(tid) -> Any`
- `yield_now() -> Int`

Notes:

- Task IDs are runtime handles.
- API is cooperative and runtime-dependent.
