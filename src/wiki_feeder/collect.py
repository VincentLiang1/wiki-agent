"""收件主流程:各入口 → 驗證 → Raw_Sources/_待處理/。

每一筆的順序固定,不可調換(調換就可能「來源刪了、副本卻沒有」):
    1. 算來源 SHA-256;處理紀錄已有 → 跳到 5(只清來源)
    2. 複製到暫存名、驗證 SHA-256、改成正式名
    3. 寫程式補的 sidecar(<檔名>.feeder.json)
    4. 寫處理紀錄並 commit
    5. 清來源
任何一步失敗:保留來源、記錄、留到下一輪。寧可重複,不可遺失。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config
from .i18n import L
from .inboxes import Candidate, FolderInbox, FuturesInbox, InboxUnavailable
from .ledger import Ledger
from .mover import copy_verified, pick_names, sha256_of
from .osplat import WINDOWS, try_lock, unlock
from .osplat import uptime as _uptime

log = logging.getLogger(__name__)

SIDECAR_EXT = ".feeder.json"


@dataclass
class Report:
    moved: list[str] = field(default_factory=list)       # 落到 _待處理/ 的正式路徑
    duplicates: list[str] = field(default_factory=list)  # 內容已處理過、只清了來源
    failed: list[str] = field(default_factory=list)      # 這輪失敗、來源保留
    skipped_unstable: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    new_alerts: list[str] = field(default_factory=list)   # 24 小時內第一次出現的,要發到當日摘要
    locked: bool = False

    @property
    def ok(self) -> bool:
        return not self.alerts and not self.failed


def build_inboxes(cfg: Config) -> list:
    inboxes = []
    if cfg.icloud_inbox is not None:
        inboxes.append(FolderInbox("iCloud", cfg.icloud_inbox, trigger_download=cfg.trigger_icloud_download))
    if cfg.onedrive_inbox is not None:
        inboxes.append(FolderInbox("OneDrive", cfg.onedrive_inbox))
    if cfg.futures is not None:
        inboxes.append(FuturesInbox(cfg.futures, cfg.state_dir / "futures_last_check"))
    return inboxes


@contextmanager
def run_lock(path: Path):
    """launchd 兩次執行可能重疊:拿不到鎖就回傳 False,呼叫端直接結束。
    flock 在行程結束時由系統自動釋放,當掉也不會留下死鎖。
    開檔用 a+ 不用 w:Windows 上別人鎖著的檔被 w 截斷會失敗(Mac 的 flock 不在乎)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        if not try_lock(f):
            yield False
            return
        run = run_file(path)
        run.write_text(json.dumps({"pid": os.getpid(), "started": time.time(), "up": uptime()}), encoding="utf-8")
        try:
            yield True
        finally:
            run.unlink(missing_ok=True)
            unlock(f)


def run_file(lock: Path) -> Path:
    """握鎖期間的行程編號與開始時間;修改時間是最後一次心跳。看門狗靠它找出卡住的一輪(flock 不記 pid)。"""
    return lock.with_name(lock.name + ".run")


def uptime() -> float:
    """不含睡眠的秒數(macOS 的 CLOCK_UPTIME_RAW,每個行程讀到的都一樣)。看門狗用它算多久沒心跳:
    闔上螢幕睡一兩個小時(pmset 紀錄有 96、174 分鐘)時那一輪只是暫停,用牆上時間算會被當成卡住、unstick 砍掉。"""
    return _uptime()


def heartbeat(lock: Path) -> None:
    """每處理一筆就跳一下:一輪可能連處理好幾筆、每筆都可以跑很久,只看開始時間會把正常的長輪當成卡住。"""
    run = run_file(lock)
    try:
        info = json.loads(run.read_text(encoding="utf-8"))
        info["up"] = uptime()
        run.write_text(json.dumps(info), encoding="utf-8")
    except (OSError, ValueError):
        pass


