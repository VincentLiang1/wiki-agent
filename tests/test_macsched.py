"""Mac 朋友版:常駐腳本 scripts/macsched.py、安裝問答 scripts/macsetup.py、install.sh 與兩個 .command。

全部用假的家目錄;launchctl 換成假的,不會裝進這台的 launchd。真的 launchd 實測見 docs/dev/Windows安裝.md。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# 整檔跳過要在 import 之前:pytestmark 擋不住下面模組層級的 _mod("macsched")(它 import fcntl)
if sys.platform == "win32":
    pytest.skip("Mac 朋友版(launchd、flock、zsh)", allow_module_level=True)

ROOT = Path(__file__).parents[1]


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ms = _mod("macsched")


def test_agents_run_this_checkout_with_home_and_path_set(tmp_path):
    """launchd 的 PATH 沒有 ~/.local/bin、Homebrew(claude、uv 常在那裡);標籤不與使用者本人的 tw.vli.* 撞名。"""
    inbox = tmp_path / "_WikiBox"
    d = ms.plist_for("io.github.wiki-agent.collect", ["collect"], tmp_path, [inbox])
    assert d["ProgramArguments"] == [str(ROOT / ".venv" / "bin" / "python"), "-m", "wiki_feeder", "collect"]
    env = d["EnvironmentVariables"]
    assert env["HOME"] == str(tmp_path) and f"{tmp_path}/.local/bin" in env["PATH"] and "/opt/homebrew/bin" in env["PATH"]
    assert d["StartInterval"] == 60 and d["RunAtLoad"] and d["WatchPaths"] == [str(inbox)]
    assert d["StandardErrorPath"].startswith(str(tmp_path / "Library" / "Application Support" / "wiki-feeder" / "logs"))
    assert "WatchPaths" not in ms.plist_for("io.github.wiki-agent.process", ["process"], tmp_path)
    assert ms.PREFIX == "io.github.wiki-agent" and "vli" not in ms.PREFIX


def test_install_writes_two_agents_into_the_given_home(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ms, "_launchctl", lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ms.Config, "default", classmethod(lambda cls: type("C", (), {
        "icloud_inbox": tmp_path / "in", "onedrive_inbox": None})()))
    assert ms.install(tmp_path, "test.wa")
    agents = tmp_path / "Library" / "LaunchAgents"
    assert sorted(p.name for p in agents.iterdir()) == ["test.wa.collect.plist", "test.wa.process.plist"]
    assert [a[0] for a in calls] == ["bootout", "bootstrap", "bootout", "bootstrap"]
    ms.uninstall(tmp_path, "test.wa")
    assert not list(agents.iterdir())


def test_update_waits_for_the_running_round_and_blocks_new_ones(tmp_path):
    """正在跑的一輪握著 deploy.lock 的共享鎖:更新等它做完才 pull;更新期間新的一輪拿不到鎖、直接結束。"""
    import fcntl

    from wiki_feeder.collect import deploy_guard

    _, state = ms.paths(tmp_path)
    lock = state / "deploy.lock"
    lock.parent.mkdir(parents=True)
    held = open(lock, "a+")
    fcntl.flock(held, fcntl.LOCK_SH)
    released = []

    def release():
        time.sleep(0.5)
        released.append(time.monotonic())
        held.close()

    threading.Thread(target=release).start()
    ran = []

    def run(cmd):
        with deploy_guard(lock) as ok:
            ran.append((cmd[0], time.monotonic(), ok))
        return subprocess.CompletedProcess(cmd, 0)

    assert ms.update(tmp_path, run=run) == 0
    assert [c for c, _, _ in ran] == ["git", "uv"]
    assert ran[0][1] >= released[0]                                         # 等那一輪做完才 pull
    assert not any(ok for _, _, ok in ran)                                  # 更新期間新的一輪不跑
    with deploy_guard(lock) as ok:
        assert ok                                                           # 做完就放開


def test_failed_pull_stops_the_update(tmp_path):
    ran = []
    assert ms.update(tmp_path, run=lambda cmd: ran.append(cmd[0]) or subprocess.CompletedProcess(cmd, 1)) == 1
    assert ran == ["git"]


def test_mac_setup_writes_a_readable_config_and_stores_the_password_in_the_keychain(tmp_path):
    mset = _mod("macsetup")
    home = tmp_path
    a = {"icloud": str(mset.icloud_drive(home) / "_WikiBox"), "wiki": str(home / "SOURCE5" / "WIKI"),
         "raw": str(home / "SOURCE5" / "Raw_Sources"), "label": "知識庫", "doc2md": str(mset.scribe2md_doc2md(home)),
         "mail_from": "amy@gmail.com", "mail_to": "amy@gmail.com", "claude": "/x/claude"}
    text = mset.render_config(a)
    assert text.startswith(mset.HEADER) and "記事本" not in text
    cfg = mset.ws.write_config(text, tmp_path / "state")
    assert cfg.doc2md_cmd[0].endswith("/meeting-scribe/app/.venv/bin/doc2md") and cfg.claude_cmd == ("/x/claude",)
    seen = []
    assert mset.save_password("amy@gmail.com", "abcd", run=lambda cmd, **k: seen.append(cmd) or
                              subprocess.CompletedProcess(cmd, 0))
    assert seen[0][:3] == ["/usr/bin/security", "add-generic-password", "-U"]
    assert seen[0][seen[0].index("-s") + 1] == "wiki-feeder-smtp"           # 與 osplat.secret 讀的同一個


def test_install_sh_runs_only_when_fully_downloaded_and_reads_the_keyboard():
    """curl … | bash:下載到一半斷線不可只跑了前半段;標準輸入是腳本本身,問答要從 /dev/tty 讀。"""
    p = ROOT / "install.sh"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n") and "\r" not in text
    assert text.rstrip().splitlines()[-1] == 'main "$@"' and text.count("\nmain() {") == 1
    assert "</dev/tty" in text and "wiki-agent.git" in text
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    assert os.access(p, os.X_OK)


@pytest.mark.parametrize("name", ["更新.command", "移除排程.command"])
def test_command_files_are_executable_zsh_and_exit_zero(name):
    """git clone 下來的 .command 才能雙擊(從網頁下載的帶隔離標記);要有執行權限、結尾明寫 exit 0。"""
    p = ROOT / name
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/zsh\n") and "\r" not in text and text.rstrip().endswith("exit 0")
    assert os.access(p, os.X_OK)
    assert subprocess.run(["zsh", "-n", str(p)]).returncode == 0
    mode = subprocess.run(["git", "ls-files", "-s", name], cwd=ROOT, capture_output=True, text=True).stdout
    assert not mode or mode.startswith("100755")                            # 進了 git 就要是可執行


# -- 介面語言 -------------------------------------------------------------------------------------------

def _fake_check(tmp_path, monkeypatch, output: str, expected: int = 1):
    """check():launchctl 換成假的,bootstrap 時寫出 `collect --list` 的輸出。"""
    _, state = ms.paths(tmp_path)
    log = state / "logs" / "check.launchd.log"

    def launchctl(*a):
        if a[0] == "bootstrap":
            log.write_text(output, encoding="utf-8")
        return subprocess.CompletedProcess(a, 0, "state = not running" if a[0] == "print" else "", "")
    monkeypatch.setattr(ms, "_launchctl", launchctl)
    monkeypatch.setattr(ms, "_expected_inboxes", lambda: expected)
    return ms.check(tmp_path, "test.wa")


def test_check_needs_a_readable_line_for_every_inbox(tmp_path, monkeypatch):
    assert _fake_check(tmp_path, monkeypatch, "icloud\t可讀,0 組候選\n") == 0
    assert _fake_check(tmp_path, monkeypatch, "") == 1                                  # 空輸出不算過
    out = "icloud\t可讀,0 組候選\nonedrive\t錯誤:onedrive 收件匣沒有讀取權限\n"
    assert _fake_check(tmp_path, monkeypatch, out, expected=2) == 1                     # 一個讀不到就不算過


def test_check_recognises_the_english_readable_marker(tmp_path, monkeypatch):
    """cli 照設定檔的語言印「可讀」;英文介面也要認得。要等主代理合併 locales/en.json 才會過。"""
    from wiki_feeder import i18n
    i18n.set_lang("en")
    word = ms.L("可讀")
    assert word != "可讀"
    assert _fake_check(tmp_path, monkeypatch, f"icloud\t{word}, 0 candidate groups\n") == 0


def test_sched_reads_the_language_from_the_config_file(tmp_path, monkeypatch):
    """.command 直接叫 macsched、不經 cli:自己讀 [general] language;沒有設定檔就照系統語言。"""
    monkeypatch.setattr(ms.i18n, "detect", lambda: "zh-Hans")
    assert ms.config_lang(tmp_path) == "zh-Hans"
    _, state = ms.paths(tmp_path)
    state.mkdir(parents=True)
    (state / "config.toml").write_text('[general]\nlanguage = "en"\n', encoding="utf-8")
    assert ms.config_lang(tmp_path) == "en"


SH_LANG = 'source <(sed "/^main \\"\\$@\\"$/d" install.sh); detect_lang "$1"'


@pytest.mark.parametrize("apple, want", [('(\n    "zh-Hant-TW",\n    "en-TW"\n)', "zh-Hant"),
                                         ('(\n    "zh-Hans-CN"\n)', "zh-Hans"),
                                         ('(\n    "en-US",\n    "zh-Hant-TW"\n)', "en"),
                                         ('( "zh-HK" )', "zh-Hant"), ("", "en")])
def test_install_sh_picks_its_message_language_from_the_first_system_language(apple, want):
    r = subprocess.run(["bash", "-c", SH_LANG, "_", apple], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == want


def test_install_sh_has_three_languages_for_every_message():
    """Python 裝好之前的訊息:每一句 msg 都給三種語言,不留單一語言的 echo。"""
    body = (ROOT / "install.sh").read_text(encoding="utf-8").split("\nmain() {", 1)[1]
    assert not [ln for ln in body.splitlines() if 'echo "' in ln and any("一" <= c <= "鿿" for c in ln)]
    r = subprocess.run(["bash", "-c", 'source <(sed "/^main \\"\\$@\\"$/d" install.sh); WA_LANG=zh-Hans msg 甲 乙 C; '
                        'WA_LANG=en msg 甲 乙 C'], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.split() == ["乙", "C"]
