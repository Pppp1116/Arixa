#!/usr/bin/env python3
from pathlib import Path
import shutil


def main() -> int:
    repo_runtime = Path('runtime/llvm_runtime.c')
    bundled_runtime = Path('astra/assets/runtime/llvm_runtime.c')
    if not repo_runtime.exists():
        raise SystemExit(f'missing canonical runtime source: {repo_runtime}')
    bundled_runtime.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo_runtime, bundled_runtime)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
