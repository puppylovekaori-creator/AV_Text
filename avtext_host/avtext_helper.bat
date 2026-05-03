@echo off
setlocal EnableExtensions

REM ------------------------------------------------------------
REM AVText Native Host launcher (TRACE ENABLED)
REM - Forces running avtext_helper.py in this folder
REM - Writes undeniable trace logs
REM ------------------------------------------------------------

set "HOST_DIR=%~dp0"
set "TRACE=%HOST_DIR%avtext_bat_trace.log"
set "MARK=%HOST_DIR%avtext_bat_ran.marker"
set "PY_FILE=%HOST_DIR%avtext_helper.py"

REM Timestamp
for /f "tokens=1-3 delims=/:. " %%a in ("%date% %time%") do set "TS=%%a-%%b-%%c"
set "NOW=%date% %time%"

>> "%TRACE%" echo ============================================================
>> "%TRACE%" echo [BAT] %NOW%
>> "%TRACE%" echo [BAT] HOST_DIR=%HOST_DIR%
>> "%TRACE%" echo [BAT] CD(before)=%CD%
>> "%TRACE%" echo [BAT] PY_FILE=%PY_FILE%

REM Marker (always updated)
> "%MARK%" echo [BAT] last_run=%NOW%
>> "%MARK%" echo [BAT] HOST_DIR=%HOST_DIR%
>> "%MARK%" echo [BAT] PY_FILE=%PY_FILE%

REM Move working directory to host folder (important)
pushd "%HOST_DIR%"
>> "%TRACE%" echo [BAT] CD(after)=%CD%

REM Detect Python (prefer venv if exists)
set "PY_EXE="
set "PY_ARGS="
if exist "%HOST_DIR%venv\Scripts\python.exe" (
  set "PY_EXE=%HOST_DIR%venv\Scripts\python.exe"
)

if "%PY_EXE%"=="" (
  call :try_python "py" "-3.14"
)

if "%PY_EXE%"=="" (
  call :try_python "python" ""
)

if "%PY_EXE%"=="" (
  call :try_python "py" "-3.13"
)

if "%PY_EXE%"=="" (
  REM Final fallback
  set "PY_EXE=python"
)

>> "%TRACE%" echo [BAT] PY_EXE=%PY_EXE% %PY_ARGS%

REM Show python resolution
>> "%TRACE%" echo [BAT] where python:
where python >> "%TRACE%" 2>&1
>> "%TRACE%" echo [BAT] where py:
where py >> "%TRACE%" 2>&1

>> "%TRACE%" echo [BAT] python --version:
"%PY_EXE%" %PY_ARGS% --version >> "%TRACE%" 2>&1

REM Check the .py existence (hard proof)
if not exist "%PY_FILE%" (
  >> "%TRACE%" echo [BAT][ERROR] avtext_helper.py not found at: %PY_FILE%
  popd
  exit /b 2
)

>> "%TRACE%" echo [BAT] launching: "%PY_EXE%" %PY_ARGS% -u "%PY_FILE%"
>> "%TRACE%" echo ------------------------------------------------------------

REM Run Native Host (stdio). -u for unbuffered.
"%PY_EXE%" %PY_ARGS% -u "%PY_FILE%"

set "RC=%ERRORLEVEL%"
>> "%TRACE%" echo ------------------------------------------------------------
>> "%TRACE%" echo [BAT] exit code=%RC%
>> "%TRACE%" echo ============================================================

popd
exit /b %RC%

:try_python
set "CAND_EXE=%~1"
set "CAND_ARGS=%~2"
>> "%TRACE%" echo [BAT] probe: %CAND_EXE% %CAND_ARGS%
"%CAND_EXE%" %CAND_ARGS% -c "import pyodbc" >> "%TRACE%" 2>&1
if errorlevel 1 (
  exit /b 1
)
set "PY_EXE=%CAND_EXE%"
set "PY_ARGS=%CAND_ARGS%"
exit /b 0
