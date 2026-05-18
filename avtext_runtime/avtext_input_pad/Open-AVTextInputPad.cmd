@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%avtext_input_pad.pyw"
set "CACHE=%APPDATA%\sakura\avtext\avtext_python_choice.txt"
set "PYW_EXE="

if not exist "%SCRIPT_PATH%" (
  echo avtext_input_pad.pyw was not found.
  pause
  exit /b 1
)

if exist "%CACHE%" (
  set /p PY_EXE=<"%CACHE%"
  if defined PY_EXE if exist "!PY_EXE!" (
    set "PYW_CAND=!PY_EXE:python.exe=pythonw.exe!"
    if exist "!PYW_CAND!" set "PYW_EXE=!PYW_CAND!"
  )
)

if not defined PYW_EXE (
  for %%P in (
    "%LocalAppData%\Programs\Python\Python314\pythonw.exe"
    "%LocalAppData%\Programs\Python\Python313\pythonw.exe"
  ) do (
    if not defined PYW_EXE if exist %%~P set "PYW_EXE=%%~P"
  )
)

if defined PYW_EXE (
  start "" "%PYW_EXE%" "%SCRIPT_PATH%"
  exit /b 0
)

start "" pyw "%SCRIPT_PATH%"
exit /b 0