@contextmanager
def deploy_guard(path: Path):
    """整個執行期間握共享鎖;deploy 拿獨佔鎖。收件、轉寫、攝入的鎖在發摘要與警示之前就放了,
    deploy 只等那三把的話,會在寄摘要信半途把行程砍掉——那輪的攝入從此不出現在摘要裡,
    警示也已記成發過、24 小時內不再報(2026-10-05 審查實測)。
    Windows 沒有共享鎖、也不 deploy(朋友更新是 git pull):一律放行。"""
    if WINDOWS:
        yield True
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        if not try_lock(f, shared=True):
            yield False
            return
        try:
            yield True
        finally:
            unlock(f)


def collect(cfg: Config, inboxes: list | None = None) -> Report:
    report = Report()
    with run_lock(cfg.lock_path) as got:
        if not got:
            log.info(L("另一個 collect 正在執行,這次直接結束"))
            report.locked = True
            return report
        inboxes = build_inboxes(cfg) if inboxes is None else inboxes
        with Ledger(cfg.ledger_path) as ledger:
            if cfg.raw_roots:
                hashed, gone = ledger.refresh_raw_index(cfg.raw_roots, cfg.raw_skip_dirs)
                if hashed or gone:
                    log.info(L("既有原件索引:新算 %d 個、移除 %d 筆"), hashed, gone)
            for inbox in inboxes:
                heartbeat(cfg.lock_path)
                _collect_one(cfg, inbox, ledger, report)
    report.new_alerts = [m for m in report.alerts if _alert(cfg, m)]
    return report


def _collect_one(cfg: Config, inbox, ledger: Ledger, report: Report) -> None:
    """一個入口出任何事都只記警示、不中斷其他入口(例如列檔途中使用者從 iPhone 刪了檔)。"""
    try:
        try:
            inbox.prepare()
        except InboxUnavailable as e:
            _unavailable(cfg, inbox, e, report)
            return
        _streak(cfg, inbox.name, reset=True)
        _mark_offline(cfg, inbox.name, False)
        groups = inbox.candidates()
        if inbox.needs_stability:
            groups = _stable_groups(groups, cfg.stable_wait, report)
        for group in groups:
            _take_group(cfg, inbox, group, ledger, report)
    except Exception as e:  # noqa: BLE001
        _inbox_alert(inbox, e, report)
    try:
        inbox.finish()
    except Exception as e:  # noqa: BLE001
        _inbox_alert(inbox, e, report)


def _streak(cfg: Config, name: str, reset: bool = False) -> int:
    """某收件匣連續讀不到幾輪(存在 state dir,跨輪累計)。"""
    path = cfg.state_dir / "inbox_streak.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    n = 0 if reset else data.get(name, 0) + 1
    if data.get(name, 0) != n:
        data[name] = n
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return n


def _mark_offline(cfg: Config, name: str, down: bool) -> None:
    """記下這個收件匣最近一次讀不到是不是因為連不上網路(`inbox_offline.json`,看門狗看這個不叫修理、不寄信)。

    2026-10-20 帶筆電到公司:FUTURES 走 ssh 連不上 GitHub,網路閃一下通的那一刻看門狗就寄了 🛑。
    連不上網路不是壞掉,警示照樣進當日摘要(一天一則),只是不交給修理。"""
    path = cfg.state_dir / "inbox_offline.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = []
    names = [n for n in data if n != name] if isinstance(data, list) else []
    if down:
        names.append(name)
        mark_net_down(cfg)
    if names != data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(names), ensure_ascii=False), encoding="utf-8")


def net_down_path(cfg: Config) -> Path:
    return cfg.state_dir / "net_down.json"


def mark_net_down(cfg: Config) -> None:
    """記下最近一次看到連不上網路的牆上時間(`net_down.json`)。

    看門狗的 iCloud 探針看這個:寫入之後斷過網,沒傳上去是網路的事、不是 iCloud 卡住(§7.7)。
    2026-10-22 拔掉電源帶出門,探針在斷網前一刻寫入,接上手機熱點 4 分鐘時看門狗查到「12 分鐘沒傳上去」就寄了 🛑。"""
    path = net_down_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time()}), encoding="utf-8")


