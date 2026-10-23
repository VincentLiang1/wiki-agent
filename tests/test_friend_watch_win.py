"""朋友版 Windows 的簡易看門狗(`wiki-feeder watch`,winsched 每 3 分鐘;使用者 2026-10-23)。

Mac 版的測試在 test_watchdog.py(那個檔在 Windows 整個跳過、又用 fcntl);這裡只用跨平台的東西,
兩邊都跑:工作排程器換成假的 PowerShell 輸出,不碰真的。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace

from wiki_feeder import repair
from wiki_feeder.collect import run_file, run_lock
from wiki_feeder.watchdog import running, tasks_not_ready

NAMES = ("wiki-feeder-test\\collect", "wiki-feeder-test\\process")


def _ps(stdout: str, rc: int = 0, calls: list | None = None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        return SimpleNamespace(returncode=rc, stdout=stdout.encode(), stderr=b"boom" if rc else b"")
    return run


def test_disabled_or_missing_task_counts_as_not_loaded():
    calls = []
    out = "\\wiki-feeder-test\\collect=Ready\r\n\\wiki-feeder-test\\watch=Running\r\n"
    assert tasks_not_ready(NAMES, _ps(out, calls=calls)) == ["wiki-feeder-test\\process"]       # 不存在
    out = "\\wiki-feeder-test\\collect=Running\n\\wiki-feeder-test\\process=Disabled\n"
    assert tasks_not_ready(NAMES, _ps(out)) == ["wiki-feeder-test\\process"]                    # 被停用
    out = "\\wiki-feeder-test\\collect=Queued\n\\wiki-feeder-test\\process=Ready\n"
    assert tasks_not_ready(NAMES, _ps(out)) == []
    cmd = calls[0][-1]
    assert "Get-ScheduledTask -TaskPath '\\wiki-feeder-test\\'" in cmd and "State" in cmd   # 英文列舉,不解析 schtasks


def test_powershell_failing_is_not_reported_as_unloaded():
    """PowerShell 自己跑不起來不代表排程沒了:報出去是一則假的「排程沒有載入」。"""
    assert tasks_not_ready(NAMES, _ps("", rc=1)) == []

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)
    assert tasks_not_ready(NAMES, boom) == []


def _deps(down=()):
    return repair.Deps(agents_check=lambda: list(down), now=time.time)


def test_windows_alert_tells_the_friend_the_windows_way(cfg):
    """Windows 的朋友沒有「雙擊 wiki-agent」、也沒有終端機:要寫 Install.bat／Update.bat 與 PowerShell。"""
    alerts = repair.friend_round(cfg, NAMES, _deps(["wiki-feeder-test\\process"]), windows=True)
    assert len(alerts) == 1 and "排程沒有載入" in alerts[0] and "wiki-feeder-test\\process" in alerts[0]
    assert "Install.bat" in alerts[0] and str(repair.FRIEND_REPO) in alerts[0]
    assert "macsched" not in alerts[0] and "終端機" not in alerts[0]
    assert repair.friend_round(cfg, NAMES, _deps(["wiki-feeder-test\\process"]), windows=True) == []   # 24 小時一次


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_pid_alive_tells_a_finished_process_from_a_running_one():
    """⚠️ Windows 的 os.kill(pid, 0) 是送 Ctrl+C,對已經結束的 pid 也不報錯(2026-10-23 實測):照它判斷的話
    當掉、關機留下的 .run 永遠算「還在跑」。"""
    from wiki_feeder.osplat import pid_alive
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    child = _sleeper()
    try:
        assert pid_alive(child.pid) and not pid_alive(done.pid)
    finally:
        child.kill()
        child.wait()
    assert not pid_alive(child.pid)


def test_hung_round_is_reported_and_the_holder_is_left_alone(cfg):
    """.run 寫的是另一個活著的行程:查完它要還活著(看門狗只偵測、不在朋友的電腦上結束行程);
    卡住要報、文字是 Windows 的做法。"""
    child = _sleeper()
    try:
        lock = cfg.ingest_lock_path
        with run_lock(lock):
            f = run_file(lock)
            info = json.loads(f.read_text(encoding="utf-8"))
            info["pid"] = child.pid
            info["up"] -= cfg.ingest_timeout + 900 + 60
            f.write_text(json.dumps(info), encoding="utf-8")
            alerts = repair.friend_round(cfg, NAMES, _deps(), windows=True)
            assert child.poll() is None, "查卡住時把那一輪的行程結束掉了"
        assert len(alerts) == 1 and "攝入那一輪卡住了" in alerts[0] and "PowerShell" in alerts[0]
        assert "~/wiki-agent" not in alerts[0]
    finally:
        child.kill()
        child.wait()


def test_leftover_run_file_without_a_lock_holder_is_cleared(cfg):
    """當掉、關機留下的 .run:沒有人握鎖就清掉、不當成卡住(pid 可能早被別的行程用掉)。"""
    child = _sleeper()
    try:
        lock = cfg.convert_lock_path
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        run_file(lock).write_text(json.dumps({"pid": child.pid, "started": 0, "up": 0}), encoding="utf-8")
        assert running(cfg) == [] and not run_file(lock).exists()
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


def test_round_in_progress_is_seen_while_its_lock_is_held(cfg):
    """另一個握著鎖的一輪要看得到(Windows 只有獨佔鎖:試拿拿不到才算有人在跑)。"""
    with run_lock(cfg.lock_path):
        rs = running(cfg)
    assert [r["stage"] for r in rs] == ["收件"] and rs[0]["pid"] == os.getpid()
