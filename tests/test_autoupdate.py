"""朋友版的自動更新(wiki_feeder.autoupdate、scripts/winautoupdate.py;spec §7.9)。
Windows 的行為照原樣守(`_deps` 預設 windows=True,在 Mac 上也跑);Mac 的 tick 在本檔最後,換版程式
scripts/macautoupdate.py 在 tests/test_macautoupdate.py。

假的公開 repo 建在 tmp_path,commit 時間用 GIT_COMMITTER_DATE 造;朋友的 clone 的 origin 寫真的公開 repo 網址
(判斷「是不是朋友的 clone」看的是它),再用 repo 自己的 url.<假的>.insteadOf 導到假的,不碰網路。
換版程式不開真的行程、不碰工作排程器:子行程換成記錄指令的假函式。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from wiki_feeder import autoupdate as au

PUBLIC = "https://github.com/VincentLiang1/wiki-agent.git"
NOW = time.time()
DAY = 86400


def _git(*args, cwd, when=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"@{int(when)} +0800"
    r = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _entry(src, human=False, text="改了一點"):
    return {"source": src, "date": "2026-10-2x", "needs_human": human, "zh-Hant": text, "zh-Hans": text, "en": "x"}


class Pub:
    """假的公開 repo:publish 一版就是一個 commit(訊息「發佈 日期(來源 <sha>)」、根目錄 UPDATES.json 多一筆)。"""
    def __init__(self, tmp: Path):
        self.bare, self.work = tmp / "pub.git", tmp / "pubwork"
        _git("init", "-q", "--bare", str(self.bare), cwd=tmp)
        _git("clone", "-q", str(self.bare), str(self.work), cwd=tmp)
        self.notes: list[dict] = []
        self.shas: dict[str, str] = {}

    def publish(self, src: str, when: float, human=False):
        self.notes.insert(0, _entry(src, human, f"{src} 的說明"))
        (self.work / "UPDATES.json").write_text(json.dumps(self.notes, ensure_ascii=False), encoding="utf-8")
        (self.work / "app.txt").write_text(src, encoding="utf-8")
        (self.work / "scripts").mkdir(exist_ok=True)
        (self.work / "scripts" / "winautoupdate.py").write_text("# 換版程式\n", encoding="utf-8")
        (self.work / "scripts" / "macautoupdate.py").write_text("# 換版程式\n", encoding="utf-8")
        _git("add", "-A", cwd=self.work)
        _git("commit", "-q", "-m", f"發佈 2026-10-2x(來源 {src})", cwd=self.work, when=when)
        _git("push", "-q", "origin", "HEAD:main", cwd=self.work)
        self.shas[src] = _git("rev-parse", "HEAD", cwd=self.work)
        return self.shas[src]

    def friend(self, tmp: Path, at: str, origin=PUBLIC) -> Path:
        root = tmp / "friend"
        _git("clone", "-q", str(self.bare), str(root), cwd=tmp)
        _git("reset", "-q", "--hard", self.shas[at], cwd=root)
        _git("remote", "set-url", "origin", origin, cwd=root)
        _git("config", f"url.{self.bare.as_posix()}.insteadOf", PUBLIC, cwd=root)
        return root


class Box:
    def __init__(self):
        self.spawned, self.mails, self.enabled = [], [], []


def _deps(box: Box, **kw) -> au.UpdateDeps:
    d = au.UpdateDeps(now=lambda: NOW, run=au._git_local, get=None,
                      mail=lambda cfg, s, b: box.mails.append((s, b)),
                      spawn=lambda cmd: box.spawned.append(cmd) or 4242,
                      alive=lambda pid: False, enable=lambda folder: box.enabled.append(folder), windows=True)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


@pytest.fixture
def ucfg(cfg):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return replace(cfg, auto_update=True, mail_from="me@x", mail_to="t@t")


def _arg(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_takes_the_newest_version_once_it_is_a_day_old(ucfg, tmp_path):
    """換到最新版、中間的版本跳過,說明照樣全列(使用者 2026-10-23)。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    want = pub.publish("ccccccc", NOW - 1.5 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box)) is True
    [cmd] = box.spawned
    assert _arg(cmd, "--target") == want and _arg(cmd, "--kind") == "git" and _arg(cmd, "--folder") == "wf"
    assert "-S" in cmd and "-I" in cmd                          # 換版程式不載入 site-packages
    assert "bbbbbbb 的說明" in _arg(cmd, "--notes") and "ccccccc 的說明" in _arg(cmd, "--notes")
    assert json.loads(ucfg.update_lock_path.read_text())["pid"] == 4242
    assert "started" in ucfg.update_log_path.read_text(encoding="utf-8")


