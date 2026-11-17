@echo off
setlocal
title VitePDF uninstaller
if not defined LOCALAPPDATA goto noprofile
set "ROOT=%LOCALAPPDATA%\VitePDF"
if exist "%ROOT%\venv\Scripts\python.exe" if exist "%ROOT%\app\vitepdf.py" "%ROOT%\venv\Scripts\python.exe" -I "%ROOT%\app\vitepdf.py" --uninstall-console
for %%E in (.jpg .jpeg .jfif .png .heic .heif .webp .bmp .pdf) do reg delete "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\VitePDF" /f >nul 2>&1
reg delete "HKCU\Software\Classes\Directory\Background\shell\VitePDF" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\VitePDF" /f >nul 2>&1
if defined APPDATA del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\VitePDF.lnk" >nul 2>&1
if defined APPDATA del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\VitePDF Capture area.lnk" >nul 2>&1
cd /d "%TEMP%"
echo.
echo Removing the VitePDF folder ...
if exist "%ROOT%\app\vitepdf.py" rmdir /s /q "%ROOT%" & echo VitePDF was removed. & echo If the installer added Python 3.12 and you do not need it, remove it under Settings, Apps. & pause & exit /b 0
echo VitePDF was removed.
pause
exit /b 0

:noprofile
echo The user profile folder could not be found. Nothing was changed.
pause
exit /b 1
