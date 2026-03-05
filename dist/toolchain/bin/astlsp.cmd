@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
set "ASTRA_STDLIB_PATH=%ROOT%\\astra\\stdlib"
set "ASTRA_RUNTIME_C_PATH=%ROOT%\\astra\\assets\\runtime\\llvm_runtime.c"
"%PY%" -m astra.lsp %*
