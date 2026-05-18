@echo off
setlocal EnableExtensions
call "%~dp0run_avtext_python.bat" "%~dp0avtext_daemon_client.py" no_title %*
exit /b %ERRORLEVEL%