def test_newest_under_a_day_waits_for_it_instead_of_taking_the_previous(ucfg, tmp_path):
    """最新版發佈不滿 1 天:先不換(24 小時內發現問題可以補發下一版),也不換上一版;
    等到它滿 1 天那一輪就換,不必再等一整天(關機 3 天、開機時最新版才發佈 1 小時)。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    want = pub.publish("ccccccc", NOW - 3600)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box)) is False and not box.spawned and not box.mails
    assert "waiting" in ucfg.update_log_path.read_text(encoding="utf-8")
    ready = NOW - 3600 + DAY
    assert au.tick(ucfg, root, "wf", _deps(box, now=lambda: ready - 60)) is False and not box.spawned
    assert au.tick(ucfg, root, "wf", _deps(box, now=lambda: ready + 60)) is True
    [cmd] = box.spawned
    assert _arg(cmd, "--target") == want


def test_already_on_the_newest_does_nothing(ucfg, tmp_path):
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("ccccccc", NOW - 3600)
    root = pub.friend(tmp_path, "ccccccc")
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box)) is False and not box.spawned and not box.mails


def test_development_repo_is_never_touched(ucfg, tmp_path):
    """使用者自己的開發目錄(origin 是私人的 wiki-feeder),包括使用者那台 Windows,一律不動,也不寄信。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa", origin="https://github.com/someone/private-repo.git")
    box = Box()
    fetched = []
    assert au.tick(ucfg, root, "wf", _deps(box, run_net=lambda *a, **k: fetched.append(a))) is False
    assert not box.spawned and not box.mails and not fetched


def test_uncommitted_changes_block_and_mail_once(ucfg, tmp_path):
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    (root / "app.txt").write_text("朋友改過", encoding="utf-8")
    (root / "my-notes.txt").write_text("沒追蹤的檔不算", encoding="utf-8")
    box = Box()
    au.tick(ucfg, root, "wf", _deps(box))
    assert not box.spawned and len(box.mails) == 1 and "app.txt" in box.mails[0][1]
    au.tick(ucfg, root, "wf", _deps(box, now=lambda: NOW + DAY + 60))     # 隔天再查:同一版、同一種結果不重寄
    assert len(box.mails) == 1


def test_untracked_files_alone_do_not_block(ucfg, tmp_path):
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    (root / "my-notes.txt").write_text("朋友的", encoding="utf-8")
    box = Box()
    au.tick(ucfg, root, "wf", _deps(box))
    assert len(box.spawned) == 1


