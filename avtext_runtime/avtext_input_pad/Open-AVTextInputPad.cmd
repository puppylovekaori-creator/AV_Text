@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
set "SCRIPT=%BASE_DIR%avtext_input_pad.pyw"
set "RUNTIME_DIR=%BASE_DIR%.."
set "CACHE=%RUNTIME_DIR%\avtext_python_choice.txt"
set "PYW_EXE="
set "PYW_ARGS="

if exist "%CACHE%" (
  set /p CACHED_PY=<"%CACHE%"
  if defined CACHED_PY (
    for %%I in ("!CACHED_PY!") do (
      if exist "%%~dpIpythonw.exe" (
        set "PYW_EXE=%%~dpIpythonw.exe"
        set "PYW_ARGS="
      )
    )
  )
)

if not defined PYW_EXE if exist "%RUNTIME_DIR%\venv\Scripts\pythonw.exe" (
  set "PYW_EXE=%RUNTIME_DIR%\venv\Scripts\pythonw.exe"
)

if not defined PYW_EXE (
  call :try_pyw "pyw" "-3.14"
)

if not defined PYW_EXE (
  call :try_pyw "pythonw" ""
)

if not defined PYW_EXE (
  call :try_pyw "pyw" "-3.13"
)

if not defined PYW_EXE (
  echo pythonw.exe or pyw.exe was not found.
  pause
  exit /b 1
)

start "" "%PYW_EXE%" %PYW_ARGS% "%SCRIPT%"
exit /b 0

:try_pyw
set "CAND_EXE=%~1"
set "CAND_ARGS=%~2"
"%CAND_EXE%" %CAND_ARGS% -c "import tkinter" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYW_EXE=%CAND_EXE%"
set "PYW_ARGS=%CAND_ARGS%"
exit /b 0
