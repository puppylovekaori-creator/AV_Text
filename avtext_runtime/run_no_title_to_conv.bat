@echo off
setlocal EnableExtensions
call "%~dp0run_avtext_python.bat" "%~dp0no_title_to_conv.py" %*
exit /b %ERRORLEVEL%
