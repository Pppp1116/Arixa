#!/usr/bin/env python3
from pathlib import Path
import shutil


def main() -> int:
    """Sync the canonical runtime C source into the packaged asset location."""
    repo_root = Path(__file__).resolve().parent.parent
    repo_runtime = repo_root / 'runtime/llvm_runtime.c'
    bundled_runtime = repo_root / 'astra/assets/runtime/llvm_runtime.c'
    if not repo_runtime.exists():
        raise SystemExit(f'missing canonical runtime source: {repo_runtime}')
    bundled_runtime.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo_runtime, bundled_runtime)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
