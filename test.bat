@echo off
rem ============================================================
rem  IMEG run tests
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"

title IMEG - Run tests
setlocal

echo.
echo  ==========================================================
echo    IMEG   Run tests
echo  ==========================================================
echo.

set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto :USE_VENV
where py >nul 2>nul
if not errorlevel 1 goto :USE_PY
where python >nul 2>nul
if not errorlevel 1 goto :USE_PYTHON
echo  [ERROR] Python was not found, run "install.bat" first.
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
%PYCMD% -c "import pytest" >nul 2>nul
if not errorlevel 1 goto :RUN
echo  pytest is missing, installing it ...
%PYCMD% -m pip install pytest
if errorlevel 1 goto :FAIL

:RUN
echo.
%PYCMD% -m pytest -q
if errorlevel 1 goto :FAIL

echo.
echo  ==========================================================
echo    All tests passed.
echo  ==========================================================
echo.
pause
exit /b 0

:FAIL
echo.
echo  ==========================================================
echo    Some tests failed, scroll up to see which one.
echo  ==========================================================
echo.
pause
exit /b 1
