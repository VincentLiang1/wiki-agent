"""朋友版 Windows 自動更新的換版程式:watch 那一輪決定好要換哪一版,用獨立的行程叫這支(spec §7.9)。

watch 用 `.venv\\Scripts\\pythonw.exe -I -S` 叫它:**只用標準函式庫**、不載入 site-packages(Windows 上換不掉被載入的
檔,uv sync 要換的就是那些),也不 import wiki_feeder(換版途中那些檔會被換掉)。訊息不翻譯:結果寫成代碼,
下一輪 watch 照設定的語言寫信、寫 log。

步驟(任何一步失敗就退回,排程一定重新啟用):
  1. 等叫它的 watch 結束(它載入了 numpy)
  2. 停用收件、轉寫＋攝入兩個任務,等正在跑的那一輪自己做完(不砍:攝入做到一半被砍,下一輪會 STOP);watch 不停用:
     這支中途死掉的話,下一輪 watch 看到鎖檔的 pid 不在就把排程重新啟用
  3. 換版:git 裝的 `git merge --ff-only <目標>`(watch 已經 fetch 過);zip 裝的先備份再 `winupdate.py --zip`
  4. uv sync(先等 watch 不在跑;失敗就再等一次重試)
  5. 重新啟用排程(新版多的任務順手建,winsched enable)
  6. 試讀:`collect --list --dirs` 結束碼要是 0(收件匣、知識庫、原件資料夾都讀得到)
  退回:git `reset --hard <舊的 HEAD>`(watch 確認過沒有改過的檔才會叫這支);zip 從備份還原;再 uv sync、重新啟用
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

NO_WINDOW = 0x08000000   # 這支是 pythonw:子行程(git、uv、python)不加這個會每個都閃一個主控台視窗


class StepError(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step, self.detail = step, detail


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return ctypes.GetLastError() == 5
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally:
        k.CloseHandle(h)


def tool_path() -> str:
    """排程底下的 PATH 不一定有 uv、git(Update.bat 也是自己補):照 Install.bat 裝的位置補上。"""
    extra = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "cmd"),
             os.path.join(os.path.expanduser("~"), ".local", "bin"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")]
    return os.pathsep.join([os.environ.get("PATH", ""), *extra])


class Updater:
    def __init__(self, a: argparse.Namespace, run=None, sleep=time.sleep, alive=_alive):
        self.a, self.root, self.state = a, Path(a.root), Path(a.state)
        self.py = str(self.root / ".venv" / "Scripts" / "python.exe")
        self.env = {**os.environ, "PATH": tool_path(), "PYTHONUTF8": "1"}
        self.env.pop("VIRTUAL_ENV", None)
        self._run, self.sleep, self.alive = run or self._subprocess, sleep, alive
        self.uv = shutil.which("uv", path=self.env["PATH"]) or "uv"
        self.git = shutil.which("git", path=self.env["PATH"]) or "git"
        self.backup = self.state / "update-backup"

    def _subprocess(self, cmd: list[str], timeout: float = 3600) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=self.root, env=self.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, creationflags=NO_WINDOW if sys.platform == "win32" else 0)

    def run(self, step: str, cmd: list[str], timeout: float = 3600) -> str:
        try:
            r = self._run(cmd, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise StepError(step, f"{cmd[0]}: {e}") from e
        if r.returncode != 0:
            raise StepError(step, ((r.stdout or "") + (r.stderr or "")).strip()[-2000:] or f"exit {r.returncode}")
        return r.stdout or ""

    def winsched(self, step: str, *args: str) -> str:
        return self.run(step, [self.py, "-X", "utf8", str(self.root / "scripts" / "winsched.py"), *args,
                               "--folder", self.a.folder])

    def watch_running(self) -> bool:
        try:
            r = self._run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                           f"(Get-ScheduledTask -TaskPath '\\{self.a.folder}\\' -TaskName watch "
                           "-ErrorAction SilentlyContinue).State"], timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return (r.stdout or "").strip() == "Running"

    def wait_watch(self, limit: float = 120) -> None:
        waited = 0.0
        while self.watch_running() and waited < limit:
            self.sleep(2)
            waited += 2

    def sync(self, step: str) -> None:
        self.wait_watch()
        try:
            self.run(step, [self.uv, "sync"], timeout=1800)
        except StepError:
            self.sleep(10)
            self.wait_watch()       # watch 剛好在跑、鎖住了 numpy:等它結束再試一次
            self.run(step, [self.uv, "sync"], timeout=1800)

    # -- 換版與退回 --
    def head(self) -> str:
        return self.run("switch", [self.git, "rev-parse", "HEAD"]).strip()

    def switch(self) -> None:
        if self.a.kind == "git":
            self.run("switch", [self.git, "merge", "--ff-only", "-q", self.a.target])
        else:
            wu = str(self.root / "scripts" / "winupdate.py")
            self.run("switch", [self.py, "-X", "utf8", wu, "--backup", str(self.backup)])
            self.run("switch", [self.py, "-X", "utf8", wu, "--zip", self.a.zip])

    def rollback(self, old: str) -> None:
        if self.a.kind == "git":
            self.run("rollback", [self.git, "reset", "--hard", "-q", old])
        elif self.backup.is_dir():
            self.run("rollback", [self.py, "-X", "utf8", str(self.root / "scripts" / "winupdate.py"),
                                  "--restore", str(self.backup)])
        self.sync("rollback")

    def main(self) -> dict:
        res = {"kind": self.a.kind, "target": self.a.target, "label": self.a.label, "notes": self.a.notes,
               "started": time.time()}
        waited = 0.0
        while self.alive(self.a.parent) and waited < 600:   # 叫我的 watch 還握著 numpy
            self.sleep(1)
            waited += 1
        old, switched = "", False
        try:
            self.winsched("disable", "disable", "--keep-watch")
            old = self.head() if self.a.kind == "git" else self.a.current
            res["old"] = old[:7] if self.a.kind == "git" else old
            self.switch()
            switched = True
            self.sync("sync")
            self.winsched("enable", "enable")
            self.run("check", [self.py, "-X", "utf8", "-m", "wiki_feeder", "collect", "--list", "--dirs"], timeout=600)
            res["result"] = "ok"
        except StepError as e:
            res.update(result="failed", step=e.step, detail=e.detail)
            try:
                if switched or e.step == "switch":
                    self.rollback(old)
            except StepError as e2:
                res.update(result="rollback_failed", detail=f"{e.detail}\n\n[rollback] {e2.detail}")
        finally:
            try:
                self.winsched("enable", "enable")             # 排程絕不能停在停用
            except StepError as e3:
                if res.get("result") == "ok":
                    res.update(result="failed", step="enable", detail=e3.detail)
                else:
                    res["detail"] = res.get("detail", "") + f"\n\n[enable] {e3.detail}"
                    res["result"] = "rollback_failed"
        res["finished"] = time.time()
        return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="winautoupdate")
    for k in ("root", "state", "kind", "target", "label", "folder"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--parent", type=int, default=0)
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
