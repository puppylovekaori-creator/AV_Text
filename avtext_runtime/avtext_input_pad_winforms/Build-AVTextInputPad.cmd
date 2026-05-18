@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "PROJECT=%ROOT%src\AVTextInputPad\AVTextInputPad.csproj"
set "PUBLISH=%ROOT%publish"

dotnet publish "%PROJECT%" -c Release -r win-x64 --self-contained false -o "%PUBLISH%"
exit /b %ERRORLEVEL%
