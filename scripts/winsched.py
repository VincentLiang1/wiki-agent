"""wiki-feeder 的 Windows 排程(給朋友用的版本):產生工作排程器的任務定義、安裝、移除、查狀態、實測收件匣。

用法(在 repo 根目錄,Windows 上):
    uv run python -X utf8 scripts\\winsched.py install     在工作排程器建「wiki-feeder\\collect」「…\\process」「…\\watch」
    uv run python -X utf8 scripts\\winsched.py uninstall   刪掉這三個任務
    uv run python -X utf8 scripts\\winsched.py status      三個任務的狀態與上次結果
    uv run python -X utf8 scripts\\winsched.py check       跑一次 `collect --list`,確認讀得到收件匣
    uv run python -X utf8 scripts\\winsched.py xml         只印出任務定義(不動工作排程器)
    uv run python -X utf8 scripts\\winsched.py disable     停用三個任務、等正在跑的一輪做完(Update.bat 用)
    uv run python -X utf8 scripts\\winsched.py enable      重新啟用
    實測時加 --folder <別的資料夾名>,不碰真的 wiki-feeder\\

朋友那台用 repo 根目錄的 Install.bat／Update.bat／Remove-Schedule.bat,不必打這些指令。

對照 Mac 的 scripts/launchd.py(≈ 工作排程器 ≈ launchd):
- 收件、轉寫＋攝入兩個任務每分鐘一輪(使用者 2026-10-04 定案的節奏,Mac 一樣),分開是讓長錄音不擋收件;
  第三個 watch 每 3 分鐘(簡易看門狗,使用者 2026-10-23,spec §7.7):查卡住的一輪、前兩個任務不見或被停用,
  發警示到當日摘要。間隔每個任務各自設(INTERVALS)
- **沒有自動修理、沒有發佈副本**(使用者 2026-10-19:朋友那台不做自動修理);直接跑 repo 的 .venv,
  更新就是 `git pull` 加 `uv sync`(任務下一分鐘就用新程式)
- ⚠️ 停用時**先停 watch**、等它跑完才停另外兩個;安裝、啟用時 **watch 最後**。Windows 沒有共享鎖,Mac 那種
  「更新握獨佔鎖、watch 拿不到就不查」做不到(collect.deploy_guard 在 Windows 一律放行),順序反了的話
  朋友每次更新都會收到一則「排程沒有載入」
- 跑 `pythonw.exe`:`python.exe` 每分鐘會閃一個黑色視窗
- 一律帶 `-X utf8`:台灣的 Windows 預設 cp950,子行程輸出(中文 commit 訊息、路徑)會讀成亂碼。
  任務定義不能設環境變數,所以用旗標;CLI 在 Windows 上沒有 UTF-8 模式就拒絕執行
- 「只在使用者登入時執行」:iCloud for Windows 也只在登入時同步;不必存 Windows 密碼
- 同一個任務還在跑就不另開(IgnoreNew):程式本身也有鎖檔,這是第二道
- 不設執行時間上限(PT0S):長錄音轉寫要幾十分鐘,程式自己對每個子行程有逾時
- 插電與否都跑(筆電用電池時工作排程器預設不跑)
- 登入觸發一定要寫 <UserId>:沒寫是「任何使用者登入時」,一般帳號建任務會「存取被拒」
  (2026-10-20 實測;只有系統管理員建得起來)
- schtasks 的訊息是系統碼頁(台灣 cp950),我們跑在 -X utf8 底下要自己用 OEM 碼頁解;
  照 utf-8 解的話讀取執行緒當掉、錯誤訊息變成空字串

2026-10-20 在使用者的 Windows(一般帳號)實測過 install／status／uninstall;2026-10-23 實測 watch(停用 collect
→ 當日摘要出現「排程沒有載入」),見 docs/dev/Windows安裝.md。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wiki_feeder import i18n  # noqa: E402
from wiki_feeder.config import CONFIG_FILE, state_dir_for  # noqa: E402
from wiki_feeder.i18n import L  # noqa: E402
from wiki_feeder.osplat import oem_decode  # noqa: E402

FOLDER = "wiki-feeder"
WATCH = "watch"
TASKS = {"collect": ["collect"], "process": ["process"], WATCH: ["watch"]}   # 順序就是安裝、啟用的順序:watch 最後
INTERVALS = {"collect": "PT1M", "process": "PT1M", WATCH: "PT3M"}


def venv_python(repo: Path = REPO, windowless: bool = True) -> Path:
    scripts = repo / ".venv" / "Scripts"
    if windowless and (scripts / "pythonw.exe").exists():
        return scripts / "pythonw.exe"
    return scripts / "python.exe"


def current_user() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def task_args(key: str, folder: str = FOLDER) -> list[str]:
    """watch 要查的是同一個資料夾裡的任務(實測時 --folder 換一個)。"""
    return [*TASKS[key], "--prefix", folder] if key == WATCH else TASKS[key]


def task_xml(args: list[str], python: Path, workdir: Path, user: str = "",
             start: str = "2026-01-01T00:00:00", interval: str = "PT1M") -> str:
    """工作排程器任務定義(Task Scheduler 1.4 schema)。user:誰登入時開始跑(DOMAIN\\帳號)。
    interval:ISO 8601 的分鐘數(PT1M、PT3M)。"""
    user = user or current_user()
    cmd_args = " ".join(["-X", "utf8", "-m", "wiki_feeder", *args])
    minutes = interval.removeprefix("PT").removesuffix("M")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(L("wiki-feeder {args}:每 {m} 分鐘一輪", args=" ".join(args), m=minutes))}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Repetition>
        <Interval>{interval}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>{interval}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(python))}</Command>
      <Arguments>{escape(cmd_args)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def task_name(key: str, folder: str = FOLDER) -> str:
    return f"{folder}\\{key}"


def schtasks(*args: str) -> tuple[int, str]:
    r = subprocess.run(["schtasks", *args], capture_output=True)
    return r.returncode, oem_decode(r.stdout + r.stderr).strip()


def install(state: Path, folder: str = FOLDER, keys: list[str] | None = None) -> None:
    py = venv_python()
    if not py.exists():
        sys.exit(L("找不到 {path}:先在 repo 根目錄跑 `uv sync`", path=py))
    state.mkdir(parents=True, exist_ok=True)
    for key in keys or TASKS:   # watch 最後:重裝時前兩個還沒建好,它不會先跑起來報「排程沒有載入」
        xml = state / f"task-{key}.xml"
        xml.write_text(task_xml(task_args(key, folder), py, REPO, interval=INTERVALS[key]),
                       encoding="utf-16")   # schtasks /XML 要 UTF-16
        name = task_name(key, folder)
        rc, msg = schtasks("/Create", "/TN", name, "/XML", str(xml), "/F")
        print(L("{task}:已建立", task=name) if rc == 0 else L("{task}:建立失敗 {msg}", task=name, msg=msg))


def uninstall(folder: str = FOLDER) -> None:
    for key in reversed(TASKS):   # watch 先刪
        name = task_name(key, folder)
        rc, msg = schtasks("/Delete", "/TN", name, "/F")
        print(L("{task}:已刪除", task=name) if rc == 0 else f"{name}:{msg}")
    # schtasks 刪不了資料夾,用工作排程器的 COM 介面刪;裡面還有別的任務就刪不掉,不勉強
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$s = New-Object -ComObject Schedule.Service; $s.Connect(); "
                        f"$s.GetFolder('\\').DeleteFolder('{folder}', 0)"], capture_output=True)
    print(L("{folder}\\ 資料夾:已刪除", folder=folder) if r.returncode == 0
          else L("{folder}\\ 資料夾:沒刪(不存在或裡面還有別的任務)", folder=folder))


def running(folder: str = FOLDER) -> list[str]:
    """正在跑的任務。PowerShell 的 State 是英文列舉(schtasks 的「狀態」欄跟著系統語言)。"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-ScheduledTask -TaskPath '\\{folder}\\' -ErrorAction SilentlyContinue | "
                        "Where-Object State -eq 'Running' | ForEach-Object TaskName"], capture_output=True)
    return oem_decode(r.stdout).split()


