@echo off
setlocal EnableExtensions
call "%~dp0run_avtext_python.bat" "%~dp0av_title_convert.py" %*
exit /b %ERRORLEVEL%
