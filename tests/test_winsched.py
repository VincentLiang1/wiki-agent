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


def test_two_tasks_and_no_watchdog():
    """朋友那台不做自動修理(使用者 2026-10-19):只有收件、轉寫＋攝入兩個任務。"""
    assert _mod().TASKS == {"collect": ["collect"], "process": ["process"]}


def test_logon_trigger_names_the_user():
    """沒寫 UserId 的登入觸發是「任何使用者登入時」,一般帳號建任務會「存取被拒」(2026-10-20 Windows 實測)。"""
    xml = _mod().task_xml(["collect"], Path(r"C:\wf\pythonw.exe"), Path(r"C:\wf"), user=r"PC\amy")
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    assert root.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text == r"PC\amy"