def _wait(keys: list[str], folder: str, poll: float, sleep) -> None:
    waited = 0.0
    while busy := [t for t in running(folder) if t in keys]:
        if waited % 60 == 0:
            print(L("等正在跑的一輪做完({tasks};長錄音可能要幾十分鐘,不要關這個視窗)…", tasks=L("、").join(busy)),
                  flush=True)
        sleep(poll)
        waited += poll


def disable(folder: str = FOLDER, poll: float = 10, sleep=None, keep_watch: bool = False) -> None:
    """更新前:停用三個任務(不再開新的一輪),再等正在跑的那一輪自己做完。
    ⚠️ 先停 watch、等它這一輪跑完,才停另外兩個:反過來的話 watch 會看到它們被停用,報一則假的「排程沒有載入」
    (Windows 沒有共享鎖,deploy_guard 擋不住)。
    ⚠️ 不砍它:攝入做到一半被砍,下一輪看到 ingesting 會 STOP(§5.6);長錄音轉寫可能要等幾十分鐘。"""
    import time
    sleep = sleep or time.sleep
    # keep_watch:自動更新(scripts/winautoupdate.py)用。watch 不停,換版程式中途死掉時靠它把排程重新啟用;
    # watch 那一輪看到換版正在進行就不查排程沒載入,所以不會誤報
    for key in [k for k in [WATCH, *(k for k in TASKS if k != WATCH)] if not (keep_watch and k == WATCH)]:
        name = task_name(key, folder)
        rc, msg = schtasks("/Change", "/TN", name, "/DISABLE")
        print(L("{task}:已停用", task=name) if rc == 0 else f"{name}:{msg}")
        if key == WATCH:
            _wait([WATCH], folder, 2, sleep)   # watch 一輪只要幾秒
    _wait([k for k in TASKS if not (keep_watch and k == WATCH)], folder, poll, sleep)
    print(L("沒有正在跑的了"))