def test_needs_human_version_only_mails(ucfg, tmp_path):
    """要人動手的版本不自動裝,寄信請朋友執行 Update.bat;跳過好幾版時,中間任何一版要人動手都算。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 4 * DAY)
    pub.publish("bbbbbbb", NOW - 3 * DAY, human=True)
    pub.publish("ccccccc", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    au.tick(ucfg, root, "wf", _deps(box))
    assert not box.spawned and len(box.mails) == 1
    subject, body = box.mails[0]
    assert "動手" in subject and "Update.bat" in body and "bbbbbbb 的說明" in body
    au.tick(ucfg, root, "wf", _deps(box, now=lambda: NOW + DAY + 60))
    assert len(box.mails) == 1


def test_offline_only_logs_and_retries_in_an_hour(ucfg, tmp_path):
    """連不上網路不算警示:不寄信、不算失敗,只寫 log;一小時後再查,不是等一天、也不是每 3 分鐘。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box, calls = Box(), []

    def down(cmd, timeout, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: unable to access: Could not resolve host: github.com")
    au.tick(ucfg, root, "wf", _deps(box, run_net=down))
    assert not box.mails and not box.spawned and "offline" in ucfg.update_log_path.read_text(encoding="utf-8")
    au.tick(ucfg, root, "wf", _deps(box, run_net=down, now=lambda: NOW + 600))
    assert len(calls) == 1
    au.tick(ucfg, root, "wf", _deps(box, run_net=down, now=lambda: NOW + 3700))
    assert len(calls) == 2 and not box.mails


def test_auto_update_off_does_not_even_fetch(ucfg, tmp_path):
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box, fetched = Box(), []
    au.tick(replace(ucfg, auto_update=False), root, "wf", _deps(box, run_net=lambda *a, **k: fetched.append(a)))
    assert not fetched and not box.spawned


def test_result_is_mailed_once_and_a_failed_version_is_not_retried(ucfg, tmp_path):
    """結果另寄一封信:成功寫新版與說明;失敗並已退回,主旨開頭「⚠️ 需要處理」、寫哪一步、系統照常在跑。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    want = pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    res = {"result": "failed", "step": "check", "detail": "收件匣讀不到", "target": want, "label": "bbbbbbb",
           "old": "aaaaaaa"}
    ucfg.update_result_path.write_text(json.dumps(res), encoding="utf-8")
    au.tick(ucfg, root, "wf", _deps(box))
    [(subject, body)] = box.mails
    assert subject.startswith("⚠️ 需要處理") and "試讀" in body and "照常在跑" in body and "aaaaaaa" in subject
    assert not box.spawned                                     # 裝失敗過的那一版不再自動重試
    ucfg.update_result_path.write_text(json.dumps(res), encoding="utf-8")
    au.tick(ucfg, root, "wf", _deps(box, now=lambda: NOW + DAY + 60))
    assert len(box.mails) == 1
    log = ucfg.update_log_path.read_text(encoding="utf-8")
    assert "aaaaaaa\tbbbbbbb\tfailed" in log


def test_mail_that_cannot_be_sent_is_retried(ucfg, tmp_path):
    root = tmp_path / "nothing"
    root.mkdir()
    box = Box()
    ucfg.update_result_path.write_text(json.dumps({"result": "ok", "target": "t1", "label": "v1", "notes": "說明"}),
                                       encoding="utf-8")

    def boom(cfg, s, b):
        raise OSError("smtp down")
    au.tick(ucfg, root, "wf", _deps(box, mail=boom))
    au.tick(ucfg, root, "wf", _deps(box))
    [(subject, body)] = box.mails
    assert "v1" in subject and "說明" in body


def test_without_mail_settings_it_only_logs(cfg, tmp_path):
    c = replace(cfg, auto_update=True, mail_to="", mail_from="")
    c.state_dir.mkdir(parents=True, exist_ok=True)
    box = Box()
    c.update_result_path.write_text(json.dumps({"result": "ok", "target": "t1", "label": "v1"}), encoding="utf-8")
    au.tick(c, tmp_path, "wf", _deps(box))
    assert not box.mails and "\tv1\tok" in c.update_log_path.read_text(encoding="utf-8")


def test_running_updater_pauses_the_agents_check_and_a_dead_one_is_recovered(ucfg, tmp_path):
    """換版程式在跑:收件、攝入被停用是正常的(回 True,不查排程沒載入)。它死掉了(斷電):排程絕不能停在停用。"""
    box = Box()
    ucfg.update_lock_path.write_text(json.dumps({"pid": 99, "target": "t1", "label": "v1", "old": "v0"}))
    assert au.tick(ucfg, tmp_path, "wf", _deps(box, alive=lambda pid: True)) is True and not box.enabled
    assert au.tick(ucfg, tmp_path, "wf", _deps(box, alive=lambda pid: False)) is False
    assert box.enabled == ["wf"] and not ucfg.update_lock_path.exists()
    assert len(box.mails) == 1 and "中斷" in box.mails[0][0] and "Update.bat" in box.mails[0][1]


# -- zip 裝的 --------------------------------------------------------------------------

def _zip_bytes(tag, notes):
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from test_winupdate import BASE, _zip
    return _zip({**BASE, "UPDATES.json": json.dumps(notes).encode()}, tag=tag)


def test_zip_install_takes_the_newest_release_with_the_package(ucfg, tmp_path):
    """附了安裝包的最新 Release,剛發佈也換;最新那版還沒附 zip(Windows 還沒收尾)就拿附了的那一版。"""
    root = tmp_path / "wiki-agent"
    root.mkdir()
    (root / "VERSION").write_text("tag=r1\n", encoding="utf-8")
    (root / "MANIFEST").write_text("VERSION\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "winautoupdate.py").write_text("#\n", encoding="utf-8")
    z2 = _zip_bytes("r2", [_entry("s2"), _entry("s1")])
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))   # noqa: E731
    rels = [{"tag_name": "r3", "draft": False, "published_at": iso(NOW - 600),
             "assets": [{"name": "wiki-agent-mac.zip", "browser_download_url": "u3"}]},
            {"tag_name": "r2", "draft": False, "published_at": iso(NOW - 2 * DAY),
             "assets": [{"name": "wiki-agent-win.zip", "browser_download_url": "u2"}]},
            {"tag_name": "r1", "draft": False, "published_at": iso(NOW - 5 * DAY), "assets": []}]
    got = []

    def get(url, timeout=60):
        got.append(url)
        return json.dumps(rels).encode() if url == au.RELEASES_API else {"u2": z2}[url]
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box, get=get)) is True
    [cmd] = box.spawned
    assert _arg(cmd, "--kind") == "zip" and _arg(cmd, "--target") == "r2" and "u3" not in got
    assert Path(_arg(cmd, "--zip")).read_bytes() == z2 and _arg(cmd, "--current") == "r1"


# -- 換版程式 -------------------------------------------------------------------------

def _updater():
    spec = importlib.util.spec_from_file_location("winautoupdate_script",
                                                  Path(__file__).parents[1] / "scripts" / "winautoupdate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run_updater(tmp_path, fail_on=None, kind="git"):
    m = _updater()
    cmds = []

    def run(cmd, timeout=3600):
        cmds.append(cmd)
        text = " ".join(cmd)
        if fail_on and fail_on in text and not any("reset" in c for c in cmd):
            return subprocess.CompletedProcess(cmd, 1, "", f"{fail_on} 壞了")
        if cmd[-1] == "HEAD":
            return subprocess.CompletedProcess(cmd, 0, "oldhead123\n", "")
        if cmd[0] == "powershell":
            return subprocess.CompletedProcess(cmd, 0, "Ready\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    a = Namespace(root=str(tmp_path), state=str(tmp_path / "state"), kind=kind, target="newsha", label="v2",
                  folder="wf", parent=0, notes="說明", zip=str(tmp_path / "u.zip"), current="r1")
    res = m.Updater(a, run=run, sleep=lambda s: None, alive=lambda pid: False).main()
    return res, [" ".join(c) for c in cmds]


def test_updater_happy_path_keeps_watch_and_checks_reading(tmp_path):
    res, cmds = _run_updater(tmp_path)
    assert res["result"] == "ok" and res["old"] == "oldhead"
    i = {k: next(n for n, c in enumerate(cmds) if k in c) for k in
         ("disable --keep-watch", "merge --ff-only", " sync", "winsched.py enable", "collect --list --dirs")}
    assert i["disable --keep-watch"] < i["merge --ff-only"] < i[" sync"] < i["winsched.py enable"] \
        < i["collect --list --dirs"]


def test_updater_rolls_back_when_the_trial_read_fails(tmp_path):
    """試讀失敗:退回舊的 HEAD、uv sync、重新啟用排程。排程絕不能停在停用。"""
    res, cmds = _run_updater(tmp_path, fail_on="collect --list")
    assert res["result"] == "failed" and res["step"] == "check" and "壞了" in res["detail"]
    i_check = next(n for n, c in enumerate(cmds) if "collect --list" in c)
    after = cmds[i_check:]
    assert any("reset --hard -q oldhead123" in c for c in after)
    i_reset = next(n for n, c in enumerate(after) if "reset --hard" in c)
    assert any(c.endswith(" sync") for c in after[i_reset:]) and "winsched.py enable" in after[-1]


def test_updater_reenables_even_when_disable_fails(tmp_path):
    res, cmds = _run_updater(tmp_path, fail_on="disable")
    assert res["result"] == "failed" and res["step"] == "disable"
    assert not any("merge" in c or "reset" in c for c in cmds) and "winsched.py enable" in cmds[-1]


def test_updater_zip_backs_up_before_switching_and_restores(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "update-backup").mkdir()
    res, cmds = _run_updater(tmp_path, fail_on=" sync", kind="zip")
    assert res["result"] == "rollback_failed"                    # 退回時的 uv sync 也失敗(假的一律失敗)
    i_b = next(n for n, c in enumerate(cmds) if "--backup" in c)
    i_z = next(n for n, c in enumerate(cmds) if "--zip" in c)
    assert i_b < i_z and any("--restore" in c for c in cmds[i_z:]) and "winsched.py enable" in cmds[-1]


def test_missing_updater_script_only_logs(ucfg, tmp_path):
    """朋友那份沒有換版程式(發佈漏了):不開行程、不當成中斷,只寫 log。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    (root / "scripts" / "winautoupdate.py").unlink()
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box)) is False
    assert not box.spawned and not box.mails and "check_failed" in ucfg.update_log_path.read_text(encoding="utf-8")


