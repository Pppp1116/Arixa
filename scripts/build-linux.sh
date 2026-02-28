#!/usr/bin/env bash
set -euo pipefail
python -m pip install -e .
python -m astra.cli build examples/hello.astra -o build/hello.py
python build/hello.py
