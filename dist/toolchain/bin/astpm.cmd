@echo off
set "ROOT=%~dp0.."
if defined ASTRA_PYTHON (
  set "PY=%ASTRA_PYTHON%"
) else (
  set "PY=python"
)
set "PYTHONPATH=%ROOT%"
"%PY%" -m astra.pkg %*
