@echo off
rem ============================================================
rem  IMEG Toolbox - main menu
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"

title IMEG Toolbox
setlocal

:MENU
cls
echo.
echo  ==========================================================
echo    IMEG   Graphics / Control Tool   -   Toolbox
echo  ==========================================================
echo.
echo     [1]  Install / update environment (create .venv)
echo     [2]  Start IMEG GUI
echo     [3]  Build EXE (runs on PCs without Python)
echo     [4]  Run tests
echo     [5]  Open project folder
echo     [0]  Exit
echo.
set "SEL="
set /p "SEL=  Type a number and press Enter: "
if "%SEL%"=="1" goto :DO_INSTALL
if "%SEL%"=="2" goto :DO_GUI
if "%SEL%"=="3" goto :DO_BUILD
if "%SEL%"=="4" goto :DO_TEST
if "%SEL%"=="5" goto :DO_OPEN
if "%SEL%"=="0" goto :DO_QUIT
echo.
echo     No such option, try again.
echo.
timeout /t 2 >nul
goto :MENU

:DO_INSTALL
call :RUN_BAT "install.bat"
goto :MENU

:DO_GUI
call :RUN_BAT "start.bat"
goto :MENU

:DO_BUILD
call :RUN_BAT "build.bat"
goto :MENU

:DO_TEST
call :RUN_BAT "test.bat"
goto :MENU

:DO_OPEN
start "" explorer "%~dp0"
goto :MENU

:DO_QUIT
endlocal
exit /b 0

:RUN_BAT
if exist "%~dp0%~1" goto :RUN_BAT_OK
echo.
echo    [ERROR] %~1 not found.
echo    Keep it in the same folder as menu.bat.
echo.
pause
exit /b 1

:RUN_BAT_OK
echo.
echo  ==========================================================
echo    Running: %~1
echo  ==========================================================
call "%~dp0%~1"
echo.
echo  ----------------------------------------------------------
echo    %~1 finished. Press any key to go back to the menu.
echo  ----------------------------------------------------------
pause >nul
exit /b 0