def last_net_down(cfg: Config) -> float:
    """最近一次看到連不上網路的牆上時間;沒有紀錄回 0。"""
    try:
        at = json.loads(net_down_path(cfg).read_text(encoding="utf-8")).get("at")
    except (OSError, ValueError, AttributeError):
        return 0.0
    return float(at) if isinstance(at, (int, float)) else 0.0


def _unavailable(cfg: Config, inbox, e: InboxUnavailable, report: Report) -> None:
    """收件匣讀不到:連續 N 輪才發警示。

    實測(2026-10-04):launchd 每分鐘一輪,OneDrive 有一輪回 Operation not permitted、前後都正常
    ——雲端同步的瞬間狀態。直接發警示會叫人去查一個沒壞的權限。真的壞掉會一直讀不到,幾分鐘內照樣報。
    """
    n = _streak(cfg, inbox.name)
    _mark_offline(cfg, inbox.name, network_down(str(e)))
    if n >= cfg.unavailable_alert_after:
        _inbox_alert(inbox, e, report)
    else:
        log.warning(L("%s(連續第 %d 輪,滿 %d 輪才發警示)"), e, n, cfg.unavailable_alert_after)


def _inbox_alert(inbox, e: Exception, report: Report) -> None:
    msg = str(e) if isinstance(e, InboxUnavailable) else L("{inbox} 發生預期外的錯誤:{kind}: {e}", inbox=inbox.name,
                                                         kind=type(e).__name__, e=e)
    log.error("%s", msg, exc_info=not isinstance(e, InboxUnavailable))
    report.alerts.append(msg)


def _snapshot(c: Candidate) -> tuple[int, int] | None:
    try:
        st = c.path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _stable_groups(groups: list[list[Candidate]], wait: float, report: Report) -> list[list[Candidate]]:
    """大小與修改時間間隔 wait 秒連續兩次相同才取;整組任一檔還在變就整組留到下一輪。"""
    if not groups:
        return groups
    before = {c: _snapshot(c) for g in groups for c in g}
    if wait > 0:
        time.sleep(wait)
    stable = []
    for g in groups:
        if all(before[c] is not None and _snapshot(c) == before[c] for c in g):
            stable.append(g)
        else:
            report.skipped_unstable.extend(c.rel for c in g)
            log.info(L("檔案還在變動,下一輪再取:%s"), ", ".join(c.rel for c in g))
    return stable


def _take_group(cfg: Config, inbox, group: list[Candidate], ledger: Ledger, report: Report) -> None:
    hashed: list[tuple[Candidate, str, int]] = []
    for c in group:
        try:
            hashed.append((c, sha256_of(c.path), c.path.stat().st_size))
        except OSError as e:
            log.error(L("%s:讀不到 %s:%s"), inbox.name, c.rel, e)
            report.failed.append(f"{inbox.name}:{c.rel}")

    fresh = []
    for c, sha, size in hashed:
        if ledger.lookup(sha) is not None or ledger.raw_lookup(sha) is not None:
            ledger.record_duplicate(sha, inbox.name, c.rel)
            if _release(inbox, c, report):
                report.duplicates.append(f"{inbox.name}:{c.rel}")
        else:
            fresh.append((c, sha, size))
    if not fresh:
        return

    names = pick_names(cfg.pending_dir, [c.path.name for c, _, _ in fresh])
    for (c, sha, size), name in zip(fresh, names):
        try:
            final = copy_verified(c.path, cfg.pending_dir, name, sha)
            _write_sidecar(final, inbox, c, sha, size)
            ledger.record(sha, size, inbox.name, c.rel, str(final))
        except Exception as e:  # noqa: BLE001 —— 任何失敗都一樣:保留來源、下一輪再來
            log.error(L("%s:%s 取件失敗,來源保留:%s"), inbox.name, c.rel, e)
            report.failed.append(f"{inbox.name}:{c.rel}")
            continue
        report.moved.append(str(final))
        _release(inbox, c, report)