def test_zip_newest_under_a_day_waits_and_is_not_downloaded(ucfg, tmp_path):
    root = tmp_path / "wiki-agent"
    root.mkdir()
    (root / "VERSION").write_text("tag=r1\n", encoding="utf-8")
    (root / "MANIFEST").write_text("VERSION\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "winautoupdate.py").write_text("#\n", encoding="utf-8")
    # 照真的安裝放 winupdate.py:原本靠前面的測試先 import 過才綠,單獨跑或平行跑(xdist)就紅
    (root / "scripts" / "winupdate.py").write_bytes((Path(__file__).parents[1] / "scripts" / "winupdate.py").read_bytes())
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))   # noqa: E731
    rels = [{"tag_name": "r2", "draft": False, "published_at": iso(NOW - 3600),
             "assets": [{"name": "wiki-agent-win.zip", "browser_download_url": "u2"}]},
            {"tag_name": "r1", "draft": False, "published_at": iso(NOW - 5 * DAY), "assets": []}]
    got = []

    def get(url, timeout=60):
        got.append(url)
        return json.dumps(rels).encode()
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box, get=get)) is False
    assert not box.spawned and got == [au.RELEASES_API]
    assert "waiting" in ucfg.update_log_path.read_text(encoding="utf-8")


# -- 自動更新本身壞了:開機好幾天都沒查成功就警示(repair._update_stale) ------------------------

