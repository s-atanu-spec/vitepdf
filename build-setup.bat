@echo off
setlocal
title VitePDF Setup builder
rem For the author. Builds VitePDF-Setup-x.y.z.exe, the one-file offline installer.
rem Run install.bat on this computer first.
set "PY=%LOCALAPPDATA%\VitePDF\venv\Scripts\python.exe"
if not exist "%PY%" goto nopython
"%PY%" -I "%~dp0build_setup.py"
echo.
pause
exit /b

:nopython
echo Install VitePDF on this computer first with install.bat (not with Setup.exe),
echo then run this again.
pause
exit /b 1
