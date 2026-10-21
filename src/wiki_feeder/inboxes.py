"""三個入口。都實作同一組介面,主流程(collect.py)不知道背後是資料夾還是 git。

介面:
    prepare()     取件前準備;收件匣不存在或連不上 → 丟 InboxUnavailable
    candidates()  回傳「一組一組」的候選檔(同目錄、同主檔名的算一組,一起搬)
    release(c)    c 已驗證複製且已記進處理紀錄,可以清掉來源
    finish()      這一輪結束(FUTURES 在這裡 git rm + commit + push)

FUTURES 的傳輸方式還沒定案,換成別的做法時只要換掉 FuturesInbox。
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import FuturesConfig
from .i18n import L
from .mover import is_dataless
from .osplat import download_cmd
from .proc import run_net

log = logging.getLogger(__name__)


class InboxUnavailable(Exception):
    """收件匣不存在、沒權限、或遠端連不上——要大聲失敗。"""


@dataclass(frozen=True)
class Candidate:
    path: Path   # 實際位置
    rel: str     # 相對收件匣根目錄的路徑(寫進 sidecar 的「原路徑」)


def _ignored(name: str) -> bool:
    # 點開頭:.DS_Store、OneDrive 的 .849C… 標記檔、iCloud 的 .x.icloud 佔位檔、我們自己的 .partial
    # Icon\r:Finder 自訂圖示;~$*、*.tmp:Office 暫存檔
    return name.startswith(".") or name == "Icon\r" or name.startswith("~$") or name.endswith(".tmp")


def _group(cands: list[Candidate]) -> list[list[Candidate]]:
    groups: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for c in cands:
        groups[(str(Path(c.rel).parent), Path(c.rel).stem)].append(c)
    return [sorted(g, key=lambda c: c.rel) for _, g in sorted(groups.items())]


class FolderInbox:
    """iCloud 與 OneDrive:一般資料夾,取到就刪。"""

    needs_stability = True

    def __init__(self, name: str, root: Path, trigger_download: bool = False):
        self.name = name
        self.root = root
        self.trigger_download = trigger_download

    def meta(self) -> dict:
        return {}

    def prepare(self) -> None:
        if not self.root.is_dir():
            raise InboxUnavailable(L("{inbox} 收件匣不存在:{path}", inbox=self.name, path=self.root))
        try:
            os.listdir(self.root)
        except PermissionError as e:
            raise InboxUnavailable(
                L("{inbox} 收件匣沒有讀取權限(經 ssh/launchd 執行時查「完整磁碟取用權限」):{e}", inbox=self.name, e=e)
            ) from e

    def candidates(self) -> list[list[Candidate]]:
        found: list[Candidate] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if fn.startswith(".") and fn.endswith(".icloud"):
                    # 舊式 iCloud 佔位檔 .名稱.icloud:請它下載,這輪不取
                    self._request_download(p.with_name(fn[1:-len(".icloud")]))
                    continue
                if _ignored(fn) or not p.is_file():
                    continue
                # 一律 `/`:sidecar 的「原路徑」是資料格式,Windows 攝入的檔也會同步回 Mac(spec 02)
                found.append(Candidate(p, p.relative_to(self.root).as_posix()))
        groups = []
        for g in _group(found):
            try:
                pending = [c for c in g if is_dataless(c.path)]
            except FileNotFoundError:
                continue  # 列檔之後才被刪掉(例如使用者在 iPhone 上刪了),這輪略過

            if pending:
                for c in pending:
                    log.info(L("%s:%s 是雲端佔位檔、內容還沒下載,這輪先不取"), self.name, c.rel)
                    self._request_download(c.path)
                continue
            groups.append(g)
        return groups

    def _request_download(self, path: Path) -> None:
        if not self.trigger_download:
            return
        try:
            subprocess.run(download_cmd(str(path)), capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning(L("%s:要求下載 %s 失敗:%s"), self.name, path, e)

    def release(self, c: Candidate) -> None:
        c.path.unlink()

    def finish(self) -> None:
        pass


class GitError(Exception):
    pass


class FuturesInbox:
    """公司端經 GitHub 投遞:FUTURES repo 的 PROCESS/。

    只做 PROCESS/ 的稀疏取出;只 git rm 已驗證複製的檔;絕不 --force;
    不修改 PROCESS/ 以外的任何路徑。
    """

    name = "FUTURES"
    needs_stability = False  # 已 commit 的內容不會寫到一半

    def __init__(self, cfg: FuturesConfig, stamp: Path | None = None):
        self.cfg = cfg
        self.repo = cfg.repo_dir
        self.stamp = stamp            # 上次遠端檢查的時間(檔案修改時間)
        self._released: list[str] = []
        self._head = ""

    def _checked_recently(self) -> bool:
        if self.stamp is None or not self.stamp.exists() or not (self.repo / ".git").exists():
            return False
        return time.time() - self.stamp.stat().st_mtime < self.cfg.check_interval

    # -- git ----------------------------------------------------------------
    def _git(self, *args: str, cwd: Path | None = None, check: bool = True,
             timeout: float | None = None) -> subprocess.CompletedProcess:
        # 連不上的先由 ssh 自己斷(ConnectTimeout、連上後沒回應 60 秒),run_net 的逾時是最後一道
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes "
                   "-o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=4")
        cmd = ["git", "-c", f"user.name={self.cfg.git_user}", "-c", f"user.email={self.cfg.git_email}", *args]
        r = run_net(cmd, timeout or self.cfg.net_timeout, cwd=cwd or self.repo, env=env, text=True)
        if check and r.returncode != 0:
            raise GitError(L("git {args} 失敗:{out}", args=" ".join(args), out=r.stderr.strip() or r.stdout.strip()))
        return r

    def _rev(self, ref: str) -> str:
        return self._git("rev-parse", ref).stdout.strip()

    def meta(self) -> dict:
        return {"commit": self._head}

    # -- 介面 -----------------------------------------------------------------
    def prepare(self) -> None:
        self._released = []
        if self._checked_recently():
            # 不連 GitHub;本機 PROCESS/ 裡上一輪留下的檔照常列出、照常處理
            self._head = self._rev("HEAD")
            return
        try:
            if not (self.repo / ".git").exists():
                self._clone()
            self._push_pending()
            remote_head = self._remote_head()
            if remote_head != self._rev(f"origin/{self.cfg.branch}") or remote_head != self._rev("HEAD"):
                self._git("pull", "--ff-only", "origin", self.cfg.branch)
            self._head = self._rev("HEAD")
        except GitError as e:
            raise InboxUnavailable(L("FUTURES 取件準備失敗:{e}", e=e)) from e
        if self.stamp is not None:
            self.stamp.parent.mkdir(parents=True, exist_ok=True)
            self.stamp.touch()

    def _clone(self) -> None:
        self.repo.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--no-checkout", "--branch", self.cfg.branch]
        if self.cfg.partial_clone:
            args.append("--filter=blob:none")
        self._git(*args, self.cfg.remote, str(self.repo), cwd=self.repo.parent, timeout=self.cfg.net_timeout * 6)
        # --no-cone:cone 模式一定會連根目錄的檔一起取出,FUTURES 根目錄是公司檔
        self._git("sparse-checkout", "set", "--no-cone", f"/{self.cfg.process_dir}/")
        self._git("checkout", self.cfg.branch)

    def _remote_head(self) -> str:
        out = self._git("ls-remote", "origin", f"refs/heads/{self.cfg.branch}").stdout.split()
        if not out:
            raise GitError(L("遠端沒有 {branch} 分支", branch=self.cfg.branch))
        return out[0]

    def _push_pending(self) -> None:
        """上一輪推送失敗留下的本機 commit:先試著推上去。

        還是推不上去就丟掉本機那個 commit、回到遠端狀態——那些檔都已複製並記進
        處理紀錄,回到遠端後它們會重新出現在 PROCESS/,下一步以 SHA-256 判為重複、
        只清來源。不會遺失,也絕不 --force。
        """
        ahead = int(self._git("rev-list", "--count", f"origin/{self.cfg.branch}..HEAD").stdout.strip())
        if ahead == 0:
            return
        log.warning(L("FUTURES:有 %d 個上一輪沒推上去的 commit,先重推"), ahead)
        if not self._push_with_retry():
            log.warning(L("FUTURES:重推仍失敗,本機回到遠端狀態,已取走的檔下一輪以重複處理"))
            self._git("fetch", "origin", self.cfg.branch)
            self._git("reset", "--hard", f"origin/{self.cfg.branch}")

    def candidates(self) -> list[list[Candidate]]:
        prefix = self.cfg.process_dir + "/"
        keep = {prefix + k for k in self.cfg.keep}
        out = self._git("-c", "core.quotePath=off", "ls-files", "-z", "--", self.cfg.process_dir).stdout
        found = []
        for rel in filter(None, out.split("\0")):
            if rel in keep or _ignored(Path(rel).name):
                continue
            p = self.repo / rel
            if p.is_file():
                found.append(Candidate(p, rel))
        return _group(found)

    def release(self, c: Candidate) -> None:
        self._released.append(c.rel)

    def finish(self) -> None:
        if not self._released:
            return
        n = len(self._released)
        self._git("rm", "-q", "--", *self._released)
        self._git("commit", "-q", "-m", f"process: 取走 {n} 個檔")
        self._released = []
        if not self._push_with_retry():
            raise InboxUnavailable(L("FUTURES 推送失敗,已取走的檔留待下一輪重推(已複製,不會重複攝入)"))

    def _push_with_retry(self) -> bool:
        for i in range(self.cfg.push_retries):
            if self._git("push", "origin", f"HEAD:{self.cfg.branch}", check=False).returncode == 0:
                return True
            log.info(L("FUTURES:推送被拒(第 %d 次),pull --rebase 後重試"), i + 1)
            r = self._git("pull", "--rebase", "origin", self.cfg.branch, check=False)
            if r.returncode != 0:
                self._git("rebase", "--abort", check=False)
                log.warning(L("FUTURES:rebase 失敗:%s"), r.stderr.strip())
                return False
        return False
