# std.process

Source: `stdlib/process.astra`

Hosted process/environment helpers:

- `exit(code) -> Never`
- `env(name) -> String`
- `env_or(name, fallback) -> String`
- `cwd() -> String`
- `run(cmd) -> Int`
- `run_ok(cmd) -> Bool`
- `eprintln(msg) -> Int`
