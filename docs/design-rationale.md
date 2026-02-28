# Design Rationale

- Bootstrap in Python enables fast iteration and reproducibility.
- Syntax is intentionally compact and C-like for easy parsing.
- Deterministic builds come from sorted lockfiles and stable hashing.
- Self-hosting path is staged: bootstrap compiler compiles an Astra compiler artifact and verifies recursive compilation flow.
