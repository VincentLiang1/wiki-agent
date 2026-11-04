"""三個入口。都實作同一組介面,主流程(collect.py)不知道背後是資料夾還是 git。

介面:
    prepare()     取件前準備;收件匣不存在或連不上 → 丟 InboxUnavailable
    candidates()  回傳「一組一組」的候選檔(同目錄、同主檔名的算一組,一起搬)
    release(c)    c 已驗證複製且已記進處理紀錄,可以清掉來源
    finish()      這一輪結束(FUTURES 在這裡 git rm + commit + push)

FUTURES 的傳輸方式還沒定案,換成別的做法時只要換掉 FuturesInbox。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import gitsync
from .config import FuturesConfig
from .i18n import L, N_
from .mover import is_dataless
from .osplat import download_cmd
from .proc import run_net

log = logging.getLogger(__name__)


class InboxUnavailable(Exception):
    """收件匣不存在、沒權限、或遠端連不上——要大聲失敗。

    offline:查證過不是收件匣壞掉(錯誤字樣看不出來的,例如 GitHub 出事時回的 publickey),收件比照連不上網路處理
    (collect._unavailable)——NET_DOWN 是本機連不上網路(記 net_down.json),REMOTE_SIDE 是 GitHub 那端不穩。
    沒標的由 collect 照錯誤字樣(network_down)判斷。"""

    def __init__(self, msg: str, offline: str | None = None):
        super().__init__(msg)
        self.offline = offline


NET_DOWN = "net_down"
REMOTE_SIDE = "remote_side"


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
        except OSError as e:
            # 2026-10-25:OneDrive 同步的瞬間 listdir 回 EINTR、下一輪就好——跟沒權限一樣連續幾輪才報(§3.4)
            raise InboxUnavailable(L("{inbox} 收件匣暫時讀不到:{e}", inbox=self.name, e=e)) from e

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


# GitHub 出事時 ssh 也回 publickey(2026-11-04:金鑰在、指紋對,6 次 ssh 成功 2 次,githubstatus 晚一小時才公告)
PUBLICKEY = "Permission denied (publickey)"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
# 警示「已查證」那句的兩段(checked_sentence 接起來;repair.PROMPT 第 9 條插入同一句)。
# 這句不隨 githubstatus 讀不讀得到而變:警示以全文去重(§7.2),讀到什麼只寫 log
DENIED_ALL = N_("ssh 連試 {n} 次都被拒")
NO_NOTICE = N_("githubstatus 沒有公告 Git Operations 出事")


def ssh_target(remote: str) -> str | None:
    """remote 是 ssh 就回 ssh -T 要連的目標;不是 ssh 回 None。

    ssh:// 寫法回 `ssh://[使用者@]主機[:埠]`(ssh 認得這種寫法,埠號不會丟);scp 寫法回冒號前那段
    (沒寫使用者的照 ~/.ssh/config 補)。單一字母接冒號是 Windows 的磁碟機,不算。"""
    m = re.match(r"(?:git\+)?(ssh://[^/]+)", remote)
    if m:
        return m.group(1)
    if "://" in remote:
        return None
    m = re.match(r"([^/:]{2,}):", remote)
    return m.group(1) if m else None


def ssh_once(target: str) -> tuple[bool | None, str]:
    """ssh -T 一次:(True 認得金鑰／False 被拒／None 沒有結論, ssh 印的最後一行)。

    GitHub 認得金鑰時結束碼是 1、印「successfully authenticated」,所以看字樣不看結束碼。只有印著 publickey
    才算被拒;逾時、連線被重設、DNS 查不到、host key 不對都不是金鑰被拒的證據(2026-11-04 同一段時間也有逾時)。"""
    r = run_net(["ssh", *SSH_OPTS, "-T", target], 30, text=True)
    out = f"{r.stderr or ''}\n{r.stdout or ''}".strip()
    if "successfully authenticated" in out:
        return True, ""
    last = out.splitlines()[-1].strip() if out else L("ssh 結束碼 {code}", code=r.returncode)
    return (False if PUBLICKEY in out else None), last


def git_ops_status(url: str) -> str | None:
    """githubstatus 上「Git Operations」的狀態(operational、degraded_performance…);讀不到、格式不對回 None。"""
    import urllib.request   # 只有 publickey 查證用得到:不拖慢每次啟動(collect、process 每分鐘各起一次)

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        s = next((c.get("status") for c in data.get("components", []) if c.get("name") == "Git Operations"), None)
    except Exception:  # noqa: BLE001 —— 斷網、改版、格式不對都當讀不到
        return None
    return s if isinstance(s, str) and s else None


def github_side(cfg: FuturesConfig, remote: str | None = None) -> tuple[str | None, str]:
    """publickey 被拒時查證是不是 GitHub 那端不穩:(REMOTE_SIDE／NET_DOWN／None 真的被拒, 查證結果一句話)。
    remote:git 實際在連的那一個。

    連試 ssh:有一次成功 → GitHub 不穩(金鑰沒壞);有一次沒有結論(逾時、斷線)→ 停下、當成連不上網路(NET_DOWN),
    那不是被拒的證據;githubstatus 的 Git Operations 不是 operational 也算 GitHub 不穩。每次都真的被拒、
    githubstatus 也沒公告才算被拒。githubstatus 讀不到不算 GitHub 不穩(金鑰真的被撤時寧可報出來,§3.4)。"""
    target = ssh_target(remote or cfg.remote)
    n = 0
    if target:
        for n in range(1, cfg.ssh_probe_tries + 1):
            got, last = ssh_once(target)
            log.info(L("FUTURES 查證:ssh -T 第 %d 次:%s"), n, last or L("成功"))
            if got is None:
                # 直接標成斷網:ssh 的說法千奇百怪(kex_exchange_identification…),不靠 collect.network_down 的字樣
                return NET_DOWN, L("ssh 沒有連上 GitHub(不是被拒),比照連不上網路:{err}", err=last)
            if got:
                return REMOTE_SIDE, L("ssh 連試 {n} 次有成功,是 GitHub 不穩、不是金鑰的問題", n=n)
    status = git_ops_status(cfg.status_url) if cfg.status_url else None
    log.info("FUTURES:%s", L("githubstatus 讀不到") if status is None
             else L("githubstatus 的 Git Operations 是 {status}", status=status))
    if status and status != "operational":
        return REMOTE_SIDE, L("githubstatus 的 Git Operations 是 {status},是 GitHub 那端在出事", status=status)
    tried = L(DENIED_ALL, n=n) if target else L("沒試 ssh(remote 不是 ssh)")
    return None, checked_sentence(tried)


def checked_sentence(tried: str) -> str:
    """警示裡「已查證」那一句。repair.PROMPT 第 9 條插入 checked_sentence(L(DENIED_ALL, n="N")):兩邊由同一個函式、
    同一個語系組出來,修理的 claude 才找得到那句(寫死在提示裡的話,英文語系的警示永遠對不上)。"""
    return L("已查證:{tried}、{seen}", tried=tried, seen=L(NO_NOTICE))


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

    def _stamp_age(self) -> float | None:
        """距上次連上遠端(stamp 的修改時間)幾秒;沒有 stamp、讀不到回 None。"""
        try:
            return time.time() - self.stamp.stat().st_mtime if self.stamp is not None else None
        except OSError:
            return None

    def _checked_recently(self) -> bool:
        ago = self._stamp_age() if (self.repo / ".git").exists() else None
        return ago is not None and ago < self.cfg.check_interval

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
            if gitsync.rebasing(self.repo):
                # 上一輪 rebase 做到一半被砍:中止、回到原本的 commit,不讓它卡住之後每一輪
                log.warning(L("FUTURES:上一輪停在 rebase 中途,先中止"))
                gitsync.abort(self.repo, self._try)
            self._push_pending()
            remote_head = self._remote_head()
            if remote_head != self._rev(f"origin/{self.cfg.branch}") or remote_head != self._rev("HEAD"):
                # 不用 pull:它照 FETCH_HEAD 合併,同時有別的 fetch 在跑就失敗(見 gitsync)
                self._git("fetch", "origin", self.cfg.branch)
                self._git("merge", "--ff-only", "-q", f"origin/{self.cfg.branch}")
            self._head = self._rev("HEAD")
        except GitError as e:
            msg, offline = L("FUTURES 取件準備失敗:{e}", e=e), None
            if PUBLICKEY in str(e):
                offline, why = self._github_side()
                msg += "\n" + why
            raise InboxUnavailable(msg, offline=offline) from e
        if self.stamp is not None:
            self.stamp.parent.mkdir(parents=True, exist_ok=True)
            self.stamp.touch()

    def _github_side(self) -> tuple[str | None, str]:
        """publickey 的查證(§3.4)。上次連上遠端(stamp)不到 github_hold 秒:金鑰剛剛還能用,先當成 GitHub 不穩、
        不連試——2026-11-04 事故中 ls-remote 連 9 輪被拒、前後幾分鐘都有連上的輪,只看當輪的連試總會碰上一輪全被拒。
        查證本身出錯(找不到 ssh 之類)當成沒查到、照舊警示,不讓例外蓋掉原本的錯誤、跳過連續 3 輪的門檻。"""
        ago = self._stamp_age()
        if ago is not None and ago < self.cfg.github_hold:
            return REMOTE_SIDE, L("上次連上 GitHub 是 {m} 分鐘前,金鑰剛剛還能用:先當成 GitHub 不穩", m=int(ago // 60))
        try:
            remote = self._origin_url() or self.cfg.remote
            return github_side(self.cfg, remote)
        except Exception as e:  # noqa: BLE001 —— 查證本身的錯
            return None, L("查證時出錯,沒能查證:{e}", e=e)

    def _origin_url(self) -> str:
        """git 實際在連的 origin(套過 insteadOf);讀不到回空字串。clone 之後設定裡的 remote 改過的話兩者不同,
        查證要連 git 真正在連的那一個:否則新的連得上、舊的一直被拒,永遠被當成 GitHub 不穩、不警示。"""
        if not (self.repo / ".git").exists():
            return ""
        r = self._git("remote", "get-url", "origin", check=False, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""

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

    def _try(self, *args: str) -> subprocess.CompletedProcess:
        return self._git(*args, check=False)

    def _push_with_retry(self) -> bool:
        """被拒就 fetch + rebase origin/<branch> 再推(gitsync);暫時性失敗等一下重試,真正的衝突放棄這輪。"""
        for i in range(self.cfg.push_retries):
            if self._git("push", "origin", f"HEAD:{self.cfg.branch}", check=False).returncode == 0:
                return True
            log.info(L("FUTURES:推送被拒(第 %d 次),跟上遠端後重試"), i + 1)
            state, err = gitsync.rebase_onto_remote(self.repo, self.cfg.branch, self._try)
            if state == gitsync.CONFLICT:
                log.warning(L("FUTURES:rebase 失敗:%s"), err)
                return False
            if state == gitsync.TRANSIENT and i + 1 < self.cfg.push_retries:
                log.info(L("FUTURES:跟上遠端失敗(暫時性),稍候重試:%s"), err)
                gitsync.wait(i)
        return False
