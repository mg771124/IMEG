# -*- coding: utf-8 -*-
"""Generate / check the Windows batch files (.bat) of this project.

Rule of thumb for these files: **pure ASCII, saved as ANSI, never UTF-8.**

cmd.exe decodes a .bat with the console code page (950 on Traditional Chinese
Windows). Anything non-ASCII in the file is therefore a gamble:

* saved as UTF-8  -> every Chinese string turns into mojibake;
* saved as Big5   -> still risky, because the second byte of some very common
  Big5 characters is ``0x5C`` (backslash) or ``0x7C`` (pipe) -- the classic
  "Xu-Gong-Gai" problem. Characters such as GONG or HUI can silently cut a
  command line in half.

So the .bat files stay ASCII (English messages) and this script enforces it:
it refuses to write (or accept) any byte >= 0x80, any BOM, or LF-only line
endings. Edit the texts below -- this file is UTF-8 -- and re-run the script:

    python tools/make_bat.py           # regenerate every .bat
    python tools/make_bat.py --check   # verify existing .bat files only

See docs/bat-notes.md if you really want Chinese text inside a .bat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM_UTF8 = b"\xef\xbb\xbf"
BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")


HEADER = """\
@echo off
rem ============================================================
rem  {title}
rem
rem  This file is plain ASCII on purpose: no UTF-8, no BOM, no
rem  Chinese characters. cmd.exe decodes batch files with the
rem  console code page, so any non-ASCII byte can be misread
rem  (and some Big5 characters carry a backslash/pipe as their
rem  second byte, which breaks command lines).
rem  Read docs/bat-notes.md before adding localized messages.
rem ============================================================
cd /d "%~dp0"
"""

# --------------------------------------------------------------------------
# Batch file contents (kept here in UTF-8; written out as ASCII + CRLF)
# --------------------------------------------------------------------------

BATS: dict[str, str] = {}

BATS["menu.bat"] = HEADER.format(title="IMEG Toolbox - main menu") + """
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
"""

BATS["install.bat"] = HEADER.format(title="IMEG install / update") + """
title IMEG - Install / update environment
setlocal

echo.
echo  ==========================================================
echo    IMEG   Install / update environment
echo  ==========================================================
echo.
echo  [1/5] Looking for Python ...
echo.

set "VPY=%~dp0.venv\\Scripts\\python.exe"
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
echo      * drop adb.exe into tools\\platform-tools\\
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
"""

BATS["start.bat"] = HEADER.format(title="IMEG start GUI") + """
title IMEG - Graphics / Control Tool
setlocal

echo.
echo  Starting IMEG, first launch takes a while ...
echo  (close the window to quit)
echo.

set "VPY=%~dp0.venv\\Scripts\\python.exe"
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
"""

BATS["build.bat"] = HEADER.format(title="IMEG build EXE") + """
title IMEG - Build EXE
setlocal

echo.
echo  ==========================================================
echo    IMEG   Build EXE
echo  ==========================================================
echo.
echo  Output goes to dist\\IMEG\\ and takes a few minutes.
echo  Do not close this window while it is running.
echo.
echo  [1/2] Looking for Python ...

set "VPY=%~dp0.venv\\Scripts\\python.exe"
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
echo    Output folder: %~dp0dist\\IMEG
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
"""

BATS["test.bat"] = HEADER.format(title="IMEG run tests") + """
title IMEG - Run tests
setlocal

echo.
echo  ==========================================================
echo    IMEG   Run tests
echo  ==========================================================
echo.

set "VPY=%~dp0.venv\\Scripts\\python.exe"
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
"""


# --------------------------------------------------------------------------
# Encode / check
# --------------------------------------------------------------------------

def encode_bat(text: str) -> bytes:
    """Normalise line endings and encode as strict 7-bit ASCII."""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"
    body = body.replace("\n", "\r\n")
    try:
        data = body.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SystemExit(
            f"[make_bat] non-ASCII character in batch text: {exc}\n"
            f"           Keep .bat files ASCII (see docs/bat-notes.md)."
        ) from exc
    return data


def check_bat(path: Path, data: bytes) -> list[str]:
    """Return a list of problems with an existing .bat file."""
    problems: list[str] = []
    for bom, name in ((BOM_UTF8, "UTF-8"), (BOM_UTF16[0], "UTF-16LE"), (BOM_UTF16[1], "UTF-16BE")):
        if data.startswith(bom):
            problems.append(f"starts with a {name} BOM (must be plain ASCII)")
            break
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        bad = data[exc.start:exc.start + 1]
        problems.append(
            f"not pure ASCII: byte 0x{bad.hex()} at offset {exc.start} "
            f"(save the file as ANSI / ASCII, not UTF-8)"
        )
        return problems
    if b"\r\n" not in data:
        problems.append("no CRLF line endings")
    elif data.count(b"\r\n") != data.count(b"\n"):
        problems.append("mixed LF / CRLF line endings")
    if "@echo off" not in text:
        problems.append("missing @echo off")
    if "cd /d \"%~dp0\"" not in text:
        problems.append("missing cd /d %~dp0 (must run from the project folder)")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate ASCII Windows batch files")
    ap.add_argument("--check", action="store_true", help="only check, do not write")
    args = ap.parse_args(argv)

    if args.check:
        rc = 0
        for name in BATS:
            path = ROOT / name
            if not path.exists():
                print(f"  [MISSING] {name}")
                rc = 1
                continue
            problems = check_bat(path, path.read_bytes())
            if problems:
                rc = 1
                print(f"  [BAD] {name}")
                for p in problems:
                    print(f"      - {p}")
            else:
                print(f"  [OK] {name}  ({path.stat().st_size} bytes, ASCII + CRLF)")
        return rc

    for name, text in BATS.items():
        data = encode_bat(text)
        (ROOT / name).write_bytes(data)
        print(f"  [WRITE] {name}  ({len(data)} bytes, ASCII + CRLF)")
    print(f"\nDone, {len(BATS)} batch files. Never save them as UTF-8.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
