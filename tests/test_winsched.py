"""Windows 工作排程器的任務定義:在 Mac 上只驗產生出來的 XML(安裝要到 Windows 上實際跑)。"""
from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _mod():
    spec = importlib.util.spec_from_file_location("winsched_script",
                                                  Path(__file__).parents[1] / "scripts" / "winsched.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_task_runs_every_minute_hidden_utf8_and_never_overlaps():
    m = _mod()
    xml = m.task_xml(["process"], Path(r"C:\wf\.venv\Scripts\pythonw.exe"), Path(r"C:\wf"))
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    get = lambda p: root.find(p, NS).text   # noqa: E731
    assert get("t:Actions/t:Exec/t:Command").endswith("pythonw.exe")          # 不每分鐘閃黑色視窗
    # -X utf8:台灣的 Windows 預設 cp950,中文 commit 訊息與路徑會讀成亂碼
    assert get("t:Actions/t:Exec/t:Arguments") == "-X utf8 -m wiki_feeder process"
    assert get("t:Actions/t:Exec/t:WorkingDirectory") == r"C:\wf"
    assert get("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"
    assert get("t:Settings/t:DisallowStartIfOnBatteries") == "false"           # 筆電用電池也照跑
    assert get("t:Settings/t:StopIfGoingOnBatteries") == "false"
    assert get("t:Settings/t:ExecutionTimeLimit") == "PT0S"                    # 長錄音轉寫不被砍
    assert get("t:Settings/t:Hidden") == "true"
    assert {e.text for e in root.findall(".//t:Repetition/t:Interval", NS)} == {"PT1M"}
    assert get("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"


def test_paths_with_special_characters_are_escaped():
    m = _mod()
    xml = m.task_xml(["collect"], Path(r"C:\A&B\pythonw.exe"), Path(r"C:\A&B"))
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert root.find("t:Actions/t:Exec/t:Command", NS).text == r"C:\A&B\pythonw.exe"


def test_three_tasks_watch_last_each_with_its_own_interval():
    """朋友那台不做自動修理(使用者 2026-10-19);簡易看門狗 watch 每 3 分鐘(使用者 2026-10-23),另外兩個每分鐘。
    watch 查的是同一個資料夾(實測時 --folder 換一個,不可去查真的 wiki-feeder\\)。"""
    m = _mod()
    assert list(m.TASKS) == ["collect", "process", "watch"]
    assert m.INTERVALS == {"collect": "PT1M", "process": "PT1M", "watch": "PT3M"}
    assert m.task_args("watch", "wf-test") == ["watch", "--prefix", "wf-test"]
    assert m.task_args("collect", "wf-test") == ["collect"]
    xml = m.task_xml(m.task_args("watch"), Path(r"C:\wf\pythonw.exe"), Path(r"C:\wf"), interval=m.INTERVALS["watch"])
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert {e.text for e in root.findall(".//t:Repetition/t:Interval", NS)} == {"PT3M"}
    assert root.find("t:Actions/t:Exec/t:Arguments", NS).text == "-X utf8 -m wiki_feeder watch --prefix wiki-feeder"
    assert "3" in root.find("t:RegistrationInfo/t:Description", NS).text


def _record(m, monkeypatch, busy=()):
    """假的 schtasks／PowerShell:記下每一步,running 第一次回 busy、之後回空。"""
    steps, left = [], [list(busy)]
    monkeypatch.setattr(m, "schtasks", lambda *a: steps.append(a[0] + " " + a[2]) or (0, ""))

    def running(folder):
        steps.append("running")
        now, left[0] = left[0], []
        return now
    monkeypatch.setattr(m, "running", running)
    return steps


def test_disable_stops_watch_first_and_waits_for_it(monkeypatch):
    """⚠️ Windows 沒有共享鎖,deploy_guard 擋不住:先停 collect 的話,正在跑的 watch 看到它被停用,
    朋友每次更新都收到一則假的「排程沒有載入」。"""
    m = _mod()
    steps = _record(m, monkeypatch, busy=["watch"])
    m.disable("wf", sleep=lambda s: None)
    i_watch, i_collect = steps.index("/Change wf\\watch"), steps.index("/Change wf\\collect")
    assert i_watch < steps.index("running") < i_collect
    assert "/Change wf\\process" in steps


def _venv(m, monkeypatch, tmp_path):
    py = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    py.parent.mkdir(parents=True)
    py.touch()
    monkeypatch.setattr(m, "venv_python", lambda: py)


def test_enable_and_install_put_watch_last(monkeypatch, tmp_path):
    m = _mod()
    steps = _record(m, monkeypatch)
    monkeypatch.setattr(m, "installed", lambda folder: ["collect", "process", "watch"])
    m.enable("wf")
    assert steps == ["/Change wf\\collect", "/Change wf\\process", "/Change wf\\watch"]
    steps.clear()
    _venv(m, monkeypatch, tmp_path)
    m.install(tmp_path / "state", "wf")
    assert steps == ["/Create wf\\collect", "/Create wf\\process", "/Create wf\\watch"]
    assert "--prefix wf" in (tmp_path / "state" / "task-watch.xml").read_text(encoding="utf-16")


def test_enable_after_an_update_adds_the_missing_watch_but_not_a_removed_schedule(monkeypatch, tmp_path):
    """更新的朋友不會再跑 Install.bat:舊版沒有 watch,重新啟用時要順手建起來;
    用 Remove-Schedule.bat 拿掉整個排程的,更新不可以偷偷裝回去。"""
    m = _mod()
    steps = _record(m, monkeypatch)
    _venv(m, monkeypatch, tmp_path)
    monkeypatch.setattr(m, "installed", lambda folder: ["collect", "process"])
    m.enable("wf", tmp_path / "state")
    assert steps == ["/Change wf\\collect", "/Change wf\\process", "/Create wf\\watch"]
    steps.clear()
    monkeypatch.setattr(m, "installed", lambda folder: [])
    m.enable("wf", tmp_path / "state")
    assert steps == []


def test_logon_trigger_names_the_user():
    """沒寫 UserId 的登入觸發是「任何使用者登入時」,一般帳號建任務會「存取被拒」(2026-10-20 Windows 實測)。"""
    xml = _mod().task_xml(["collect"], Path(r"C:\wf\pythonw.exe"), Path(r"C:\wf"), user=r"PC\amy")
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert root.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text == r"PC\amy"


def test_disable_for_auto_update_keeps_watch(monkeypatch):
    """自動更新換版時 watch 不停:換版程式中途死掉,下一輪 watch 要把排程重新啟用(spec §7.9)。"""
    m = _mod()
    steps = _record(m, monkeypatch, busy=["collect"])
    m.disable("wf", sleep=lambda s: None, keep_watch=True)
    assert "/Change wf\\watch" not in steps and "/Change wf\\collect" in steps and "/Change wf\\process" in steps
