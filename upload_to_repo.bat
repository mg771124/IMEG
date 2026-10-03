@echo off
setlocal EnableExtensions
chcp 65001 >nul
title IMEG 上传并同步到 GitHub

cd /d "%~dp0"
if errorlevel 1 goto failed
where git >nul 2>nul
if errorlevel 1 goto git_missing

echo [1/4] 检查仓库与分支...
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto not_a_repo
set "BRANCH=arena/01a1029b-imeg"
set "CURRENT_BRANCH="
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%B"
if not "%CURRENT_BRANCH%"=="%BRANCH%" goto wrong_branch
git remote get-url origin >nul 2>nul
if errorlevel 1 goto no_origin

echo.
echo [2/4] 当前变更（将执行 git add -A）：
git status --short --branch
set "COMMIT_MSG=%~1"
if not defined COMMIT_MSG set /p "COMMIT_MSG=请输入本次提交说明: "
if not defined COMMIT_MSG goto empty_message
set "CONFIRM="
set /p "CONFIRM=确认提交并推送到 origin/%BRANCH%？[Y/N]: "
if /i not "%CONFIRM%"=="Y" goto cancelled

echo.
echo [3/4] 暂存并提交...
git add -A
if errorlevel 1 goto failed
git diff --cached --quiet
if not errorlevel 1 goto no_changes
git commit -m "%COMMIT_MSG%"
if errorlevel 1 goto commit_failed

echo.
echo [4/4] 推送到 origin/%BRANCH%...
git push --set-upstream origin "%BRANCH%"
if errorlevel 1 goto push_failed
echo.
echo 上传完成：
git status --short --branch
pause
exit /b 0

:git_missing
echo [错误] 找不到 Git。请先安装 Git for Windows，并确保 git 已加入 PATH。
goto failed

:not_a_repo
echo [错误] 此目录不是 Git 仓库。请在克隆后的仓库目录中运行此 BAT。
goto failed

:wrong_branch
echo [错误] 当前分支是 "%CURRENT_BRANCH%"，此上传脚本只推送 %BRANCH%。不会自动切换分支。
goto failed

:no_origin
echo [错误] 找不到 origin 远端，请先配置 GitHub 仓库 remote。
goto failed

:empty_message
echo [错误] 提交说明不能为空。
goto failed

:cancelled
echo 已取消，没有提交或推送。
pause
exit /b 0

:no_changes
echo 没有待提交的变更，不需要上传。
pause
exit /b 0

:commit_failed
echo [错误] git commit 失败。请检查 Git 用户名/邮箱、提交说明或 pre-commit hook。
goto failed

:push_failed
echo [错误] 推送失败。若远端有新提交，请先运行 download_latest.bat；若是认证错误，请检查本机 Git 凭据。
goto failed

:failed
echo.
echo 上传失败。检查上方错误后重试。
pause
exit /b 1
