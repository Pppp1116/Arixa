# Memory Model

Astra uses explicit value categories and reference forms tracked by semantic analysis.

Baseline behaviors:

- move-oriented assignment/argument passing for non-copy types
- copy-like behavior for scalar numeric/bool and shared references
- borrow checks for reference reads/writes in safe code
- runtime-backed heap primitives in hosted mode

Relevant implementation: `astra/semantic.py`, `astra/layout.py`, `astra/runtime.py`.
