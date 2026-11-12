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


def test_install_writes_three_agents_into_the_given_home(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ms, "_launchctl", lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ms.Config, "default", classmethod(lambda cls: type("C", (), {
        "icloud_inbox": tmp_path / "in", "onedrive_inbox": None, "gdrive_inbox": None})()))
    assert ms.install(tmp_path, "test.wa")
    agents = tmp_path / "Library" / "LaunchAgents"
    assert sorted(p.name for p in agents.iterdir()) == ["test.wa.collect.plist", "test.wa.process.plist",
                                                        "test.wa.watch.plist"]
    assert [a[0] for a in calls] == ["bootout", "bootstrap"] * 3
    ms.uninstall(tmp_path, "test.wa")
    assert not list(agents.iterdir())


def test_watch_runs_every_three_minutes_and_checks_its_own_labels(tmp_path, monkeypatch):
    """簡易看門狗(使用者 2026-10-23):每 3 分鐘;查的是同一組標籤(實測換 --prefix 時不可去查朋友真的那組)。"""
    import plistlib
    monkeypatch.setattr(ms, "_launchctl", lambda *a: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ms.Config, "default", classmethod(lambda cls: type("C", (), {
        "icloud_inbox": None, "onedrive_inbox": tmp_path / "od", "gdrive_inbox": None})()))
    app = tmp_path / "Applications" / "wiki-agent.app"
    assert ms.install(tmp_path, "test.wa", app=app)
    agents = tmp_path / "Library" / "LaunchAgents"
    d = plistlib.loads((agents / "test.wa.watch.plist").read_bytes())
    assert d["ProgramArguments"] == [str(app / ms.LAUNCHER), "watch", "--prefix", "test.wa"]   # App 版也經啟動器
    assert d["StartInterval"] == 180 and "WatchPaths" not in d
    assert plistlib.loads((agents / "test.wa.collect.plist").read_bytes())["StartInterval"] == 60


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
    a = {"icloud": str(mset.icloud_drive(home) / "_WikiBox"), "wiki": str(home / "LLMWiki" / "WIKI"),
         "raw": str(home / "LLMWiki" / "Raw_Sources"), "label": "知識庫", "doc2md": str(mset.scribe2md_doc2md(home)),
         "mail_from": "amy@gmail.com", "mail_to": "amy@gmail.com", "claude": "/x/claude"}
    text = mset.render_config(a)
    assert text.startswith(mset.HEADER) and "記事本" not in text
    cfg = mset.ws.write_config(text, tmp_path / "state")
    assert cfg.doc2md_cmd[0].endswith("/meeting-scribe/app/.venv/bin/doc2md") and cfg.claude_cmd == ("/x/claude",)
    keychain, seen = {}, []
    assert mset.save_password("amy@gmail.com", "abcd", run=_fake_security(keychain, seen))
    assert keychain == {("wiki-feeder-smtp", "amy@gmail.com"): "abcd"}     # 與 osplat.secret 讀的同一個


def _fake_security(keychain: dict, seen: list, stores: bool = True):
    """假的 /usr/bin/security:-i 照它的拆字讀標準輸入那一行(shlex 與它對 \\、" 的處理相同);find 照 -w 印密碼。"""
    import shlex

    def run(cmd, **k):
        seen.append((cmd, k.get("input")))
        if cmd[1:] == ["-i"]:
            a = shlex.split(k["input"])
            if stores and a[:2] == ["add-generic-password", "-U"]:
                keychain[(a[a.index("-s") + 1], a[a.index("-a") + 1])] = a[a.index("-w") + 1]
            return subprocess.CompletedProcess(cmd, 0, "", "")             # security -i 指令失敗也回 0
        assert cmd[1] == "find-generic-password", cmd
        key = (cmd[cmd.index("-s") + 1], cmd[cmd.index("-a") + 1])
        if key not in keychain:
            return subprocess.CompletedProcess(cmd, 44, "", "not found")
        return subprocess.CompletedProcess(cmd, 0, keychain[key] + "\n", "")
    return run


def test_mac_setup_keeps_the_mail_password_off_the_command_line():
    """稽核 (14):密碼放 security 的參數,執行瞬間 ps 看得到;要從 -i 的標準輸入送,含引號、反斜線也要存得對。"""
    mset = _mod("macsetup")
    for pw in ("abcdefghijklmnop", 'a"b\\c d'):
        keychain, seen = {}, []
        assert mset.save_password("amy@gmail.com", pw, run=_fake_security(keychain, seen))
        assert keychain[("wiki-feeder-smtp", "amy@gmail.com")] == pw
        assert all(pw not in a for cmd, _ in seen for a in cmd)
        assert seen[0][0] == ["/usr/bin/security", "-i"]


