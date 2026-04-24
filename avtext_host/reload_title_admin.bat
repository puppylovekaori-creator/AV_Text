@echo off
setlocal

set "SAKURA_EXE="

rem ???????????
if exist "%ProgramFiles%\sakura\sakura.exe" set "SAKURA_EXE=%ProgramFiles%\sakura\sakura.exe"
if not defined SAKURA_EXE if exist "%ProgramFiles(x86)%\sakura\sakura.exe" set "SAKURA_EXE=%ProgramFiles(x86)%\sakura\sakura.exe"

rem PATH??????
if not defined SAKURA_EXE for /f "delims=" %%P in ('where sakura.exe 2^>nul') do (
  set "SAKURA_EXE=%%P"
  goto :FOUND
)

:FOUND
if not defined SAKURA_EXE exit /b 2

"%SAKURA_EXE%" "-M=%~dp0reload_title_admin.mac" "-MTYPE=file"
exit /b %ERRORLEVEL%