def installed(folder: str = FOLDER) -> list[str]:
    """資料夾裡現有的任務(不論有沒有停用)。"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-ScheduledTask -TaskPath '\\{folder}\\' -ErrorAction SilentlyContinue | "
                        "ForEach-Object TaskName"], capture_output=True)
    return oem_decode(r.stdout).split()


def enable(folder: str = FOLDER, state: Path | None = None) -> None:
    """更新後重新啟用;舊版沒裝過的任務(2026-10-23 加的 watch)順手建起來——用 git pull 或 zip 更新的朋友
    不會再跑一次 Install.bat。資料夾裡一個任務都沒有(朋友用 Remove-Schedule.bat 拿掉了)就不建。"""
    have = installed(folder)
    for key in TASKS:   # watch 最後
        name = task_name(key, folder)
        if key not in have:
            if have:
                install(state or _state_dir(), folder, keys=[key])
            continue
        rc, msg = schtasks("/Change", "/TN", name, "/ENABLE")
        print(L("{task}:已啟用", task=name) if rc == 0 else f"{name}:{msg}")


def _state_dir() -> Path:
    from wiki_feeder.config import Config
    return Config.default().state_dir


def status(folder: str = FOLDER) -> None:
    for key in TASKS:
        name = task_name(key, folder)
        _, msg = schtasks("/Query", "/TN", name, "/V", "/FO", "LIST")
        print(f"== {name} ==\n{msg}\n")


def check() -> None:
    """用 venv 的 python 跑一次只列收件匣、不搬檔;讀得到每個收件匣才算過(空輸出不算)。"""
    r = subprocess.run([str(venv_python(windowless=False)), "-X", "utf8", "-m", "wiki_feeder", "collect", "--list"],
                       cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    print((r.stdout + r.stderr).strip() or L("(沒有任何輸出:不算通過,看 %LOCALAPPDATA%\\wiki-feeder\\logs\\feeder.log)"))


def config_lang() -> str:
    """.bat 直接叫這支、不經 cli:自己讀設定檔的 [general] language;讀不到就看系統語言。"""
    try:
        path = state_dir_for(sys.platform, Path.home(), os.environ) / CONFIG_FILE
        lang = tomllib.loads(path.read_text(encoding="utf-8-sig"))["general"]["language"]
        if lang in i18n.LANGS:
            return lang
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        pass
    return i18n.detect()


def main(argv: list[str] | None = None) -> int:
    i18n.set_lang(config_lang())
    ap = argparse.ArgumentParser(prog="winsched", description=L("wiki-feeder 的 Windows 工作排程器任務"))
    ap.add_argument("cmd", choices=["install", "uninstall", "status", "check", "xml", "disable", "enable"])
    ap.add_argument("--folder", default=FOLDER, help=L("工作排程器的資料夾(實測時換一個,不碰真的)"))
    ap.add_argument("--keep-watch", action="store_true", help=L("disable 時不停 watch(自動更新用)"))
    args = ap.parse_args(argv)
    f = args.folder
    if args.cmd == "xml":
        for key in TASKS:
            xml = task_xml(task_args(key, f), venv_python(), REPO, interval=INTERVALS[key])
            print(f"== {task_name(key, f)} ==\n{xml}")
        return 0
    if sys.platform != "win32":
        print(L("這支只在 Windows 上用;Mac 用 scripts/launchd.py"), file=sys.stderr)
        return 2
    from wiki_feeder.config import Config
    {"install": lambda: install(Config.default().state_dir, f), "uninstall": lambda: uninstall(f),
     "status": lambda: status(f), "check": check, "disable": lambda: disable(f, keep_watch=args.keep_watch), "enable": lambda: enable(f)}[args.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