def test_mac_setup_reports_a_password_that_did_not_reach_the_keychain():
    """security -i 存失敗也回 0:不讀回來比對,問答會說存好了,寄信卻一直失敗。"""
    mset = _mod("macsetup")
    assert not mset.save_password("amy@gmail.com", "abcd", run=_fake_security({}, [], stores=False))
    old = {("wiki-feeder-smtp", "amy@gmail.com"): "old-password"}           # 已有舊的、更新沒成功
    assert not mset.save_password("amy@gmail.com", "abcd", run=_fake_security(old, [], stores=False))
    assert not mset.save_password("amy@gmail.com", "ab\ncd", run=_fake_security({}, []))



def uv_pin(name: str, text: str) -> tuple[str, str]:
    """稽核 (12):沒鎖版本的 `curl … astral.sh/uv/install.sh | sh` 跑的是當下網站上的任何東西;
    要裝固定版本、安裝程式比對過 SHA-256 才執行。回傳 (版本, 雜湊);App 的 setup.zsh 在 test_make_mac_app 比對。"""
    import re
    assert "astral.sh/uv/install.sh" not in text, name
    ver = re.search(r"^UV_VERSION=(\d+\.\d+\.\d+)$", text, re.M)
    sha = re.search(r"^UV_INSTALLER_SHA256=([0-9a-f]{64})$", text, re.M)
    assert ver and sha, name
    check = '&& echo "$UV_INSTALLER_SHA256  $uv_sh" | shasum -a 256 -c -s - && sh "$uv_sh"'
    assert 'curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" -o "$uv_sh"' in text and check in text, name
    assert not re.search(r"\|\s*sh\b", text), name                           # 不准再接 `| sh` 直接跑
    return ver[1], sha[1]


def test_install_sh_installs_a_pinned_uv_after_checking_its_hash():
    """App 的 setup.zsh 不在這裡比:make_mac_app.py 不發佈,公開複本跑這個檔會找不到(發佈時炸過,2026-11-12)。"""
    uv_pin("install.sh", (ROOT / "install.sh").read_text(encoding="utf-8"))

def test_install_sh_runs_only_when_fully_downloaded_and_reads_the_keyboard():
    """curl … | bash:下載到一半斷線不可只跑了前半段;標準輸入是腳本本身,問答要從 /dev/tty 讀。"""
    p = ROOT / "install.sh"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n") and "\r" not in text
    assert text.rstrip().splitlines()[-1] == 'main "$@"' and text.count("\nmain() {") == 1
    assert "</dev/tty" in text and "wiki-agent.git" in text
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    assert os.access(p, os.X_OK)


@pytest.mark.parametrize("name", ["Update.command", "Remove-Schedule.command"])
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


# -- 雙擊 App 安裝(scripts/make_mac_app.py):排程由 App 裡的啟動器跑 ---------------------------------------

def test_app_install_runs_the_agents_through_the_launcher_inside_the_app(tmp_path, monkeypatch):
    """讀取權限認的是 App:直接跑 python 的話系統不會問、背景永遠讀不到 iCloud 雲碟。"""
    mark = tmp_path / ".app-bundle"
    monkeypatch.setattr(ms, "APP_MARK", mark)
    assert ms.app_bundle() is None                                          # install.sh clone 的
    mark.write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    app = ms.app_bundle()
    assert app == Path("/Applications/wiki-agent.app")
    d = ms.plist_for("io.github.wiki-agent.collect", ["collect"], tmp_path, None, app)
    assert d["ProgramArguments"] == ["/Applications/wiki-agent.app/Contents/MacOS/wiki-agent", "collect"]
    mark.write_text("", encoding="utf-8")
    assert ms.app_bundle() is None


def test_app_check_reads_the_knowledge_base_too_and_waits_for_the_permission_dialog(tmp_path, monkeypatch):
    """知識庫在「文件」「桌面」是另一種權限:要趁安裝時讓系統問;等人按「允許」,不只等 60 秒。"""
    loaded = []
    monkeypatch.setattr(ms, "_load", lambda label, d, agents: loaded.append(d) or True)
    monkeypatch.setattr(ms, "_launchctl", lambda *a: subprocess.CompletedProcess(a, 0, "state = running", ""))
    monkeypatch.setattr(ms.time, "sleep", lambda s: None)
    monkeypatch.setattr(ms, "_expected_inboxes", lambda: 1)
    app = Path("/Applications/wiki-agent.app")
    assert ms.check(tmp_path, "test.wa", app) == 1
    assert loaded[0]["ProgramArguments"] == [str(app / ms.LAUNCHER), "collect", "--list", "--dirs"]
    assert ms.CHECK_WAIT_APP >= 300 > ms.CHECK_WAIT


