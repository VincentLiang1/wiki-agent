"""Mac 與 Windows 不一樣的那幾件事(osplat.py)。Windows 分支能用參數換掉平台的,在 Mac 上就先測;
真的要 Windows API 的(msvcrt 鎖檔、taskkill、attrib、認證管理員)標 skipif,到 Windows 上跑。"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from wiki_feeder import osplat
from wiki_feeder.config import CONFIG_FILE, Config, find_ffmpeg

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="要 Windows 的 API")


class _St:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.mark.parametrize("attrs, placeholder", [
    (0x20, False),                    # 一般檔(ARCHIVE)
    (0x20 | 0x400000, True),          # RECALL_ON_DATA_ACCESS:iCloud for Windows 還沒下載的檔
    (0x40000, True),                  # RECALL_ON_OPEN
    (0x1000, True),                   # OFFLINE
])
def test_windows_cloud_placeholder_by_file_attributes(attrs, placeholder):
    """Windows 沒有 st_flags:只看 Mac 的旗標的話,還沒下載的檔會被當成一般檔去算雜湊、複製(讀它會卡在下載)。"""
    assert osplat.is_placeholder(_St(st_file_attributes=attrs), windows=True) is placeholder


def test_child_processes_get_no_console_window_flag():
    """排程的 pythonw.exe 叫 git／claude／doc2md:沒加 CREATE_NO_WINDOW 的話每一個都閃一個主控台視窗。"""
    assert osplat.no_window_flags(0) == osplat.CREATE_NO_WINDOW
    group = 0x200   # CREATE_NEW_PROCESS_GROUP(逾時砍整組,proc.py)
    assert osplat.no_window_flags(group) == group | osplat.CREATE_NO_WINDOW
    assert osplat.no_window_flags(osplat.CREATE_NEW_CONSOLE) == osplat.CREATE_NEW_CONSOLE   # 不能並用
    assert osplat.hide_child_consoles(windows=False) is False


@on_windows
def test_scheduled_pythonw_runs_children_without_a_console_window(tmp_path):
    """2026-10-19 實測:pythonw.exe 底下的子行程預設(含 CREATE_NEW_PROCESS_GROUP)會開一個看得見的主控台視窗。"""
    import subprocess
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pytest.skip("venv 沒有 pythonw.exe")
    out = tmp_path / "out.txt"
    script = tmp_path / "probe.py"
    script.write_text(
        "import subprocess, sys\n"
        "from wiki_feeder import osplat\n"
        "applied = osplat.hide_child_consoles()\n"
        "child = 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'\n"
        "r = subprocess.run([sys.executable.replace('pythonw.exe', 'python.exe'), '-c', child],\n"
        "                   capture_output=True, text=True, **osplat.group_kwargs())\n"
        f"open({str(out)!r}, 'w').write(f'{{applied}} {{r.stdout.strip()}}')\n", encoding="utf-8")
    subprocess.run([str(pythonw), str(script)], timeout=60)
    assert out.read_text() == "True 0"


def test_mac_cloud_placeholder_by_flags():
    assert osplat.is_placeholder(_St(st_flags=osplat.SF_DATALESS), windows=False)
    assert not osplat.is_placeholder(_St(st_flags=0), windows=False)


def test_download_request_per_platform():
    assert osplat.download_cmd(r"C:\i\a.m4a", windows=True) == ["attrib", "+P", r"C:\i\a.m4a"]
    assert osplat.download_cmd("/i/a.m4a", windows=False) == ["brctl", "download", "/i/a.m4a"]


def test_decode_uses_ffmpeg_on_windows_and_needs_it():
    cmd = osplat.decode_cmd("a.m4a", "a.wav", 8000, r"C:\ms\ffmpeg.exe", windows=True)
    assert cmd[0] == r"C:\ms\ffmpeg.exe" and cmd[cmd.index("-ar") + 1] == "8000" and cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[-1] == "a.wav" and "-nostdin" in cmd      # 沒有 -nostdin 的話 ffmpeg 會等鍵盤輸入
    with pytest.raises(RuntimeError, match="ffmpeg"):
        osplat.decode_cmd("a.m4a", "a.wav", 8000, "", windows=True)
    assert osplat.decode_cmd("a.m4a", "a.wav", 8000, windows=False)[0] == "/usr/bin/afconvert"


def test_windows_secret_from_credential_manager(monkeypatch):
    fake = types.SimpleNamespace(get_password=lambda s, a: "abcd efgh" if (s, a) == ("svc", "me@x") else None)
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert osplat.secret("svc", "me@x", windows=True) == "abcd efgh"
    assert osplat.secret("svc", "other", windows=True) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 走 QueryUnbiasedInterruptTime;Mac 一定有 clock_gettime")
def test_uptime_without_clock_gettime(monkeypatch):
    monkeypatch.delattr(osplat.time, "clock_gettime", raising=False)   # Windows 本來就沒有
    assert osplat.uptime() > 0


def test_ffmpeg_found_in_meeting_scribe_venv(tmp_path):
    venv = tmp_path / "scribe2md" / ".venv"
    exe = venv / "Lib" / "site-packages" / "static_ffmpeg" / "bin" / "win32" / "ffmpeg.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert find_ffmpeg(venv / "Scripts" / "doc2md.exe") == str(exe)
    assert find_ffmpeg(tmp_path / "別處" / "Scripts" / "doc2md.exe") == ""


def test_friend_config_keeps_the_no_cwd_import_flag(tmp_path):
    """朋友的設定也要 -P:攝入時 cwd 是他的知識庫,claude 寫個 wiki_feeder.py 就能執行任意程式。"""
    (tmp_path / CONFIG_FILE).write_text(
        f"[inbox]\nicloud = '{tmp_path}'\n[wiki]\ndir = '{tmp_path}/W'\nraw = '{tmp_path}/R'\n"
        f"[tools]\ndoc2md = '{tmp_path}/d.exe'\nffmpeg = 'C:/f.exe'\n", encoding="utf-8")
    c = Config.from_file(tmp_path / CONFIG_FILE, tmp_path)
    assert c.ingest_tools_cmd[1] == "-P" and c.ingest_tools_cmd[-2:] == ("-m", "wiki_feeder")   # Windows 中間多 -X utf8
    assert c.ffmpeg == "C:/f.exe"


def test_cli_refuses_without_utf8_mode_on_windows(monkeypatch, capsys):
    """台灣的 Windows 預設 cp950:子行程輸出的中文會讀成亂碼、寫進處理紀錄就改不回來,所以沒開 UTF-8 模式就不跑。"""
    from wiki_feeder import cli
    monkeypatch.setattr(cli, "WINDOWS", True)
    monkeypatch.setattr(cli, "_utf8_mode", lambda: False)
    assert cli.main(["ledger"]) == 2
    assert "-X utf8" in capsys.readouterr().err


def test_deploy_guard_always_lets_runs_through_on_windows(tmp_path, monkeypatch):
    """Windows 沒有共享鎖、也不 deploy:收件與攝入兩個任務同時跑時,後到的不可因為拿不到 deploy.lock 就整輪略過。"""
    from wiki_feeder import collect
    monkeypatch.setattr(collect, "WINDOWS", True)
    held = []

    def exclusive_only(f, shared=False):   # Windows 的 msvcrt.locking:沒有共享鎖,第二個拿不到
        if held:
            return False
        held.append(f)
        return True

    monkeypatch.setattr(collect, "try_lock", exclusive_only)
    with collect.deploy_guard(tmp_path / "deploy.lock") as a, collect.deploy_guard(tmp_path / "deploy.lock") as b:
        assert a and b


@on_windows
def test_windows_lock_is_exclusive(tmp_path):
    p = tmp_path / "x.lock"
    with open(p, "a+") as f, open(p, "a+") as g:
        assert osplat.try_lock(f)
        assert not osplat.try_lock(g)
        osplat.unlock(f)
        assert osplat.try_lock(g)


@on_windows
def test_windows_kill_group_kills_grandchild(tmp_path):
    import subprocess
    import time
    flag = tmp_path / "alive"
    code = ("import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"
            f"'import time,pathlib;time.sleep(3);pathlib.Path(r\"{flag}\").write_text(\"x\")']);time.sleep(30)")
    p = subprocess.Popen([sys.executable, "-c", code], **osplat.group_kwargs())
    time.sleep(1)
    osplat.kill_group(p.pid)
    time.sleep(4)
    assert not flag.exists()
