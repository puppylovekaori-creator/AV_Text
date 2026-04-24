@echo off
setlocal

rem Native Messaging host launcher (relative path)
py -3 "%~dp0avtext_helper.py"

exit /b %errorlevel%
