"""朋友版 Mac 自動更新的換版程式(scripts/macautoupdate.py;spec §7.9)。

外部指令(git、uv、rsync、ditto、codesign、spctl、macsched)換成記錄指令的假函式,不碰 launchd、不碰真的 App;
App 的改名、退回用 tmp_path 裡的假 App 真的做。deploy.lock 的等待用真的 flock。
"""
from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

if sys.platform != "darwin":
    # Windows 沒有 fcntl;release_win.py 在 Windows 解開安裝包跑全部測試,收集錯誤會擋下發佈
    pytest.skip("Mac 的換版程式(fcntl、ditto、codesign)", allow_module_level=True)

import fcntl  # noqa: E402

m = None


def _mod():
    global m
    if m is None:
        spec = importlib.util.spec_from_file_location("macautoupdate_script",
                                                      Path(__file__).parents[1] / "scripts" / "macautoupdate.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


def _app(path: Path, version: str) -> Path:
    (path / "Contents" / "Resources" / "python" / "bin").mkdir(parents=True)
    (path / "Contents" / "Resources" / "python" / "bin" / "python3.12").write_text("")
    (path / "Contents" / "Resources" / "payload").mkdir()
    (path / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": version}))
    return path


class Fake:
    """記下每個指令;fail_on 出現在指令裡就失敗(退回用的指令除外)。"""
    def __init__(self, tmp: Path, fail_on=None, team="TEAM1", bundle="io.github.wiki-agent", notarized=True,
                 python_moves=False):
        self.tmp, self.fail_on, self.team, self.bundle, self.notarized = tmp, fail_on, team, bundle, notarized
        self.cmds: list[str] = []
        self.python_moves = python_moves
        self.rolled = False

    def __call__(self, cmd, timeout=3600):
        text = " ".join(cmd)
        self.cmds.append(text)
        if "reset --hard" in text or "failed.app" in text:
            self.rolled = True
        if self.fail_on and self.fail_on in text and not self.rolled:
            return subprocess.CompletedProcess(cmd, 1, "", f"{self.fail_on} 壞了")
        if cmd[0] == "ditto":
            _app(Path(cmd[-1]) / "wiki-agent.app", "bbbbbbb")
        if cmd[0] == "codesign" and "-dvvv" in cmd:
            team = self.team if "update" in cmd[-1] else "TEAM1"
            return subprocess.CompletedProcess(cmd, 0, "", f"Identifier={self.bundle}\nTeamIdentifier={team}\n")
        if cmd[0] == "spctl":
            return subprocess.CompletedProcess(cmd, 0 if self.notarized else 3, "",
                                               "accepted\nsource=Notarized Developer ID" if self.notarized
                                               else "rejected\nsource=Unnotarized Developer ID")
        if cmd[1:2] == ["sync"] or cmd[-2:] == ["--frozen", "-q"]:
            (self.tmp / "root" / ".venv" / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
            if self.python_moves and "rollback" not in text and not self.rolled:
                self.moved = True
        if cmd[-1] == "HEAD":
            return subprocess.CompletedProcess(cmd, 0, "oldhead1234567\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _updater(tmp_path, kind="git", prefix="test.wa", fake=None, lock=None):
    mod = _mod()
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    if kind == "git":
        (root / ".git").mkdir(exist_ok=True)
    else:
        app = _app(tmp_path / "Applications" / "wiki-agent.app", "aaaaaaa")
        (root / ".app-bundle").write_text(f"{app}\n", encoding="utf-8")
    a = Namespace(root=str(root), state=str(tmp_path / "state"), kind=kind, target="20261024-bbbbbbb",
                  label="v2", prefix=prefix, notes="說明", zip=str(tmp_path / "u.zip"), current="aaaaaaa")
    fake = fake or Fake(tmp_path)
    u = mod.Updater(a, run=fake, sleep=lambda s: None, lock=lock or (lambda: open(tmp_path / "held", "w")))
    if fake.python_moves:
        u.python_now = lambda: "/new/python" if getattr(fake, "moved", False) and not fake.rolled else "/old/python"
    return u, fake


def _order(cmds, *keys):
    return [next(i for i, c in enumerate(cmds) if k in c) for k in keys]


def test_git_happy_path_switches_syncs_reinstalls_and_reads_under_launchd(tmp_path):
    u, f = _updater(tmp_path)
    res = u.main()
    assert res["result"] == "ok" and res["old"] == "oldhead"
    i = _order(f.cmds, "merge --ff-only", "sync --frozen", "macsched.py install", "macsched.py check")
    assert i == sorted(i) and all("--prefix test.wa" in c for c in f.cmds if "macsched.py" in c)
    assert not any("reset" in c for c in f.cmds)


def test_git_trial_read_failure_rolls_back(tmp_path):
    """試讀失敗:reset --hard 舊的 HEAD、uv sync、macsched install(排程一直都在,不必另外啟用)。"""
    u, f = _updater(tmp_path, fake=Fake(tmp_path, fail_on="macsched.py check"))
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "check" and "壞了" in res["detail"]
    after = f.cmds[_order(f.cmds, "macsched.py check")[0]:]
    assert "reset --hard -q oldhead1234567" in after[1] and "sync" in after[2] and "macsched.py install" in after[3]


def test_git_python_change_after_sync_rolls_back(tmp_path):
    """uv sync 換了 python 本體:完整磁碟取用權限掉了,算失敗、退回(watch 那邊先看 .python-version 是第一道)。"""
    u, f = _updater(tmp_path, fake=Fake(tmp_path, python_moves=True))
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "python"
    assert any("reset --hard" in c for c in f.cmds) and not any("macsched.py check" in c for c in f.cmds)


def test_owners_agents_are_never_touched(tmp_path):
    """紅線:標籤是使用者本人的 tw.vli.*,一個指令都不跑、不拿鎖。"""
    took = []
    u, f = _updater(tmp_path, prefix="tw.vli.wiki-feeder", lock=lambda: took.append(1))
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "guard" and f.cmds == [] and took == []


def test_app_kind_with_a_git_folder_is_refused(tmp_path):
    u, f = _updater(tmp_path, kind="app")
    (tmp_path / "root" / ".git").mkdir()
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "guard" and f.cmds == []


def test_waits_for_the_running_round_to_let_go_of_the_shared_lock(tmp_path):
    """正在跑的一輪(含叫它的 watch)全程握 deploy.lock 的共享鎖:拿得到獨佔鎖之前什麼都不換。"""
    mod = _mod()
    (tmp_path / "state").mkdir()
    holder = open(tmp_path / "state" / "deploy.lock", "a+")
    fcntl.flock(holder, fcntl.LOCK_SH)
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            holder.close()                     # 那一輪做完了
    u, f = _updater(tmp_path, lock=None)
    u.sleep, u.lock = sleep, u._lock
    res = u.main()
    assert res["result"] == "ok" and len(slept) == 3
    assert f.cmds.index(next(c for c in f.cmds if "merge" in c)) > 0


def test_lock_that_never_frees_up_changes_nothing(tmp_path, monkeypatch):
    mod = _mod()
    monkeypatch.setattr(mod, "LOCK_WAIT", 4)
    (tmp_path / "state").mkdir()
    holder = open(tmp_path / "state" / "deploy.lock", "a+")
    fcntl.flock(holder, fcntl.LOCK_SH)
    u, f = _updater(tmp_path, lock=None)
    u.lock = u._lock
    res = u.main()
    holder.close()
    assert res["result"] == "failed" and res["step"] == "lock" and not any("merge" in c for c in f.cmds)


# -- App 裝的 ----------------------------------------------------------------------------

def _version(app: Path) -> str:
    return plistlib.loads((app / "Contents" / "Info.plist").read_bytes())["CFBundleVersion"]


def test_app_happy_path_renames_keeps_the_old_one_and_follows_setup(tmp_path):
    u, f = _updater(tmp_path, kind="app")
    res = u.main()
    app = tmp_path / "Applications" / "wiki-agent.app"
    assert res["result"] == "ok", res
    assert _version(app) == "bbbbbbb" and _version(tmp_path / "Applications" / ".wiki-agent-previous.app") == "aaaaaaa"
    i = _order(f.cmds, "ditto -x -k", "codesign -v --strict", "spctl --assess", "rsync -a --delete", "sync --frozen",
               "macsched.py install", "macsched.py check")
    assert i == sorted(i)
    rsync = next(c for c in f.cmds if c.startswith("rsync"))
    assert "--exclude /.venv/ --exclude /.app-bundle" in rsync and f"{app}/Contents/Resources/payload/" in rsync
    assert not (tmp_path / "Applications" / ".wiki-agent-update").exists()


@pytest.mark.parametrize("fake, why", [
    (dict(notarized=False), "spctl"),
    (dict(team="OTHER"), "Team ID"),
    (dict(bundle="com.example.other"), "bundle id"),
])
def test_app_that_fails_verification_changes_nothing(tmp_path, fake, why):
    """簽章、公證、Team ID、bundle id 有一樣不對:App 不換、不拿鎖、不 rsync。"""
    took = []
    u, f = _updater(tmp_path, kind="app", fake=Fake(tmp_path, **fake), lock=lambda: took.append(1))
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "verify" and why in res["detail"]
    assert _version(tmp_path / "Applications" / "wiki-agent.app") == "aaaaaaa" and took == []
    assert not any(c.startswith("rsync") for c in f.cmds)


def test_app_folder_that_cannot_be_written_is_a_verify_failure_not_a_failed_rollback(tmp_path, monkeypatch):
    """App 旁邊建不了暫存資料夾(「應用程式」寫不進去):什麼都沒動,信要說「驗新版」這一步失敗、已退回,
    不可說成「也沒能退回」。"""
    mod = _mod()
    u, f = _updater(tmp_path, kind="app")
    real = mod.Path.mkdir

    def deny(self, *a, **k):
        if self.name == ".wiki-agent-update":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)
    monkeypatch.setattr(mod.Path, "mkdir", deny)
    res = u.main()
    assert res["result"] == "failed" and res["step"] == "verify" and f.cmds == []


def test_app_trial_read_failure_puts_the_old_app_back(tmp_path):
    u, f = _updater(tmp_path, kind="app", fake=Fake(tmp_path, fail_on="macsched.py check"))
    res = u.main()
    app = tmp_path / "Applications" / "wiki-agent.app"
    assert res["result"] == "failed" and res["step"] == "check"
    assert _version(app) == "aaaaaaa" and not (tmp_path / "Applications" / ".wiki-agent-previous.app").exists()
    after = f.cmds[_order(f.cmds, "macsched.py check")[0] + 1:]
    assert after[0].startswith("rsync") and f"{app}/Contents/Resources/payload/" in after[0]
    assert "sync --frozen" in after[1] and "macsched.py install" in after[2]


def test_result_and_lock_files(tmp_path, monkeypatch):
    """main() 一定留下結果檔、拿掉鎖檔(下一輪 watch 照它寄信);想不到的錯也一樣。"""
    mod = _mod()
    (tmp_path / "state").mkdir()

    def boom(self):
        raise ValueError("想不到")
    monkeypatch.setattr(mod.Updater, "main", boom)
    rc = mod.main(["--root", str(tmp_path), "--state", str(tmp_path / "state"), "--kind", "git", "--target", "t",
                   "--label", "v", "--prefix", "test.wa"])
    import json
    res = json.loads((tmp_path / "state" / "autoupdate-result.json").read_text(encoding="utf-8"))
    assert rc == 1 and res["result"] == "rollback_failed" and not (tmp_path / "state" / "autoupdate.lock").exists()