def test_app_check_failure_points_at_files_and_folders_not_full_disk_access(tmp_path, monkeypatch, capsys):
    _, state = ms.paths(tmp_path)
    log = state / "logs" / "check.launchd.log"

    def launchctl(*a):
        if a[0] == "bootstrap":
            log.write_text("iCloud\t錯誤:Operation not permitted\n", encoding="utf-8")
        return subprocess.CompletedProcess(a, 0, "state = not running" if a[0] == "print" else "", "")
    monkeypatch.setattr(ms, "_launchctl", launchctl)
    monkeypatch.setattr(ms, "_expected_inboxes", lambda: 1)
    assert ms.check(tmp_path, "test.wa", Path("/Applications/wiki-agent.app")) == 1
    out = capsys.readouterr().out
    assert "檔案與檔案夾" in out and "完整磁碟取用權限" not in out


def test_expected_readable_counts_every_inbox_and_both_folders_of_each_knowledge_base(monkeypatch, tmp_path):
    cfg = type("C", (), {"icloud_inbox": tmp_path, "onedrive_inbox": None, "gdrive_inbox": None, "repos": (object(),),
                         "icloud_restart": False})()
    monkeypatch.setattr(ms.Config, "default", classmethod(lambda cls: cfg))
    assert ms._expected_inboxes() == 3
    cfg.icloud_restart = True             # iCloud 定時重啟還要讀得到 iCloud 同步狀態
    assert ms._expected_inboxes() == 4


def test_app_update_does_not_git_pull(tmp_path, monkeypatch, capsys):
    """App 版的 ~/wiki-agent 沒有 .git:更新是換新版 App 再雙擊。"""
    mark = tmp_path / ".app-bundle"
    mark.write_text("/Applications/wiki-agent.app", encoding="utf-8")
    monkeypatch.setattr(ms, "APP_MARK", mark)
    ran = []
    assert ms.update(tmp_path, run=lambda cmd: ran.append(cmd)) == 0
    assert ran == [] and "wiki-agent" in capsys.readouterr().out


SH_ASK = 'source <(sed "/^main \\"\\$@\\"$/d" install.sh); WA_TTY="$2" ask_lang "$1"'


@pytest.mark.parametrize("answer, default, want", [("", "zh-Hans", "zh-Hans"), ("3", "zh-Hant", "en"),
                                                   ("2", "en", "zh-Hans"), ("9", "en", "en"), (None, "zh-Hant", "zh-Hant")])
def test_install_sh_asks_the_language_first_with_the_same_line_as_the_wizard(tmp_path, answer, default, want):
    """一開始就選語言(使用者 2026-10-27),之後的訊息只用選的語言;問的那一行與問答(winsetup.lang_prompt)相同。
    讀不到鍵盤(None)就用預設。"""
    tty = tmp_path / "tty"
    if answer is not None:
        tty.write_text(answer + "\n", encoding="utf-8")
    r = subprocess.run(["bash", "-c", SH_ASK, "_", default, str(tty)], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == want
    ws = _mod("winsetup")
    assert r.stderr.startswith(ws.lang_prompt(default))


def test_install_sh_defaults_to_the_language_in_the_config_and_hands_the_choice_on(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('# x\n\n[general]\nlanguage = "zh-Hans"\n', encoding="utf-8")
    sh = 'source <(sed "/^main \\"\\$@\\"$/d" install.sh); config_lang "$1"'
    assert subprocess.run(["bash", "-c", sh, "_", str(cfg)], cwd=ROOT, capture_output=True, text=True).stdout == "zh-Hans\n"
    cfg.write_text('language = "fr"\n', encoding="utf-8")
    assert subprocess.run(["bash", "-c", sh, "_", str(cfg)], cwd=ROOT, capture_output=True, text=True).stdout == ""
    body = (ROOT / "install.sh").read_text(encoding="utf-8").split("\nmain() {", 1)[1]
    first_msg = body.index("    msg ")
    assert body.index('WA_LANG=$(ask_lang "$WA_LANG")') < first_msg
    assert body.index('export WIKI_AGENT_LANG="$WA_LANG"') < first_msg


def test_mac_setup_finds_onedrive_and_google_drive_under_cloudstorage(tmp_path):
    mset = _mod("macsetup")
    store = tmp_path / "Library" / "CloudStorage"
    (store / "OneDrive-個人").mkdir(parents=True)
    (store / "GoogleDrive-amy" / "My Drive").mkdir(parents=True)
    got = mset.find_clouds(tmp_path)
    assert got == {"icloud": None, "onedrive": store / "OneDrive-個人",
                   "gdrive": store / "GoogleDrive-amy" / "My Drive"}
