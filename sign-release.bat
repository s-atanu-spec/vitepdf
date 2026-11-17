@echo off
setlocal
title VitePDF release signing
rem For the author. Signs this folder and builds the ZIP to share.
rem The first run creates your signing key in Documents\VitePDF-signing.
set "PY=%LOCALAPPDATA%\VitePDF\venv\Scripts\python.exe"
if not exist "%PY%" goto nopython
"%PY%" -I "%~dp0vitepdf_sign.py" release "%~dp0."
echo.
pause
exit /b

:nopython
echo Install VitePDF on this computer first (install.bat), then run this again.
pause
exit /b 1
