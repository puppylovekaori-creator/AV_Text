@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE_DIR=%~dp0"
set "TRACE=%BASE_DIR%avtext_python_trace.log"
set "TARGET=%~f1"

if "%~1"=="" (
  >> "%TRACE%" echo [ERROR] script path is required.
  exit /b 2
)

if not exist "%TARGET%" (
  >> "%TRACE%" echo [ERROR] script not found: %TARGET%
  exit /b 3
)

shift
set "PASS_ARGS="
:collect_args
if "%~1"=="" goto args_ready
set PASS_ARGS=%PASS_ARGS% "%~1"
shift
goto collect_args

:args_ready
pushd "%BASE_DIR%"

set "PY_EXE="
set "PY_ARGS="

if exist "%BASE_DIR%venv\Scripts\python.exe" (
  call :try_python "%BASE_DIR%venv\Scripts\python.exe" ""
)

if not defined PY_EXE (
  call :try_python "py" "-3.14"
)

if not defined PY_EXE (
  call :try_python "python" ""
)

if not defined PY_EXE (
  call :try_python "py" "-3.13"
)

if not defined PY_EXE (
  set "PY_EXE=python"
)

>> "%TRACE%" echo ============================================================
>> "%TRACE%" echo [RUN] %date% %time%
>> "%TRACE%" echo [RUN] target=%TARGET%
>> "%TRACE%" echo [RUN] python=%PY_EXE% %PY_ARGS%

"%PY_EXE%" %PY_ARGS% -u "%TARGET%" %PASS_ARGS%
set "RC=%ERRORLEVEL%"

>> "%TRACE%" echo [RUN] exit=%RC%
popd
exit /b %RC%

:try_python
set "CAND_EXE=%~1"
set "CAND_ARGS=%~2"
"%CAND_EXE%" %CAND_ARGS% -c "import pyodbc" >nul 2>&1
if errorlevel 1 (
  exit /b 1
)
set "PY_EXE=%CAND_EXE%"
set "PY_ARGS=%CAND_ARGS%"
exit /b 0
