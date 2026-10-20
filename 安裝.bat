@echo off
chcp 950 >nul
setlocal EnableExtensions
title wiki-feeder 安裝
rem 給朋友的 Windows:裝 Git／uv、取程式、uv sync、UTF-8 模式、長路徑,然後交給 scripts\winsetup.py 問答
rem 寫設定檔、存寄信密碼、裝排程。重跑也可以:已有設定檔會先問要不要沿用。docs\dev\Windows安裝.md
echo.
echo ==================================================
echo   wiki-feeder 安裝（第一次安裝、重新設定都用這個）
echo ==================================================
echo.
echo 開始之前請先做好這三件事：
echo   1. 裝好 iCloud for Windows，打開「iCloud 雲碟」
echo   2. 裝好 Claude Code，開一個命令視窗打 claude，登入你自己的帳號
echo   3. 照 meeting-scribe 的說明解壓縮、跑它的 安裝.bat
echo.
pause

rem ---- Git 與 uv ----
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links"
where git >nul 2>nul
if errorlevel 1 (
  echo 安裝 Git...
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
)
where git >nul 2>nul
if errorlevel 1 goto nogit
where uv >nul 2>nul
if errorlevel 1 (
  echo 安裝 uv...
  winget install --id astral-sh.uv -e --source winget --accept-package-agreements --accept-source-agreements
)
where uv >nul 2>nul
if errorlevel 1 goto nouv

rem ---- 取程式：這個檔在 wiki-feeder 資料夾裡就直接用，單獨收到的就 clone ----
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
if exist "%REPO%\pyproject.toml" goto haverepo
set "REPO=C:\wiki-feeder"
set "ANS="
echo.
echo 程式要放在哪個資料夾？直接按 Enter = C:\wiki-feeder
set /p "ANS=> "
if not "%ANS%"=="" set "REPO=%ANS%"
if exist "%REPO%\pyproject.toml" goto haverepo
echo 從 GitHub 下載程式...
git clone https://github.com/VincentLiang1/wiki-agent.git "%REPO%"
if errorlevel 1 goto noclone
:haverepo
cd /d "%REPO%"
echo.
echo 安裝程式需要的套件...
uv sync
if errorlevel 1 goto nosync

rem ---- UTF-8 模式：台灣的 Windows 預設 cp950，程式沒有 UTF-8 模式就不跑 ----
setx PYTHONUTF8 1 >nul
set "PYTHONUTF8=1"

rem ---- 長路徑：只有這一步要系統管理員，只提升這一個指令 ----
rem 整個 bat 用管理員跑的話，設定檔、排程都會裝到管理員帳號底下
reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled 2>nul | findstr /c:"0x1" >nul
if errorlevel 1 (
  echo.
  echo 開啟 Windows 長路徑支援：等一下會跳出「使用者帳戶控制」，請按「是」
  powershell -NoProfile -Command "Start-Process reg -Verb RunAs -Wait -ArgumentList 'add','HKLM\SYSTEM\CurrentControlSet\Control\FileSystem','/v','LongPathsEnabled','/t','REG_DWORD','/d','1','/f'"
)
reg query "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled 2>nul | findstr /c:"0x1" >nul
if errorlevel 1 echo 注意：長路徑沒有開成，檔名很長的檔可能會處理失敗。之後可以再跑一次 安裝.bat
git config --global core.longpaths true

rem ---- 問答、寫設定檔、裝排程 ----
echo.
uv run python -X utf8 scripts\winsetup.py
if errorlevel 1 goto setupfail
echo.
pause
exit /b 0

:nogit
echo.
echo 裝不起來 Git。請到 https://git-scm.com 下載安裝後，再跑一次 安裝.bat
pause
exit /b 1
:nouv
echo.
echo 裝不起來 uv。請到 https://docs.astral.sh/uv 照說明安裝後，再跑一次 安裝.bat
pause
exit /b 1
:noclone
echo.
echo 下載不了程式。請確認網路正常，再跑一次 安裝.bat。
pause
exit /b 1
:nosync
echo.
echo 套件裝不起來（上面有錯誤訊息）。請確認網路正常後再跑一次 安裝.bat
pause
exit /b 1
:setupfail
echo.
echo 安裝沒有完成（原因在上面）。處理好之後再跑一次 安裝.bat，已填好的設定可以沿用。
pause
exit /b 1
