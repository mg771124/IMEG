@echo off
setlocal EnableExtensions
chcp 65001 >nul
title IMEG 从仓库同步最新版本

cd /d "%~dp0"
if errorlevel 1 goto failed
where git >nul 2>nul
if errorlevel 1 goto git_missing

echo [1/3] 检查仓库与分支...
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto not_a_repo
set "BRANCH=arena/01a1029b-imeg"
set "CURRENT_BRANCH="
for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%B"
if not "%CURRENT_BRANCH%"=="%BRANCH%" goto wrong_branch
git remote get-url origin >nul 2>nul
if errorlevel 1 goto no_origin

rem 不覆盖未提交内容；先用 upload_to_repo.bat 上传，或手动备份/提交。
set "DIRTY="
for /f "delims=" %%S in ('git status --porcelain 2^>nul') do set "DIRTY=1"
if defined DIRTY goto dirty_tree

echo [2/3] 从 origin 获取最新提交...
git fetch --prune origin
if errorlevel 1 goto failed

rem Arena 分支首次推送前可能尚未出现在远端，先用 origin/main 同步基线。
git show-ref --verify --quiet "refs/remotes/origin/%BRANCH%"
if not errorlevel 1 goto sync_session_branch
git show-ref --verify --quiet refs/remotes/origin/main
if errorlevel 1 goto no_remote_branch

echo [3/3] 将当前分支快进到 origin/main...
git merge --ff-only origin/main
if errorlevel 1 goto merge_failed
goto done

:sync_session_branch
echo [3/3] 将当前分支快进到 origin/%BRANCH%...
git merge --ff-only "origin/%BRANCH%"
if errorlevel 1 goto merge_failed
goto done

:done
echo.
echo 同步完成：
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
echo [错误] 当前分支是 "%CURRENT_BRANCH%"，此同步脚本只操作 %BRANCH%。不会自动切换分支。
goto failed

:no_origin
echo [错误] 找不到 origin 远端，请先配置 GitHub 仓库 remote。
goto failed

:dirty_tree
echo [错误] 工作区有未提交变更；为避免覆盖，已停止同步。先提交/上传或备份变更后再运行。
goto failed

:no_remote_branch
echo [错误] origin 上找不到 %BRANCH% 或 main 分支。
goto failed

:merge_failed
echo [错误] 无法快进同步（本地与远端已有分叉）。未执行强制覆盖；请手动检查并解决 Git 历史。
goto failed

:failed
echo.
echo 下载/同步失败。检查上方错误后重试。
pause
exit /b 1
