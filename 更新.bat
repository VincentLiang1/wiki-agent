@echo off
chcp 950 >nul
setlocal EnableExtensions
title wiki-feeder 更新
rem git pull 加 uv sync。先停用排程、等正在跑的一輪做完：做到一半被打斷，下一輪會停下來等人處理
cd /d "%~dp0"
if not exist pyproject.toml goto notrepo
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links"
set "PYTHONUTF8=1"
set "FAIL="
echo 停用排程，等正在跑的一輪做完...
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py disable
echo.
echo 下載新版...
git pull
if errorlevel 1 set "FAIL=git pull"
if not defined FAIL uv sync
if not defined FAIL if errorlevel 1 set "FAIL=uv sync"
echo.
echo 重新啟用排程...
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py enable
echo.
if defined FAIL goto failed
echo 更新完成，下一分鐘起就是新版。
pause
exit /b 0

:failed
echo 更新沒有完成：%FAIL% 失敗，原因在上面。排程照舊在跑，請把這個視窗的畫面拍給幫你安裝的人。
pause
exit /b 1
:notrepo
echo 這個檔要放在 wiki-feeder 資料夾裡執行。
pause
exit /b 1