def _stale(cfg, day0: float, windows=True):
    from wiki_feeder import repair
    got = []

    def on(i):                                     # 第 i 天有開機、watch 跑了一輪
        repair._update_stale(cfg, day0 + i * DAY, lambda key, subject, body: got.append(subject + body), windows)
        return list(got)
    return on


def _state(cfg, **kw):
    cfg.update_state_path.write_text(json.dumps(kw), encoding="utf-8")


DAY0 = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))


def test_three_days_on_without_a_good_check_alerts(ucfg):
    """壞掉的版本裝上去,之後的版本都要靠它自己的更新程式:開機的日子連續 3 天沒查成功就請朋友手動 Update.bat。"""
    _state(ucfg, ok_day="2026-10-01")
    on = _stale(ucfg, DAY0)
    assert on(0) == [] and on(1) == [] and on(2) == []
    [msg] = on(3)
    assert "Update.bat" in msg and "自動更新好幾天沒有查成功" in msg


def test_days_the_computer_was_off_do_not_count(ucfg):
    """朋友好幾天沒開機,不是自動更新壞了:只算 watch 有跑的日子。"""
    _state(ucfg, ok_day="2026-10-01")
    on = _stale(ucfg, DAY0)
    on(0)
    assert on(10) == [] and on(11) == []           # 關機 9 天後開機兩天:只算 2 天
    assert len(on(12)) == 1


def test_offline_days_and_a_good_check_do_not_count(ucfg):
    """帶筆電到沒網路的地方幾天是正常的;查成功一次就從頭算。"""
    _state(ucfg, ok_day="2026-10-01", offline_days=["2026-10-02", "2026-10-03", "2026-10-04"])
    on = _stale(ucfg, DAY0)
    assert on(1) == [] and on(2) == [] and on(3) == [] and on(4) == [] and on(5) == []
    _state(ucfg, ok_day="2026-10-06", offline_days=["2026-10-02", "2026-10-03", "2026-10-04"])
    assert on(6) == [] and on(7) == []                # 從 10-06 重新算


def test_unreadable_state_counts_as_not_checked_and_auto_update_off_is_quiet(ucfg):
    ucfg.update_state_path.write_text("{壞掉", encoding="utf-8")
    on = _stale(ucfg, DAY0)
    on(0), on(1)
    assert len(on(2)) == 1
    off = replace(ucfg, auto_update=False)
    from wiki_feeder import repair
    got = []
    repair._update_stale(off, DAY0 + 9 * DAY, lambda *a: got.append(a))
    assert got == []


