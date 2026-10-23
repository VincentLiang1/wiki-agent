@echo off
rem cmd reads a running .bat by byte offset, and git pull / the zip update may replace this very file
rem (the rest would run from the middle of a line). So run a copy from %TEMP%, with the folder as argument.
if /i "%~1"=="--copy" goto copied
copy /y "%~f0" "%TEMP%\wiki-feeder-Update.bat" >nul
if errorlevel 1 goto nocopy
"%TEMP%\wiki-feeder-Update.bat" --copy "%~dp0."
:nocopy
echo Cannot copy Update.bat to %TEMP% - press any key to close.
pause >nul
exit /b 1
:copied
chcp 65001 >nul
setlocal EnableExtensions
rem Update: git pull (cloned with git) or scripts\winupdate.py (installed from the zip), then uv sync.
rem Disable the schedule first and let the running round finish: a round cut off halfway through would
rem stop the next round until someone steps in.
rem Chinese only inside call :msg / call :pick arguments - see the top of the install .bat
call :lang
call :pick T "wiki-feeder 更新" "wiki-feeder 更新" "wiki-feeder Update"
title %T%
cd /d "%~2"
if not exist pyproject.toml goto notrepo
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links"
set "PYTHONUTF8=1"
set "FAIL="
call :msg "停用排程，等正在跑的一輪做完..." "禁用定时任务，等正在跑的一轮做完..." "Pausing the schedule and waiting for the current round to finish..."
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py disable
echo.
call :msg "下載新版..." "下载新版..." "Downloading the new version..."
if not exist ".git\" goto viazip
git pull
if errorlevel 1 set "FAIL=git pull"
goto synced
:viazip
".venv\Scripts\python.exe" -X utf8 scripts\winupdate.py
if errorlevel 1 set "FAIL=winupdate"
:synced
if not defined FAIL uv sync
if not defined FAIL if errorlevel 1 set "FAIL=uv sync"
echo.
call :msg "重新啟用排程..." "重新激活定时任务..." "Turning the schedule back on..."
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py enable
echo.
if defined FAIL goto failed
call :msg "更新完成，下一分鐘起就是新版。" "更新完成，下一分钟起就是新版。" "Update finished. The new version runs from the next minute."
call :pause
exit /b 0

:failed
call :msg "更新沒有完成：%FAIL% 失敗，原因在上面。排程照舊在跑，請把這個視窗的畫面拍給幫你安裝的人。" "更新没有完成：%FAIL% 失败，原因在上面。定时任务照旧在跑，请把这个窗口的画面拍给帮你安装的人。" "Update did not finish: %FAIL% failed, the reason is shown above. The schedule keeps running the old version; please send a photo of this window to whoever helped you install."
call :pause
exit /b 1
:notrepo
call :msg "這個檔要放在 wiki-feeder 資料夾裡執行。" "这个文件要放在 wiki-feeder 文件夹里运行。" "Run this file from inside the wiki-feeder folder."
call :pause
exit /b 1

rem ==== same in all three .bat files from here to the end - tests\test_winsetup.py ====
:lang
rem Language: [general] language in the config (chosen at setup); otherwise the Windows display language,
rem mapped the same way as i18n.detect. GetUserDefaultUILanguage, not Get-UICulture: that one follows
rem the console code page and reads en-US under 65001 even on Chinese Windows.
set "WL="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$f=Join-Path $env:LOCALAPPDATA 'wiki-feeder\config.toml'; $l=''; if (Test-Path -LiteralPath $f) { $m=[regex]::Match([IO.File]::ReadAllText($f), '(?m)^\s*language\s*=\s*.(zh-Hant|zh-Hans|en)\W'); if ($m.Success) { $l=$m.Groups[1].Value } }; if (-not $l) { $q=[char]34; $k=Add-Type -Name K -Namespace WikiFeeder -PassThru -MemberDefinition ('[DllImport('+$q+'kernel32.dll'+$q+')] public static extern ushort GetUserDefaultUILanguage();'); $i=[int]$k::GetUserDefaultUILanguage(); $l='en'; if (($i -band 0x3FF) -eq 4) { $l='zh-Hant'; if ($i -eq 0x804 -or $i -eq 0x1004) { $l='zh-Hans' } } }; $l"`) do set "WL=%%L"
if not defined WL set "WL=zh-Hant"
exit /b
:msg
rem call :msg "zh-Hant" "zh-Hans" "English" - prints one line in language WL
set "M=%~1"
if "%WL%"=="zh-Hans" set "M=%~2"
if "%WL%"=="en" set "M=%~3"
echo(%M%
exit /b
:pick
rem call :pick VAR "zh-Hant" "zh-Hans" "English" - sets VAR in language WL
set "%~1=%~2"
if "%WL%"=="zh-Hans" set "%~1=%~3"
if "%WL%"=="en" set "%~1=%~4"
exit /b
:pause
rem cmd's own pause prompt is always English under 65001, so print our own
call :msg "請按任意鍵繼續 . . ." "请按任意键继续 . . ." "Press any key to continue . . ."
pause >nul
exit /b
