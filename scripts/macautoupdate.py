"""朋友版 Mac 自動更新的換版程式:watch 那一輪決定好要換哪一版,用獨立的行程叫這支(spec §7.9)。

watch 用 `~/wiki-agent/.venv/bin/python` 的本體(uv 管的 python,不在 App 裡、不在 .venv 裡)帶 `-I -S -B` 叫它:
**只用標準函式庫**、不 import wiki_feeder(換版途中那些檔會被換掉)、不寫 .pyc。訊息不翻譯:結果寫成代碼,
下一輪 watch 照設定的語言寫信、寫 log。

開法是 `start_new_session=True`(setsid):2026-10-23 實測,launchd 的 job 結束、甚至被 bootout 時,只砍它自己那個
行程群組,另開 session 的子行程照跑(ppid 變 1)。所以不必另外開一次性的 launchd job,也不必改 watch 的 plist。

步驟(任何一步失敗就退回;agent 不停用,排程從頭到尾都在):
  1. App 裝的:先驗新版——`ditto -x -k` 解到 App 旁邊的暫存資料夾,`codesign -v --strict`、`spctl --assess`
     要是公證過的、Team ID 與 bundle id 跟現在這份相同、CFBundleVersion 是目標版本。驗不過什麼都不動
  2. 拿 `deploy.lock` 的獨佔鎖:每一輪全程握它的共享鎖,所以會等正在跑的那一輪(含叫它的 watch)做完、不砍;
     拿著鎖的期間新的一輪直接結束(`collect --list` 不經這把鎖,試讀照樣跑得了)
  3. 換版:git 裝的 `git merge --ff-only <目標>`(watch 已經 fetch 過);App 裝的用 rename 換掉 App,舊的改名留著當退路,
     再照 setup.zsh 不問問題的那一段 rsync 程式到 ~/wiki-agent
  4. `uv sync --frozen`;git 裝的再看 python 本體有沒有換(換了完整磁碟取用權限就掉了,算失敗)
  5. `macsched.py install`(新版多的 agent 順手裝)→ `macsched.py check`(經 launchd 試讀,權限只有在那底下才看得出來)
  退回:git `reset --hard <舊的 HEAD>`(watch 確認過沒有改過的檔才會叫這支);App 把舊的改名回來、從它 rsync;
  再 uv sync、macsched install。最後才放鎖。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "wiki-agent.app"
BUNDLE_ID = "io.github.wiki-agent"       # make_mac_app.BUNDLE_ID:讀取權限記在它上面
NOTARIZED = "source=Notarized Developer ID"
LOCK_WAIT = 2 * 3600                       # 正在跑的一輪(長錄音的攝入)最多等這麼久;等不到就不換,下一版再說
OWNER_PREFIX = "tw.vli."                   # 使用者本人的 agent:絕不動


class StepError(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step, self.detail = step, detail


def tool_path(home: str) -> str:
    """launchd 底下的 PATH 照 macsched.env_path 已經有這些;終端機手動跑時補上(uv 常裝在 ~/.local/bin)。"""
    return os.pathsep.join([os.environ.get("PATH", ""), f"{home}/.local/bin", "/opt/homebrew/bin", "/usr/local/bin",
                            "/usr/bin", "/bin", "/usr/sbin", "/sbin"])


def app_info(app: Path, run) -> dict:
    """codesign 看到的 Identifier、TeamIdentifier,與 Info.plist 的 CFBundleVersion。"""
    r = run(["codesign", "-dvvv", str(app)], timeout=120)
    text = (r.stdout or "") + (r.stderr or "")
    info = {k: v.strip() for k, _, v in (ln.partition("=") for ln in text.splitlines()) if k in ("Identifier",
                                                                                                "TeamIdentifier")}
    try:
        info["version"] = str(plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleVersion", ""))
    except (OSError, ValueError):
        info["version"] = ""
    return info


def app_pyver(app: Path) -> str:
    """新版 App 裡那顆 python 的 X.Y(啟動器與 .pth 找的是 ~/wiki-agent/.venv/lib/python<X.Y>/site-packages)。"""
    for p in sorted((app / "Contents" / "Resources" / "python" / "bin").glob("python3.*")):
        m = re.fullmatch(r"python(3\.\d+)", p.name)
        if m:
            return m.group(1)
    return ""


class Updater:
    def __init__(self, a: argparse.Namespace, run=None, sleep=time.sleep, lock=None):
        self.a, self.root, self.state = a, Path(a.root), Path(a.state)
        self.home = os.environ.get("HOME") or str(Path.home())
        self.env = {**os.environ, "PATH": tool_path(self.home)}
        self.env.pop("VIRTUAL_ENV", None)
        self.env.pop("PYTHONHOME", None)
        self._run, self.sleep = run or self._subprocess, sleep
        self.uv = shutil.which("uv", path=self.env["PATH"]) or "uv"
        self.git = shutil.which("git", path=self.env["PATH"]) or "git"
        self.venv_py = str(self.root / ".venv" / "bin" / "python")
        self.lock = lock or self._lock
        self.app = None
        if a.kind == "app":
            try:
                self.app = Path((self.root / ".app-bundle").read_text(encoding="utf-8").strip())
            except OSError:
                self.app = None
        if self.app:
            self.stage = self.app.parent / ".wiki-agent-update"         # 跟 App 同一個資料夾:rename 不跨磁碟
            self.backup = self.app.parent / ".wiki-agent-previous.app"  # 舊的留著當退路(點開頭:Finder 不顯示)

    def _subprocess(self, cmd: list[str], timeout: float = 3600) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=self.root, env=self.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)

    def run(self, step: str, cmd: list[str], timeout: float = 3600) -> str:
        try:
            r = self._run(cmd, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise StepError(step, f"{cmd[0]}: {e}") from e
        if r.returncode != 0:
            raise StepError(step, ((r.stdout or "") + (r.stderr or "")).strip()[-2000:] or f"exit {r.returncode}")
        return r.stdout or ""

    def macsched(self, step: str, *args: str, timeout: float = 900) -> str:
        return self.run(step, [self.venv_py, str(self.root / "scripts" / "macsched.py"), *args,
                               "--prefix", self.a.prefix], timeout=timeout)

    def _lock(self):
        """deploy.lock 的獨佔鎖(macsched.hold_exclusive 的標準函式庫版):等正在跑的一輪做完。"""
        path = self.state / "deploy.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a+")
        waited = 0.0
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except BlockingIOError:
                if waited >= LOCK_WAIT:
                    f.close()
                    raise StepError("lock", f"{LOCK_WAIT // 60} 分鐘都等不到正在跑的那一輪做完")
                self.sleep(2)
                waited += 2

    # -- 安全檢查:只動朋友的安裝 --
    def guard(self) -> None:
        if self.a.prefix.startswith(OWNER_PREFIX):
            raise StepError("guard", f"標籤 {self.a.prefix} 是使用者本人的,不動")
        if self.a.kind == "git":
            if not (self.root / ".git").exists():
                raise StepError("guard", "沒有 .git")
        elif self.a.kind == "app":
            if (self.root / ".git").exists() or not self.app or self.app.suffix != ".app" or not self.app.is_dir():
                raise StepError("guard", f"不是 App 裝的({self.app})")
        else:
            raise StepError("guard", f"不認得的安裝種類 {self.a.kind}")

    # -- App:驗新版 --
    def verify(self) -> Path:
        shutil.rmtree(self.stage, ignore_errors=True)
        try:
            self.stage.mkdir(parents=True)
        except OSError as e:                     # 「應用程式」寫不進去:什麼都還沒動
            raise StepError("verify", f"{self.stage}:{e}") from e
        self.run("verify", ["ditto", "-x", "-k", self.a.zip, str(self.stage)], timeout=600)
        new = self.stage / APP_NAME
        if not new.is_dir():
            raise StepError("verify", f"zip 裡沒有 {APP_NAME}")
        self.run("verify", ["codesign", "-v", "--strict", str(new)], timeout=600)
        r = self._run(["spctl", "--assess", "-vv", "-t", "exec", str(new)], timeout=300)
        if r.returncode != 0 or NOTARIZED not in (r.stdout or "") + (r.stderr or ""):
            raise StepError("verify", "spctl:" + ((r.stdout or "") + (r.stderr or "")).strip()[-500:])
        mine, theirs = app_info(self.app, self._run), app_info(new, self._run)
        if not theirs.get("TeamIdentifier") or theirs.get("TeamIdentifier") != mine.get("TeamIdentifier"):
            raise StepError("verify", f"Team ID 不同:{theirs.get('TeamIdentifier')} ≠ {mine.get('TeamIdentifier')}")
        if theirs.get("Identifier") != BUNDLE_ID or mine.get("Identifier") != BUNDLE_ID:
            raise StepError("verify", f"bundle id 不同:{theirs.get('Identifier')} ≠ {mine.get('Identifier')}")
        if not self.a.target.endswith(theirs.get("version") or "?"):
            raise StepError("verify", f"App 的版本 {theirs.get('version')} 不是 {self.a.target}")
        return new

    # -- 換版與退回 --
    def rsync(self, step: str, app: Path) -> None:
        # 與 setup.zsh 同一組排除;⚠️ 不加 -X/-E(隔離標記不帶過去,Remove-Schedule.command 才雙擊得開)
        self.run(step, ["rsync", "-a", "--delete", "--exclude", "/.venv/", "--exclude", "/.app-bundle",
                        "--exclude", "__pycache__/", f"{app}/Contents/Resources/payload/", f"{self.root}/"],
                 timeout=600)

    def sync(self, step: str) -> None:
        self.run(step, [self.uv, "sync", "--frozen", "-q"], timeout=1800)
        if self.a.kind == "app":
            pyver = app_pyver(self.app)
            if not pyver or not (self.root / ".venv" / "lib" / f"python{pyver}" / "site-packages").is_dir():
                raise StepError(step, f"環境的 Python 版本跟 App 對不上(App 是 {pyver or '?'})")

    def switch(self, new: Path | None) -> None:
        if self.a.kind == "git":
            self.run("switch", [self.git, "merge", "--ff-only", "-q", self.a.target])
            return
        shutil.rmtree(self.backup, ignore_errors=True)   # 上一次更新留下的退路
        try:
            os.rename(self.app, self.backup)
        except OSError as e:
            raise StepError("switch", f"改名 {self.app}:{e}") from e
        try:
            os.rename(new, self.app)
        except OSError as e:
            os.rename(self.backup, self.app)
            raise StepError("switch", f"換上新版 App:{e}") from e
        self.swapped = True
        self.rsync("switch", self.app)

    def rollback(self, old: str) -> None:
        if self.a.kind == "git":
            self.run("rollback", [self.git, "reset", "--hard", "-q", old])
        elif getattr(self, "swapped", False):
            bad = self.stage / "failed.app"
            shutil.rmtree(bad, ignore_errors=True)
            try:
                os.rename(self.app, bad)
                os.rename(self.backup, self.app)
            except OSError as e:
                raise StepError("rollback", f"把舊的 App 換回來:{e}") from e
            self.rsync("rollback", self.app)
        self.sync("rollback")
        self.macsched("rollback", "install")

    def python_now(self) -> str:
        return os.path.realpath(self.venv_py)

    def main(self) -> dict:
        res = {"kind": self.a.kind, "target": self.a.target, "label": self.a.label, "notes": self.a.notes,
               "started": time.time(), "old": self.a.current}
        held = None
        old, switched = "", False
        try:
            self.guard()
            new = self.verify() if self.a.kind == "app" else None
            held = self.lock()
            old = self.run("switch", [self.git, "rev-parse", "HEAD"]).strip() if self.a.kind == "git" \
                else self.a.current
            res["old"] = old[:7]
            before = self.python_now()
            switched = True   # git merge 失敗也可能動了一半:從這裡起失敗一律退回
            self.switch(new)
            self.sync("sync")
            if self.a.kind == "git" and self.python_now() != before:
                raise StepError("python", f"{before} → {self.python_now()}")
            self.macsched("enable", "install")
            self.macsched("check", "check", timeout=900)
            res["result"] = "ok"
        except StepError as e:
            res.update(result="failed", step=e.step, detail=e.detail)
            if switched:
                try:
                    self.rollback(old)
                except StepError as e2:
                    res.update(result="rollback_failed", detail=f"{e.detail}\n\n[rollback] {e2.detail}")
        finally:
            if held is not None:
                held.close()                       # 放鎖:下一輪就用新(或退回的)程式
            if self.app:
                shutil.rmtree(self.stage, ignore_errors=True)
        res["finished"] = time.time()
        return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="macautoupdate")
    for k in ("root", "state", "kind", "target", "label", "prefix"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--zip", default="")
    ap.add_argument("--current", default="")
    a = ap.parse_args(argv)
    state = Path(a.state)
    lock = state / "autoupdate.lock"
    info = {"pid": os.getpid(), "started": time.time(), "target": a.target, "label": a.label}
    try:
        info.update({k: v for k, v in json.loads(lock.read_text(encoding="utf-8")).items() if k == "old"})
    except (OSError, ValueError):
        pass
    lock.write_text(json.dumps(info), encoding="utf-8")
    try:
        res = Updater(a).main()
    except Exception as e:  # noqa: BLE001 —— 想不到的錯也要留下結果,下一輪 watch 才寄得出信
        res = {"result": "rollback_failed", "step": "internal", "detail": repr(e), "target": a.target, "label": a.label}
    tmp = state / "autoupdate-result.json.tmp"
    tmp.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, state / "autoupdate-result.json")
    lock.unlink(missing_ok=True)
    return 0 if res.get("result") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
