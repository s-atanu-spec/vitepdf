@echo off
setlocal
title VitePDF installer
if not exist "%~dp0install.ps1" goto notextracted
if not exist "%~dp0vp_core.py" goto notextracted
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo You can close this window.
if "%RC%"=="2" echo Nothing was installed.
if not "%RC%"=="0" if not "%RC%"=="2" echo Installation did not finish. See the message above.
pause
exit /b %RC%

:notextracted
echo Please extract the whole ZIP file first,
echo then run install.bat from the extracted folder.
pause
exit /b 1