def _release(inbox, c: Candidate, report: Report) -> bool:
    try:
        inbox.release(c)
    except OSError as e:
        # 副本與紀錄都在,來源刪不掉只會讓下一輪判成重複再刪一次
        msg = L("{inbox}:{rel} 已取到但清來源失敗:{e}", inbox=inbox.name, rel=c.rel, e=e)
        log.warning("%s", msg)
        report.alerts.append(msg)
        return False
    return True


def _write_sidecar(final: Path, inbox, c: Candidate, sha: str, size: int) -> None:
    st = final.stat()
    data = {
        "來源": inbox.name,
        "原路徑": c.rel,
        "取件時間": datetime.now().astimezone().isoformat(timespec="seconds"),
        "原檔修改時間": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
        "sha256": sha,
        "大小": size,
        **inbox.meta(),
    }
    tmp = final.with_name(f".{final.name}{SIDECAR_EXT}.partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(final.with_name(final.name + SIDECAR_EXT))  # 不用 rename:Windows 目標已存在就失敗


ALERT_REPEAT_SECONDS = 24 * 3600

# 連不上網路的錯誤字樣(DNS、逾時、連線被拒;ssh 與 https 兩種說法都有)
# 「connect to host … port 22:」「Connection reset by」「server … not responding」是公司網路擋 ssh 時的說法,
# 「Can't assign requested address」「Network is down」是網路正在切換的那一輪(2026-10-16、10-20 實例)。
# 逾時只認連線的說法:「doc2md 超過 N 秒沒跑完」這類要人看的不可被當成斷網吞掉
_NETWORK_DOWN = re.compile(r"Could not resolve|nodename nor servname|Temporary failure in name resolution|"
                           r"connect to host \S+ port \d+:|port \d+ timed out|Operation timed out|"
                           r"Connection timed out|read operation timed out|Failed to connect to|Connection reset|"
                           r"server \S+ not responding|Couldn't connect to server|Network is unreachable|"
                           r"Network is down|No route to host|Can't assign requested address|Connection refused|"
                           r"getaddrinfo failed", re.I)   # Windows 的 urllib／socket 查不到 DNS


def network_down(msg: str) -> bool:
    """這則警示只是連不上網路:不列進當日摘要、不寄信,只寫 log。STOP 一律要報。

    使用者 2026-10-20:「從家裡帶筆電到公司,連不上網路正常」——連 10-14 定的「一天一則」也拿掉。
    斷網時信本來就寄不出去,網路恢復後才收到一則「剛才斷過網」沒有用處;收件、攝入、推送下一輪都會自己再試。"""
    return bool(_NETWORK_DOWN.search(msg)) and "STOP" not in msg


def _alert(cfg: Config, msg: str) -> bool:
    """記一則警示;同一則 24 小時內只記一次。回傳這次是不是新的(新的才發到當日摘要)。

    launchd 每分鐘一輪:收件匣讀不到這類持續性的問題,不去重就是每分鐘一則、手機推播洗版。
    連不上網路的不算警示(`network_down`):只寫 log,回傳 False。
    """
    if network_down(msg):
        mark_net_down(cfg)
        log.info(L("連不上網路,不列進摘要:%s"), msg.splitlines()[0] if msg else msg)
        return False
    cfg.alerts_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path = cfg.state_dir / "alerts_seen.json"
    try:
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    now = time.time()
    key = msg
    if now - seen.get(key, 0) < ALERT_REPEAT_SECONDS:
        return False
    seen = {m: t for m, t in seen.items() if now - t < ALERT_REPEAT_SECONDS}
    seen[key] = now
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    rec = {"時間": datetime.now().astimezone().isoformat(timespec="seconds"), "訊息": msg}
    with open(cfg.alerts_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def _forget_alerts(cfg: Config, msgs: list[str]) -> None:
    """摘要信寄不出去時撤銷「已報」:否則這些警示 24 小時內不會再報。"""
    seen_path = cfg.state_dir / "alerts_seen.json"
    try:
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    keys = set(msgs)
    seen = {m: t for m, t in seen.items() if m not in keys}
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
