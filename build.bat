@echo off
rem ============================================================
rem  IMEG build EXE
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"

title IMEG - Build EXE
setlocal

echo.
echo  ==========================================================
echo    IMEG   Build EXE
echo  ==========================================================
echo.
echo  Output goes to dist\IMEG\ and takes a few minutes.
echo  Do not close this window while it is running.
echo.
echo  [1/2] Looking for Python ...

set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" (
    set PYCMD="%VPY%"
    goto :PY_OK
)
where py >nul 2>nul
if not errorlevel 1 (
    set PYCMD=py -3
    goto :PY_OK
)
where python >nul 2>nul
if not errorlevel 1 (
    set PYCMD=python
    goto :PY_OK
)
echo    [ERROR] Python was not found, run "install.bat" first.
echo.
pause
exit /b 1

:PY_OK
echo    Ready.

echo.
echo  [2/2] Build options ...
echo.
set "ARGS="

set "ANS="
set /p "ANS=  * bundle OCR (rapidocr)? [Y/N] "
if /i "%ANS%"=="Y" set "ARGS=%ARGS% --with-ocr"

set "ANS="
set /p "ANS=  * bundle 'av' for the scrcpy source? [Y/N] "
if /i "%ANS%"=="Y" set "ARGS=%ARGS% --with-av"

set "ANS="
set /p "ANS=  * also pack a zip archive? [Y/N] "
if /i "%ANS%"=="Y" set "ARGS=%ARGS% --zip"

set "ANS="
set /p "ANS=  * sign with a self-signed certificate? [Y/N] "
if /i "%ANS%"=="Y" set "ARGS=%ARGS% --sign-self"

echo.
echo  Running: python -m imeg.tools.build_exe%ARGS%
echo.
%PYCMD% -m imeg.tools.build_exe%ARGS%
if errorlevel 1 goto :FAIL

echo.
echo  ==========================================================
echo    Build finished.
echo.
echo    Output folder: %~dp0dist\IMEG
echo.
echo    Copy the whole IMEG folder to a PC without Python
echo    and double-click IMEG.exe.
echo  ==========================================================
echo.
pause
exit /b 0

:FAIL
echo.
echo  ==========================================================
echo    [ERROR] Build failed.
echo    Scroll up for the PyInstaller error message.
echo  ==========================================================
echo.
pause
exit /b 1
