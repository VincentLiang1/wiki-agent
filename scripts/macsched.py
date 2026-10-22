"""Mac 朋友版的常駐(launchd ≈ Windows 的工作排程器)。使用者本人那台用的是 scripts/launchd.py(發佈副本、看門狗),不是這支。

    uv run python scripts/macsched.py install      # 裝兩個 agent(收件、轉寫＋攝入,每 60 秒一輪)
    uv run python scripts/macsched.py uninstall    # 拿掉;設定檔、處理紀錄、知識庫都不動
    uv run python scripts/macsched.py status       # 看兩個 agent 在不在跑、上次結束碼
    uv run python scripts/macsched.py check        # 用 launchd 跑一次「只列收件匣」:隱私權限只有在 launchd 底下才看得出來
    uv run python scripts/macsched.py fda-path     # 要加進「完整磁碟取用權限」的那個執行檔
    uv run python scripts/macsched.py update       # 等正在跑的一輪做完 → git pull → uv sync(Update.command 叫)

與 Windows 版(winsched.py)相同:直接跑 clone 下來的這份 `.venv`,沒有發佈副本、沒有看門狗。

- 標籤是 `io.github.wiki-agent.*`,不與使用者本人的 `tw.vli.wiki-feeder.*` 撞名;實測時用 `--prefix` 換一組
- 更新不卸載 agent:拿 deploy.lock 的獨佔鎖——每一輪全程握它的共享鎖(collect.deploy_guard),所以會等正在跑的
  那一輪做完;拿著鎖的期間新的一輪直接結束。攝入做到一半被砍,下一輪會 STOP(spec §5.6)
- plist 明寫 HOME 與 PATH:launchd 的 PATH 沒有 Homebrew 與 ~/.local/bin(claude、uv 常裝在那裡)
"""
from __future__ import annotations

import argparse
import fcntl
import os
import plistlib
import subprocess
import sys
import time
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wiki_feeder import i18n  # noqa: E402
from wiki_feeder.config import CONFIG_FILE, Config, ConfigError, state_dir_for  # noqa: E402
from wiki_feeder.i18n import L  # noqa: E402

PYTHON = REPO / ".venv" / "bin" / "python"
PREFIX = "io.github.wiki-agent"
INTERVAL = 60
JOBS = {"collect": ["collect"], "process": ["process"]}


def paths(home: Path) -> tuple[Path, Path]:
    """(LaunchAgents 資料夾, 執行狀態目錄)。測試與實測給假的家目錄。"""
    return home / "Library" / "LaunchAgents", state_dir_for("darwin", home, {})


