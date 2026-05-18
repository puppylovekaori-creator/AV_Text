@echo off
setlocal EnableExtensions

if exist "%~dp0..\avtext_input_pad_winforms\src\AVTextInputPad\bin\Release\net9.0-windows\AVTextInputPad.exe" (
  start "" "%~dp0..\avtext_input_pad_winforms\src\AVTextInputPad\bin\Release\net9.0-windows\AVTextInputPad.exe"
  exit /b 0
)

if exist "%~dp0..\avtext_input_pad_winforms\publish\AVTextInputPad.exe" (
  start "" "%~dp0..\avtext_input_pad_winforms\publish\AVTextInputPad.exe"
  exit /b 0
)

echo AVTextInputPad.exe was not found.
pause
exit /b 1
