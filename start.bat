@echo off
rem ============================================================
rem  IMEG start GUI
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"

title IMEG - Graphics / Control Tool
setlocal

echo.
echo  Starting IMEG, first launch takes a while ...
echo  (close the window to quit)
echo.

set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto :USE_VENV
where py >nul 2>nul
if not errorlevel 1 goto :USE_PY
where python >nul 2>nul
if not errorlevel 1 goto :USE_PYTHON

echo  [ERROR] Python was not found.
echo.
echo  Run "install.bat" first, then start this file again.
echo.
pause
exit /b 1

:USE_VENV
set PYCMD="%VPY%"
goto :START

:USE_PY
set PYCMD=py -3
goto :START

:USE_PYTHON
set PYCMD=python
goto :START

:START
%PYCMD% -m imeg
if not errorlevel 1 goto :OK

echo.
echo  ----------------------------------------------------------
echo    IMEG exited with an error. Usual causes:
echo.
echo     1. packages missing        - run "install.bat" first
echo     2. no adb / scrcpy        - use the "emulator window" source
echo     3. Chinese OCR missing    - run "install.bat" and add OCR
echo.
echo    The real error message is above, please scroll up.
echo  ----------------------------------------------------------
echo.
pause
exit /b 1

:OK
exit /b 0
