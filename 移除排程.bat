@echo off
chcp 950 >nul
setlocal EnableExtensions
title wiki-feeder 移除排程
rem 只移除工作排程器的兩個任務；設定檔、處理紀錄、知識庫都不動
cd /d "%~dp0"
if not exist pyproject.toml goto notrepo
set "PYTHONUTF8=1"
echo 這會移除每分鐘自動執行的排程，程式就不再自己收檔、攝入。
echo 設定檔與處理紀錄都會留著，之後跑 安裝.bat 可以裝回來。
echo.
pause
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py uninstall
echo.
pause
exit /b 0

:notrepo
echo 這個檔要放在 wiki-feeder 資料夾裡執行。
pause
exit /b 1
