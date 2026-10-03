@echo off
setlocal EnableExtensions
chcp 65001 >nul
title IMEG EXE 打包

cd /d "%~dp0"
if errorlevel 1 goto failed

set "VENV_DIR=%~dp0.venv-build"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%PYTHON%" goto venv_ready

rem Prefer Python 3.11 for predictable PyInstaller/PySide6 wheels; fall back to the default Python 3.
where py >nul 2>nul
if not errorlevel 1 goto use_py_launcher
where python >nul 2>nul
if errorlevel 1 goto missing_python
python --version
python -m venv "%VENV_DIR%"
if errorlevel 1 goto failed
goto venv_ready

:use_py_launcher
py -3.11 --version >nul 2>nul
if not errorlevel 1 goto create_py311
py -3 --version >nul 2>nul
if errorlevel 1 goto missing_python
py -3 -m venv "%VENV_DIR%"
if errorlevel 1 goto failed
goto venv_ready

:create_py311
py -3.11 -m venv "%VENV_DIR%"
if errorlevel 1 goto failed

:venv_ready
if not exist "%PYTHON%" goto failed
"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto old_python

echo.
echo [1/4] 更新 pip 并安装项目全部 Python 依赖（核心 + OCR + PyAV）...
"%PYTHON%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto failed
"%PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt" -r "%~dp0requirements-ocr.txt"
if errorlevel 1 goto failed
"%PYTHON%" -m pip install --disable-pip-version-check "pyinstaller>=6.3"
if errorlevel 1 goto failed

echo.
echo [2/4] 打包便携目录，包含 OCR 模型、PyAV、scrcpy-server、ADB 与 VC++ 运行库...
echo [3/4] 默认使用自签名证书。正式发布可先设置 IMEG_SIGN_PFX / IMEG_SIGN_PASSWORD。
"%PYTHON%" -m imeg.tools.build_exe --with-ocr --with-av --with-scrcpy-server --require-adb --require-signature --sign-self --zip %*
if errorlevel 1 goto failed

echo.
echo [4/4] 打包完成。产物位于 dist\IMEG\，压缩包位于 dist\。
pause
exit /b 0

:missing_python
echo.
echo [错误] 找不到 Python 3.10 或更高版本。请先安装 Python，并勾选 Add Python to PATH。
goto failed

:old_python
echo.
echo [错误] 打包环境需要 Python 3.10 或更高版本。
goto failed

:failed
echo.
echo [失败] 打包未完成。请查看上方错误信息；签名需要 Windows SDK 的 SignTool。
pause
exit /b 1
