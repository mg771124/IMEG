@echo off
rem ============================================================
rem  IMEG install / update
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"

title IMEG - Install / update environment
setlocal

echo.
echo  ==========================================================
echo    IMEG   Install / update environment
echo  ==========================================================
echo.
echo  [1/5] Looking for Python ...
echo.

set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto :PY_OK
where py >nul 2>nul
if not errorlevel 1 (
    set "RUN=py -3"
    goto :PY_OK
)
where python >nul 2>nul
if not errorlevel 1 (
    set "RUN=python"
    goto :PY_OK
)
echo    [ERROR] Python was not found on this PC.
echo.
echo    Install Python 3.9 or newer first, tick
echo    "Add python.exe to PATH" during setup, then run this
echo    file again:  https://www.python.org/downloads/
echo.
pause
exit /b 1

:PY_OK
if exist "%VPY%" (
    set PYCMD="%VPY%"
    echo    Using virtual env: %VPY%
) else (
    set PYCMD=%RUN%
    echo    Using system Python: %RUN%
)

echo.
echo  [2/5] Creating virtual environment .venv ...
if exist "%VPY%" goto :VENV_DONE
%PYCMD% -m venv .venv
if errorlevel 1 goto :FAIL
if not exist "%VPY%" goto :FAIL
:VENV_DONE
rem install everything into .venv from now on, never into system Python
set PYCMD="%VPY%"
echo    .venv is ready: %VPY%

echo.
echo  [3/5] Upgrading pip (safe to fail) ...
%PYCMD% -m pip install --upgrade pip

echo.
echo  [4/5] Installing numpy / opencv / PySide6 / Pillow / psutil ...
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 goto :FAIL

echo.
set "ANS="
set /p "ANS=Also install OCR (best Chinese accuracy, few hundred MB)? [Y/N] "
if /i "%ANS%"=="Y" (
    echo    Installing OCR modules ...
    %PYCMD% -m pip install -r requirements-ocr.txt
    if errorlevel 1 echo    [WARN] OCR install failed, other features still work.
)

echo.
set "ANS="
set /p "ANS=Also install 'av' (needed by the scrcpy source)? [Y/N] "
if /i "%ANS%"=="Y" (
    echo    Installing av ...
    %PYCMD% -m pip install av
    if errorlevel 1 echo    [WARN] av install failed, scrcpy source will be unavailable.
)

echo.
echo  [5/5] Checking adb (only needed for Android devices) ...
where adb >nul 2>nul
if not errorlevel 1 (
    echo.
    adb version
    goto :ADB_DONE
)
echo    adb not found. Pick any one of these:
echo      * add the platform-tools folder to PATH
echo      * set the ADB or ANDROID_HOME environment variable
echo      * drop adb.exe into tools\platform-tools\
echo.
echo    Without adb you can still use the "emulator window" capture source.
:ADB_DONE

echo.
echo  ==========================================================
echo    Installation finished.
echo.
echo    Run "start.bat" to open the GUI, or "menu.bat"
echo    for the other tools.
echo  ==========================================================
echo.
pause
exit /b 0

:FAIL
echo.
echo  ==========================================================
echo    [ERROR] Installation failed.
echo    Scroll up and send a screenshot of the error.
echo  ==========================================================
echo.
pause
exit /b 1
