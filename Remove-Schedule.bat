@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem Removes only the Task Scheduler tasks (collect, process, watch); config, records and the knowledge base stay
rem Chinese only inside call :msg / call :pick arguments - see the top of the install .bat
call :lang
call :pick T "wiki-feeder 移除排程" "wiki-feeder 移除定时任务" "wiki-feeder Remove schedule"
title %T%
cd /d "%~dp0"
if not exist pyproject.toml goto notrepo
set "PYTHONUTF8=1"
call :msg "這會移除每分鐘自動執行的排程，程式就不再自己收檔、攝入。" "这会移除每分钟自动运行的定时任务，程序就不再自己收文件、摄入。" "This removes the schedule that runs every minute; the program will stop collecting and ingesting files on its own."
call :msg "設定檔與處理紀錄都會留著，之後跑 Install.bat 可以裝回來。" "设置文件与处理记录都会留着，之后跑 Install.bat 可以装回来。" "Your settings and processing records are kept; run Install.bat later to set it up again."
echo.
call :pause
".venv\Scripts\python.exe" -X utf8 scripts\winsched.py uninstall
echo.
call :pause
exit /b 0

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