def test_tick_records_good_checks_and_offline_days(ucfg, tmp_path):
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    au.tick(ucfg, root, "wf", _deps(Box()))                       # 已是最新:也算查成功
    st = json.loads(ucfg.update_state_path.read_text(encoding="utf-8"))
    assert st["ok_day"] == au._day(NOW) and not st.get("offline_days")

    def down(cmd, timeout, **kw):
        return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: unable to access: Could not resolve host: github.com")
    later = NOW + 2 * DAY
    au.tick(ucfg, root, "wf", _deps(Box(), run_net=down, now=lambda: later))
    st = json.loads(ucfg.update_state_path.read_text(encoding="utf-8"))
    assert st["offline_days"] == [au._day(later)] and st["ok_day"] == au._day(NOW)


def test_missing_updater_is_not_a_good_check(ucfg, tmp_path):
    """換版程式不見了就是自動更新壞了:不可記成查成功,不然永遠不會警示。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    (root / "scripts" / "winautoupdate.py").unlink()
    au.tick(ucfg, root, "wf", _deps(Box()))
    assert "ok_day" not in json.loads(ucfg.update_state_path.read_text(encoding="utf-8"))


# -- Mac(git clone 與雙擊 App;2026-10-23)--------------------------------------------------------

def _mac(box, **kw):
    return _deps(box, windows=False, **kw)


def test_mac_git_install_spawns_the_mac_updater(ucfg, tmp_path):
    """Mac 用 python 本體(不在 .venv、不在 App 裡,換版途中兩個都會被換掉)跑 macautoupdate.py,帶 launchd 標籤的開頭。"""
    pub = Pub(tmp_path)
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    v2 = pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box)) is True
    [cmd] = box.spawned
    assert cmd[1:4] == ["-I", "-S", "-B"] and cmd[4].endswith("macautoupdate.py")
    assert _arg(cmd, "--prefix") == "test.wa" and _arg(cmd, "--kind") == "git" and _arg(cmd, "--target") == v2
    assert "--folder" not in cmd and "pythonw" not in cmd[0]


def test_mac_python_version_change_only_mails(ucfg, tmp_path):
    """git 裝的 .python-version 換了:uv sync 換掉 python 本體,完整磁碟取用權限就掉了、收件匣讀不到。
    換之前就看出來,只寄信請朋友手動更新、重加權限,不開換版程式。"""
    pub = Pub(tmp_path)
    (pub.work / ".python-version").write_text("3.12\n", encoding="utf-8")
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    (pub.work / ".python-version").write_text("3.13\n", encoding="utf-8")
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box)) is False and not box.spawned
    [(subject, body)] = box.mails
    assert "動手" in subject and "3.12 → 3.13" in body and "完整磁碟取用權限" in body and "Update.command" in body
    au.tick(ucfg, root, "test.wa", _mac(box, now=lambda: NOW + DAY + 60))
    assert len(box.mails) == 1                                       # 同一版只寄一次


def test_windows_ignores_python_version_change(ucfg, tmp_path):
    pub = Pub(tmp_path)
    (pub.work / ".python-version").write_text("3.12\n", encoding="utf-8")
    pub.publish("aaaaaaa", NOW - 3 * DAY)
    (pub.work / ".python-version").write_text("3.13\n", encoding="utf-8")
    pub.publish("bbbbbbb", NOW - 2 * DAY)
    root = pub.friend(tmp_path, "aaaaaaa")
    box = Box()
    assert au.tick(ucfg, root, "wf", _deps(box)) is True


def _git_repo(path: Path, origin: str | None) -> Path:
    path.mkdir(parents=True)
    _git("init", "-q", str(path), cwd=path.parent)
    if origin:
        _git("remote", "add", "origin", origin, cwd=path)
    return path


@pytest.mark.parametrize("windows", [True, False])
def test_only_friends_installs_count(tmp_path, windows):
    """紅線:使用者本人的開發目錄與發佈副本(origin 是私人 repo、本機路徑)絕不動——旁邊放了 .app-bundle、VERSION、
    MANIFEST 也一樣:有 .git 就只看 origin。"""
    kind = lambda p: au.install_kind(p, au._git_local, windows)   # noqa: E731
    dev = _git_repo(tmp_path / "dev", "https://github.com/someone/private-repo.git")
    for f in (".app-bundle", "VERSION", "MANIFEST"):
        (dev / f).write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    deploy = _git_repo(tmp_path / "deploy", str(dev))
    (deploy / ".app-bundle").write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    (deploy / "VERSION").write_text("abc1234\n", encoding="utf-8")
    assert kind(dev) == "" and kind(deploy) == "" and kind(_git_repo(tmp_path / "none", None)) == ""
    assert kind(_git_repo(tmp_path / "friend", PUBLIC)) == "git"
    app = tmp_path / "app"
    app.mkdir()
    (app / ".app-bundle").write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    assert kind(app) == ""                                            # 沒有 VERSION:看不出來,不動
    (app / "VERSION").write_text("abc1234\n", encoding="utf-8")
    assert kind(app) == ("" if windows else "app")
    z = tmp_path / "zip"
    z.mkdir()
    (z / "VERSION").write_text("tag=r1\n", encoding="utf-8")
    (z / "MANIFEST").write_text("VERSION\n", encoding="utf-8")
    assert kind(z) == ("zip" if windows else "")


def _app_zip(version: str, notes: list[dict] | None) -> bytes:
    import io
    import plistlib
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("wiki-agent.app/Contents/Info.plist", plistlib.dumps({"CFBundleVersion": version}))
        if notes is not None:
            zf.writestr("wiki-agent.app/Contents/Resources/payload/UPDATES.json", json.dumps(notes))
    return buf.getvalue()


def _app_root(tmp_path, current="aaaaaaa", notes=None):
    root = tmp_path / "wiki-agent"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "macautoupdate.py").write_text("#\n", encoding="utf-8")
    (root / ".app-bundle").write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    (root / "VERSION").write_text(current + "\n", encoding="utf-8")
    if notes is not None:
        (root / "UPDATES.json").write_text(json.dumps(notes), encoding="utf-8")
    return root


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _rel(tag, age, url="uc"):
    """附了 Mac App 的正式 Release,age 秒前發佈。"""
    return {"tag_name": tag, "draft": False, "published_at": _iso(NOW - age),
            "assets": [{"name": "wiki-agent-mac.zip", "browser_download_url": url}]}


def test_mac_app_install_takes_the_newest_release_with_the_mac_app(ucfg, tmp_path):
    """附了 wiki-agent-mac.zip 的最新正式 Release(草稿、只附 Windows 的跳過);舊的 tag(mac-日期-sha)也認得出現在這版。"""
    root = _app_root(tmp_path, notes=[_entry("aaaaaaa")])
    z = _app_zip("ccccccc", [_entry("ccccccc"), _entry("bbbbbbb"), _entry("aaaaaaa")])
    rels = [{"tag_name": "20261025-ddddddd", "draft": True, "published_at": None,
             "assets": [{"name": "wiki-agent-mac.zip", "browser_download_url": "ud"}]},
            {"tag_name": "20261024-ccccccc", "draft": False, "published_at": _iso(NOW - 2 * DAY),
             "assets": [{"name": "wiki-agent-mac.zip", "browser_download_url": "uc"},
                        {"name": "wiki-agent-win.zip", "browser_download_url": "wc"}]},
            _rel("mac-20261023-aaaaaaa", 5 * DAY, "ua")]
    got = []

    def get(url, timeout=60):
        got.append(url)
        return json.dumps(rels).encode() if url == au.RELEASES_API else {"uc": z}[url]
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box, get=get)) is True
    [cmd] = box.spawned
    assert _arg(cmd, "--kind") == "app" and _arg(cmd, "--target") == "20261024-ccccccc"
    assert _arg(cmd, "--current") == "aaaaaaa" and Path(_arg(cmd, "--zip")).read_bytes() == z
    assert "ccccccc" in _arg(cmd, "--notes") and "bbbbbbb" in _arg(cmd, "--notes") and got == [au.RELEASES_API, "uc"]


def test_mac_app_already_newest_and_too_new(ucfg, tmp_path):
    root = _app_root(tmp_path, current="ccccccc")
    rels = [_rel("20261024-ccccccc", 2 * DAY)]
    box = Box()
    get = lambda url, timeout=60: json.dumps(rels).encode()   # noqa: E731
    assert au.tick(ucfg, root, "test.wa", _mac(box, get=get)) is False and not box.spawned
    root2 = _app_root(tmp_path / "b", current="aaaaaaa")
    rels[0]["published_at"] = _iso(NOW - 3600)
    c2 = replace(ucfg, state_dir=tmp_path / "state2")
    c2.state_dir.mkdir()
    assert au.tick(c2, root2, "test.wa", _mac(box, get=get)) is False and not box.spawned
    assert "waiting" in c2.update_log_path.read_text(encoding="utf-8")


def test_mac_app_needs_human_in_a_skipped_version_only_mails(ucfg, tmp_path):
    """跳過好幾版時,中間那一版要人動手也算(App 的 payload 帶 UPDATES.json 才算得出來)。信寫 Mac 的做法。"""
    root = _app_root(tmp_path, notes=[_entry("aaaaaaa")])
    z = _app_zip("ccccccc", [_entry("ccccccc"), _entry("bbbbbbb", human=True), _entry("aaaaaaa")])
    rels = [_rel("20261024-ccccccc", 2 * DAY)]

    def get(url, timeout=60):
        return json.dumps(rels).encode() if url == au.RELEASES_API else z
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box, get=get)) is False and not box.spawned
    [(subject, body)] = box.mails
    assert "動手" in subject and "Update.bat" not in body


def test_mac_app_zip_with_another_version_inside_is_not_installed(ucfg, tmp_path):
    root = _app_root(tmp_path)
    rels = [_rel("20261024-ccccccc", 2 * DAY)]

    def get(url, timeout=60):
        return json.dumps(rels).encode() if url == au.RELEASES_API else _app_zip("eeeeeee", [])
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box, get=get)) is False and not box.spawned


def test_mac_app_failed_version_is_not_downloaded_again(ucfg, tmp_path):
    """換失敗過的那一版:不再下載(App 約 29 MB)、不再重試,也不退而裝它前一版;等更新的版本。"""
    root = _app_root(tmp_path)
    rels = [_rel("20261024-ccccccc", 2 * DAY), _rel("20261023-bbbbbbb", 3 * DAY, "ub")]
    got = []

    def get(url, timeout=60):
        got.append(url)
        return json.dumps(rels).encode() if url == au.RELEASES_API else _app_zip("ccccccc", [])
    _state(ucfg, failed=["20261024-ccccccc"])
    box = Box()
    assert au.tick(ucfg, root, "test.wa", _mac(box, get=get)) is False and not box.spawned
    assert got == [au.RELEASES_API]


def test_mac_mails_say_what_to_do_on_a_mac(ucfg, tmp_path, monkeypatch):
    """失敗、中斷的信:Mac 寫終端機與 Update.command／換新版 App,不寫 PowerShell、Update.bat。"""
    box = Box()
    monkeypatch.setattr(au, "_root_hint", lambda: str(tmp_path))
    ucfg.update_result_path.write_text(json.dumps({"result": "failed", "target": "t1", "label": "v1", "old": "v0",
                                                   "step": "check", "detail": "讀不到"}), encoding="utf-8")
    au.tick(ucfg, tmp_path, "test.wa", _mac(box))
    ucfg.update_lock_path.write_text(json.dumps({"pid": 99, "target": "t2", "label": "v2", "old": "v0"}))
    (tmp_path / ".app-bundle").write_text("/Applications/wiki-agent.app\n", encoding="utf-8")
    au.tick(ucfg, tmp_path, "test.wa", _mac(box))
    (failed, interrupted) = box.mails
    assert "終端機" in failed[1] and "PowerShell" not in failed[1] and "試讀" in failed[1]
    assert "wiki-agent-mac.zip" in interrupted[1] and "Update.bat" not in interrupted[1]
    assert box.enabled == ["test.wa"]


def test_mac_stale_alert_says_what_to_do_on_a_mac(ucfg):
    _state(ucfg, ok_day="2026-10-01")
    on = _stale(ucfg, DAY0, windows=False)
    on(0), on(1), on(2)
    [msg] = on(3)
    assert "Update.command" in msg and "終端機" in msg and "Update.bat" not in msg


def test_mac_spawn_survives_the_launchd_job_in_its_own_session():
    """launchd 結束 watch 那個 job 時砍它的行程群組(2026-10-23 實測):換版程式要另開 session 才活得下來。"""
    if sys.platform == "win32":
        pytest.skip("Mac／Linux 的 setsid")
    pid = au._spawn_mac([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert os.getsid(pid) == pid and os.getsid(pid) != os.getsid(0)
    finally:
        os.kill(pid, 15)
        os.waitpid(pid, 0)