def env_path(home: Path) -> str:
    return f"{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def plist_for(label: str, cmd: list[str], home: Path, watch: list[Path] | None = None) -> dict:
    _, state = paths(home)
    log = state / "logs" / f"{label.rsplit('.', 1)[-1]}.launchd.log"
    d = {
        "Label": label,
        "ProgramArguments": [str(PYTHON), "-m", "wiki_feeder", *cmd],
        "WorkingDirectory": str(REPO),
        "EnvironmentVariables": {"PATH": env_path(home), "HOME": str(home), "LANG": "en_US.UTF-8"},
        "StartInterval": INTERVAL,
        "RunAtLoad": True,
        # 程式自己的 log(feeder.log)有輪替;這個檔只收 log 設好之前就當掉的 traceback
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    if watch:
        d["WatchPaths"] = [str(p) for p in watch]    # 收件匣一有變動就跑,不必等滿 60 秒
    return d


def domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _load(label: str, d: dict, agents: Path) -> bool:
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{label}.plist"
    _launchctl("bootout", f"{domain()}/{label}")
    with open(path, "wb") as f:
        plistlib.dump(d, f)
    r = _launchctl("bootstrap", domain(), str(path))
    print(L("{label}:已裝好", label=label) if r.returncode == 0
          else L("{label}:裝不起來 {err}", label=label, err=r.stderr.strip()))
    return r.returncode == 0


def _inboxes(cfg: Config) -> list[Path]:
    return [p for p in (cfg.icloud_inbox, cfg.onedrive_inbox) if p]


def install(home: Path, prefix: str = PREFIX) -> bool:
    try:
        cfg = Config.default()
    except ConfigError as e:
        print(f"✗ {e}")
        return False
    agents, state = paths(home)
    (state / "logs").mkdir(parents=True, exist_ok=True)
    ok = True
    for name, cmd in JOBS.items():
        ok &= _load(f"{prefix}.{name}", plist_for(f"{prefix}.{name}", cmd, home,
                                                  _inboxes(cfg) if name == "collect" else None), agents)
    return ok


def uninstall(home: Path, prefix: str = PREFIX) -> None:
    agents, _ = paths(home)
    for name in JOBS:
        label = f"{prefix}.{name}"
        _launchctl("bootout", f"{domain()}/{label}")
        (agents / f"{label}.plist").unlink(missing_ok=True)
        print(L("{label}:已拿掉", label=label))


def status(prefix: str = PREFIX) -> None:
    for name in JOBS:
        label = f"{prefix}.{name}"
        r = _launchctl("print", f"{domain()}/{label}")
        if r.returncode:
            print(L("{label}:沒有裝", label=label))
            continue
        keep = [ln.strip() for ln in r.stdout.splitlines()
                if ln.strip().startswith(("state =", "runs =", "last exit code ="))]
        print(f"{label}:{'; '.join(keep)}")


def fda_path() -> str:
    # 隱私權限綁的是真正的執行檔(uv 的 python),不是 .venv 裡的捷徑;uv 升級 Python 小版本後要重新加
    return os.path.realpath(PYTHON)


def _expected_inboxes() -> int:
    """設定好的收件匣有幾個(至少 1):每一個都要讀得到才算過。設定檔讀不了就只要求一個。"""
    try:
        return max(1, len(_inboxes(Config.default())))
    except Exception:  # noqa: BLE001 —— 讀不了設定檔不該讓檢查當掉
        return 1


def check(home: Path, prefix: str = PREFIX) -> int:
    """用 launchd 跑一次 `collect --list`:在終端機手動跑會過、launchd 底下才會被隱私權限擋。"""
    agents, state = paths(home)
    label = f"{prefix}.check"
    out = state / "logs" / "check.launchd.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    d = plist_for(label, ["collect", "--list"], home)
    d.pop("StartInterval")
    if not _load(label, d, agents):
        return 1
    try:
        for _ in range(60):
            r = _launchctl("print", f"{domain()}/{label}")
            if "state = not running" in r.stdout and out.exists():
                break
            time.sleep(1)
    finally:
        _launchctl("bootout", f"{domain()}/{label}")
        (agents / f"{label}.plist").unlink(missing_ok=True)
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    print(text or L("(沒有輸出——可能根本沒跑起來)"))
    # 要明確看到「可讀」才算過:空輸出不可當成成功。每個設定好的收件匣都要有一行「可讀」
    # (cli 讀不到時印的是「錯誤:…」,不是「讀不到」:以前比對「讀不到」從來沒有命中過)
    readable = sum(any(f"\t{v}" in ln for v in i18n.variants("可讀")) for ln in text.splitlines())
    if readable < _expected_inboxes():
        print(L("\n✗ launchd 底下讀不到收件匣。請把這個執行檔加進「完整磁碟取用權限」(安裝說明第 5 步):\n   {path}",
                path=fda_path()))
        return 1
    print(L("✓ launchd 底下讀得到收件匣"))
    return 0


def hold_exclusive(lock: Path, say=print, poll: float = 2.0):
    """拿 deploy.lock 的獨佔鎖:正在跑的一輪握著共享鎖,做完才放。等的時候每隔一陣子講一聲。"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock, "a+")
    told = False
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            if not told:
                say(L("正在跑的一輪還沒做完(可能正在攝入),等它做完再更新,不會中途砍掉……"))
                told = True
            time.sleep(poll)


def update(home: Path, run=subprocess.run) -> int:
    _, state = paths(home)
    before = fda_path()
    f = hold_exclusive(state / "deploy.lock")
    try:
        steps = (["git", "-C", str(REPO), "pull", "--ff-only"], ["uv", "sync", "--frozen", "--directory", str(REPO)])
        for cmd in steps:
            print(f"$ {' '.join(cmd)}")
            if run(cmd).returncode:
                print(L("✗ 這一步失敗:{cmd}\n  程式維持原本的版本,排程照常在跑;把這個視窗的內容給幫你裝的人看",
                        cmd=" ".join(cmd)))
                return 1
    finally:
        f.close()                                    # 放開鎖:下一輪就用新程式
    if fda_path() != before:
        print(L("⚠ Python 換了版本:要重新把這個執行檔加進「完整磁碟取用權限」,否則收件匣會讀不到:\n   {path}",
                path=fda_path()))
    print(L("✓ 更新好了,下一輪就用新程式"))
    return 0


def config_lang(home: Path) -> str:
    """.command 直接叫這支、不經 cli:自己讀設定檔的 [general] language;讀不到就看系統語言。"""
    try:
        lang = tomllib.loads((paths(home)[1] / CONFIG_FILE).read_text(encoding="utf-8-sig"))["general"]["language"]
        if lang in i18n.LANGS:
            return lang
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        pass
    return i18n.detect()


def main(argv: list[str] | None = None) -> int:
    home = Path.home()
    i18n.set_lang(config_lang(home))
    ap = argparse.ArgumentParser(prog="macsched.py", description=L("Mac 朋友版的常駐(launchd)"))
    ap.add_argument("cmd", choices=["install", "uninstall", "status", "check", "fda-path", "update"])
    ap.add_argument("--prefix", default=PREFIX, help=L("launchd 標籤的開頭(實測時換一組,不與真的撞名)"))
    a = ap.parse_args(argv)
    if a.cmd == "install":
        return 0 if install(home, a.prefix) else 1
    if a.cmd == "uninstall":
        uninstall(home, a.prefix)
    elif a.cmd == "status":
        status(a.prefix)
    elif a.cmd == "fda-path":
        print(fda_path())
    elif a.cmd == "check":
        return check(home, a.prefix)
    else:
        return update(home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
