"""看門狗:每 3 分鐘查一次常駐程式有沒有卡住;卡住就啟動修理(見 repair.py),修完寄信。

使用者 2026-10-05 定案:「卡住了你通知我,我也是請你處理——你自己查、自己修、讓同樣的事不再發生,
修好再寄信告訴我」。之前所有警示都要等一輪跑完才寄得出去,行程卡住時(實例:FUTURES 的 ssh 卡 44 分鐘)
根本走不到寄信那一步;STOP 的信又夾在一天十幾封摘要裡。

這裡只「偵測」,不動任何東西。偵測的項目:
    stop      ingest.stop 存在(攝入停住等人)
    hung      收件／轉寫／攝入的一輪超過上限沒有心跳(collect.run_file)
    agents    launchd 的兩個 agent 沒載入(例如 deploy 在 bootout 之後被中斷)
    stuck     轉寫或攝入已停止重試的檔
    inbox     收件匣連續讀不到達警示門檻
    resource  CPU／記憶體被佔著不放(使用者 2026-10-05 要求):只查原因、寄信,不砍別人的行程
    icloud    iCloud 沒在同步(使用者 2026-10-09 要求):探針檔寫了太久沒傳上去;程式自己重啟 bird,不叫 claude
另外 icloud_kick 判斷要不要「定時重啟 bird」(下載端,使用者 2026-10-22;不是問題、不寄信,動手的是 repair.py)。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .collect import build_inboxes, last_net_down, run_file, uptime
from .config import Config
from .i18n import L
from .ledger import Ledger
from .osplat import WINDOWS, is_placeholder, oem_decode, pid_alive, try_lock, unlock

log = logging.getLogger(__name__)

AGENT_LABELS = ("tw.vli.wiki-feeder.collect", "tw.vli.wiki-feeder.process")


@dataclass
class Problem:
    kind: str       # stop / hung / agents / stuck / inbox / resource / icloud / vpbridge
    key: str        # 「同一個問題」的判準:去掉檔名、數字,修過一次又出現就改找人
    title: str      # 信件主旨用的一句話
    detail: str     # 交給修理的事實(不可信的資料:可能含檔名、攝入的輸出)
    report_only: bool = False   # 只查原因、寄信(資源類:佔用的多半不是 wiki-feeder 的行程)


def hung_limits(cfg: Config) -> dict[str, tuple[Path, float]]:
    return {
        "收件": (cfg.lock_path, cfg.collect_hung_after),
        "轉寫": (cfg.convert_lock_path, cfg.doc2md_timeout + 1800),
        "攝入": (cfg.ingest_lock_path, cfg.ingest_timeout + 900),
    }


def _alive(pid: int) -> bool:
    return pid_alive(pid)


def _nobody_holds(lock: Path, run: Path) -> bool:
    """這一階段沒有人在跑(拿得到鎖):.run 是當掉、被 SIGKILL、關機留下的,順手清掉。

    不能只看 .run 裡的 pid 還在不在:重開機或過一陣子 pid 會被別的行程用掉,照 pid 判斷會把不相干的行程
    當成卡住的一輪,unstick 就去砍它。清檔要在握著鎖的時候做:新的一輪先拿到獨佔鎖才寫 .run,不會刪到它的。
    """
    if WINDOWS:   # 朋友版的簡易看門狗(watch):只有獨佔鎖,試拿一下就放(這一瞬間新的一輪拿不到鎖、直接結束,下一分鐘再來)
        try:
            f = open(lock, "a+")
        except OSError:
            return False
        with f:
            if not try_lock(f):
                return False
            try:
                run.unlink(missing_ok=True)
            finally:
                unlock(f)
            return True
    import fcntl   # 放在函式裡:Windows 沒有 fcntl
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:
        return False   # 鎖檔不存在:不知道是誰寫的 .run,不動,照舊看 pid
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        run.unlink(missing_ok=True)
        return True
    finally:
        os.close(fd)   # 關檔就放鎖


def running(cfg: Config) -> list[dict]:
    """目前握著鎖的每一輪:階段、pid、開始時間、最後心跳。沒人握鎖、或行程已不在的 .run 檔順手清掉。"""
    out = []
    for stage, (lock, limit) in hung_limits(cfg).items():
        f = run_file(lock)
        if not f.exists() or _nobody_holds(lock, f):
            continue
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            beat = f.stat().st_mtime
        except (OSError, ValueError):
            continue
        pid = int(info.get("pid", 0))
        if not pid or not _alive(pid):
            f.unlink(missing_ok=True)
            continue
        out.append({"stage": stage, "pid": pid, "started": info.get("started", beat), "beat": beat,
                    "up": info.get("up"), "limit": limit, "lock": str(lock)})
    return out


def idle_of(r: dict, now: float) -> float:
    """那一輪多久沒心跳(秒),不含系統睡眠。舊版寫的 .run 沒有 up,才退回用檔案修改時間(牆上時間)。"""
    up = r.get("up")
    if isinstance(up, (int, float)):
        return max(0.0, uptime() - up)
    return now - r["beat"]


def deploying(cfg: Config) -> bool:
    """deploy 正握著獨佔鎖(會先 bootout 兩個 agent):這時 agent 沒載入是正常的。"""
    import fcntl
    p = cfg.deploy_lock_path
    if not p.exists():
        return False
    with open(p) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def agents_not_loaded(labels: tuple[str, ...] = AGENT_LABELS) -> list[str]:
    dom = f"gui/{os.getuid()}"
    return [lb for lb in labels
            if subprocess.run(["launchctl", "print", f"{dom}/{lb}"], capture_output=True).returncode != 0]


def tasks_not_ready(names: tuple[str, ...], run=subprocess.run) -> list[str]:
    """Windows 版的 agents_not_loaded(朋友版的簡易看門狗):工作排程器的任務(`資料夾\\名稱`)不存在或被停用。
    查 PowerShell 的 State(英文列舉);schtasks 的「狀態」欄跟著系統語言、又是 OEM 碼頁,不解析。
    PowerShell 自己跑不起來(逾時、結束碼非零)就當作查不到、不報:報出去是一則假的「排程沒有載入」。"""
    folders = sorted({n.rsplit("\\", 1)[0] for n in names})
    paths = ",".join("'\\" + f.replace("'", "''") + "\\'" for f in folders)
    cmd = (f"Get-ScheduledTask -TaskPath {paths} -ErrorAction SilentlyContinue | "
           "ForEach-Object { $_.TaskPath + $_.TaskName + '=' + $_.State }")
    try:
        r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(L("查不到工作排程器的任務狀態:%s"), e)
        return []
    if r.returncode != 0:
        log.warning(L("查不到工作排程器的任務狀態:%s"), oem_decode(r.stderr or b"").strip()[:300])
        return []
    state = {}
    for ln in oem_decode(r.stdout or b"").splitlines():
        path, _, st = ln.strip().rpartition("=")
        if path:
            state[path.lstrip("\\").lower()] = st
    return [n for n in names if state.get(n.lower()) not in ("Ready", "Running", "Queued")]


def friend_agents_check(labels: tuple[str, ...]) -> list[str]:
    """朋友版的簡易看門狗查排程:Mac 是 launchd 標籤,Windows 是工作排程器的任務名稱。"""
    return tasks_not_ready(labels) if WINDOWS else agents_not_loaded(labels)


def normalize(text: str, name: str = "") -> str:
    """問題的鍵:去掉檔名、括號裡的細節與數字——同一種毛病換一個檔再發生,算同一個問題。"""
    s = text.replace(name, "<檔>") if name else text
    s = re.sub(r"[((][^))]*[))]", "", s)
    s = re.sub(r"[0-9a-f]{7,40}", "<hash>", s)
    s = re.sub(r"\d+", "#", s)
    return s.strip()[:160]


def detect(cfg: Config, now: float | None = None, agents_check=agents_not_loaded,
           sample=None, resources_too: bool = True, icloud_check=None) -> list[Problem]:
    """sample:資源取樣 (行程清單, 可用記憶體百分比, 總記憶體 bytes);None 就實際取樣,測試換成假的。
    icloud_check:iCloud 同步狀態的查法(見 icloud_synced),測試換成假的。
    resources_too=False:不查 CPU／記憶體、不碰 iCloud 探針(修理完複查用:每查一次連續超標的次數就加一,
    探針一查可能就重寫)。"""
    now = time.time() if now is None else now
    agents_check = agents_check or agents_not_loaded
    found: list[Problem] = []

    if cfg.ingest_stop_path.exists():
        text = cfg.ingest_stop_path.read_text(encoding="utf-8")
        try:
            info = json.loads(text)
        except ValueError:
            info = {}
        reason, name = str(info.get("原因", "")), str(info.get("檔案", ""))
        # 鍵有種類就用種類:大量刪減的原因裡列著被砍的頁面路徑,normalize 只去得掉原件檔名,砍到別頁就算成
        # 新問題,每次都開一個修理(它又不能解除這種),7 天內再發生就該直接找人
        kind = info.get("種類") if isinstance(info.get("種類"), str) else ""
        found.append(Problem("stop", "stop:" + (kind or normalize(reason, name)), f"攝入停住({name})",
                             f"ingest.stop 內容:\n{text}"))

    dep = deploying(cfg)
    for r in ([] if dep else running(cfg)):   # 發佈握著全部的鎖:這時不會有任何一輪在跑
        idle = idle_of(r, now)
        if idle > r["limit"]:
            found.append(Problem("hung", f"hung:{r['stage']}", f"{r['stage']}卡住 {idle / 60:.0f} 分鐘",
                                 f"{r['stage']}那一輪(pid {r['pid']})最後一次心跳在 {idle / 60:.0f} 分鐘前,"
                                 f"上限 {r['limit'] / 60:.0f} 分鐘;鎖檔 {r['lock']}"))

    if not dep:
        down = agents_check()
        if down:
            found.append(Problem("agents", "agents", "常駐程式沒有載入",
                                 "launchd 沒有載入:" + "、".join(down)))

    if cfg.ledger_path.exists():
        with Ledger(cfg.ledger_path) as led:
            for _, path, err in led.stuck_conversions(cfg.convert_max_attempts):
                if not Path(path).exists():
                    continue   # 人已經把檔移走:轉寫那邊也不再提醒(convert._remind_stuck),這裡照做
                name = Path(path).name
                found.append(Problem("stuck", "stuck-convert:" + normalize(err or "", name),
                                     f"轉寫停止重試({name})", f"{path} 轉寫已停止重試,最後的錯誤:{err}"))
            for path in led.stuck_ingests(cfg.ingest_max_attempts):
                row = led.ingest_row_by_path(path)
                err = (row or {}).get("error") or ""
                name = Path(path).name
                found.append(Problem("stuck", "stuck-ingest:" + normalize(err, name),
                                     f"攝入停止重試({name})", f"{path} 攝入已停止重試,最後的錯誤:{err}"))

    try:
        streak = json.loads((cfg.state_dir / "inbox_streak.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        streak = {}
    # 只看設定裡的收件匣:同一個檔也記著轉寫的 doc2md(轉寫一整輪跑完才歸零,修好後還會掛著好幾十分鐘),
    # 拿掉或改名的收件匣也會一直留著舊的次數——都不是收件匣讀不到
    inboxes = {i.name for i in build_inboxes(cfg)}
    # 最近一次是連不上網路(collect._mark_offline):帶筆電出門是常態,不叫修理、不寄信,只在當日摘要報一則
    try:
        offline = json.loads((cfg.state_dir / "inbox_offline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        offline = []
    offline = set(offline) if isinstance(offline, list) else set()
    for name, n in sorted(streak.items()):
        if name in inboxes and name not in offline and isinstance(n, int) and n >= cfg.unavailable_alert_after:
            found.append(Problem("inbox", f"inbox:{name}", f"{name} 連續 {n} 輪讀不到",
                                 f"{name} 連續 {n} 輪讀不到(log 裡有每輪的錯誤)"))

    if not resources_too:
        return found
    found += icloud_probe(cfg, now, icloud_check or icloud_synced)
    found += vp_bridge_problems(cfg, now)
    try:
        procs, free_pct, total = sample() if sample else sample_resources()
    except Exception:  # noqa: BLE001 —— 取樣失敗不影響其他偵測
        return found
    found += resources(cfg, procs, free_pct, total, exclude=_exempt(cfg, procs, now))
    return found


# -- CPU／記憶體 -------------------------------------------------------------------

def processes() -> list[dict]:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pcpu=,rss=,etime=,comm="], capture_output=True, text=True,
                         timeout=30).stdout
    procs = []
    for ln in out.splitlines():
        parts = ln.split(None, 5)
        if len(parts) < 6:
            continue
        procs.append({"pid": int(parts[0]), "ppid": int(parts[1]), "cpu": float(parts[2]),
                      "rss": int(parts[3]) * 1024, "etime": parts[4], "comm": parts[5]})
    return procs


def sample_resources() -> tuple[list[dict], float | None, int]:
    procs = processes()
    m = re.search(r"free percentage:\s*(\d+)", subprocess.run(["memory_pressure", "-Q"], capture_output=True,
                                                             text=True, timeout=30).stdout)
    total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10).stdout)
    return procs, (float(m.group(1)) if m else None), total


def _descendants(procs: list[dict], roots: set[int]) -> set[int]:
    kids: dict[int, list[int]] = {}
    for p in procs:
        kids.setdefault(p["ppid"], []).append(p["pid"])
    seen, todo = set(), list(roots)
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        todo += kids.get(pid, [])
    return seen


def _exempt(cfg: Config, procs: list[dict], now: float) -> set[int]:
    """不算資源問題的:還在心跳內的收件／轉寫／攝入(長錄音轉寫本來就吃 CPU,卡住另由 hung 管),和看門狗自己。"""
    roots = {os.getpid()} | {r["pid"] for r in running(cfg) if idle_of(r, now) <= r["limit"]}
    return _descendants(procs, roots)


def resources(cfg: Config, procs: list[dict], free_pct: float | None, total: int,
              exclude: set[int] = frozenset()) -> list[Problem]:
    """連續幾次檢查都超標才算(一次高峰不算);計數記在 resource_watch.json,換了 pid 重新算(bird 除外:照執行檔算)。"""
    try:
        state = json.loads(cfg.resource_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    prev_cpu, prev_rss = state.get("cpu", {}), state.get("rss", {})
    cpu, rss, found = {}, {}, []
    top = sorted(procs, key=lambda p: -p["cpu"])[:8] + sorted(procs, key=lambda p: -p["rss"])[:8]
    snapshot = "\n".join(f"pid {p['pid']} ppid {p['ppid']} CPU {p['cpu']:.0f}% 記憶體 {p['rss'] / 2**30:.1f} GB "
                         f"已執行 {p['etime']} {p['comm']}" for p in top)
    for p in procs:
        if p["pid"] in exclude:
            continue
        k = BIRD if p["comm"] == BIRD else str(p["pid"])   # 定時重啟每 15 分鐘換掉 bird 的 pid
        if p["cpu"] >= cfg.resource_cpu_pct:
            cpu[k] = prev_cpu.get(k, 0) + 1
            if cpu[k] >= cfg.resource_cpu_ticks:
                found.append(Problem("resource", f"resource:cpu:{Path(p['comm']).name}",
                                     f"CPU 被佔用({Path(p['comm']).name})",
                                     f"pid {p['pid']}({p['comm']})連續 {cpu[k]} 次檢查 CPU ≥ {cfg.resource_cpu_pct:.0f}%"
                                     f"(目前 {p['cpu']:.0f}%,已執行 {p['etime']})。\n目前前幾名:\n{snapshot}",
                                     report_only=True))
        if total and p["rss"] >= total * cfg.resource_rss_frac:
            rss[k] = prev_rss.get(k, 0) + 1
            if rss[k] >= cfg.resource_mem_ticks:
                found.append(Problem("resource", f"resource:rss:{Path(p['comm']).name}",
                                     f"記憶體被佔用({Path(p['comm']).name})",
                                     f"pid {p['pid']}({p['comm']})連續 {rss[k]} 次檢查佔用 {p['rss'] / 2**30:.1f} GB"
                                     f"(總共 {total / 2**30:.0f} GB)。\n目前前幾名:\n{snapshot}", report_only=True))
    low = state.get("mem_low", 0) + 1 if free_pct is not None and free_pct < cfg.resource_mem_free_pct else 0
    if low >= cfg.resource_mem_ticks:
        found.append(Problem("resource", "resource:mem-low", "可用記憶體不足",
                             f"整台可用記憶體連續 {low} 次低於 {cfg.resource_mem_free_pct:.0f}%(目前 {free_pct:.0f}%)。"
                             f"\n目前前幾名:\n{snapshot}", report_only=True))
    cfg.resource_state_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.resource_state_path.write_text(json.dumps({"cpu": cpu, "rss": rss, "mem_low": low}), encoding="utf-8")
    return found


# -- iCloud 同步 -------------------------------------------------------------------

PROBE_NAME = "心跳.txt"
LAST_SYNC = re.compile(r"last-sync:(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")   # brctl status 的整個 iCloud 雲碟最後同步
# 檔案本身有沒有傳上去(NSURLUbiquitousItemIsUploadedKey);印 true／false
_UPLOADED_JS = """ObjC.import('Foundation');
function run(argv) {
  const v = Ref();
  const ok = $.NSURL.fileURLWithPath(argv[0]).getResourceValueForKeyError(v, $('NSURLUbiquitousItemIsUploadedKey'), null);
  return ok ? String(ObjC.unwrap(v[0])) : 'error';
}"""


def probe_path(cfg: Config) -> Path:
    return cfg.icloud_probe_dir / PROBE_NAME


def icloud_synced(path: Path, since: float) -> tuple[bool | None, str]:
    """since(寫入時間)之後 iCloud 有沒有把 path 傳上去。None:查不了(工具跑不起來,不是 iCloud 的問題)。

    兩個都要成立:剛寫完的幾秒內「已上傳」還是舊的 true(2026-10-09 實測),只看它會把卡住當成正常;
    brctl 的 last-sync 是整個 iCloud 雲碟最後一次同步,要晚於寫入時間才表示 bird 真的動過。
    """
    try:
        st = subprocess.run(["brctl", "status", "com.apple.CloudDocs"], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "brctl status 60 秒沒有回應(bird 可能卡住)"
    except OSError as e:
        return None, f"brctl 跑不起來:{e}"
    try:
        js = subprocess.run(["osascript", "-l", "JavaScript", "-e", _UPLOADED_JS, str(path)],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"查不了探針檔的上傳狀態:{e}"
    up = js.stdout.strip()
    if up not in ("true", "false"):
        return None, f"查不了探針檔的上傳狀態:{(js.stderr or js.stdout).strip()[:300]}"
    m = LAST_SYNC.search(st.stdout)
    if not m and "last-sync:never" not in st.stdout:
        return None, f"brctl status 看不懂:{(st.stderr or st.stdout).strip()[:300]}"
    last = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp() if m else None
    ok = up == "true" and last is not None and last >= int(since)
    return ok, f"探針檔已上傳:{up};iCloud 雲碟最後同步:{m.group(1) if m else '從未'}"


def write_probe(cfg: Config, now: float) -> None:
    """覆寫探針檔、記下寫入時間。資料夾只建一層:iCloud 雲碟整個不見(登出)要寫失敗,不可替它建出來。"""
    cfg.icloud_probe_dir.mkdir(exist_ok=True)
    probe_path(cfg).write_text(f"wiki-feeder 看門狗的 iCloud 同步探針,可以不理它。{datetime.fromtimestamp(now)}\n",
                               encoding="utf-8")
    cfg.icloud_probe_state_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.icloud_probe_state_path.write_text(json.dumps({"written": now, "up": uptime(), "pending": True}),
                                           encoding="utf-8")


def _rewrite_probe(cfg: Config, now: float) -> list[Problem]:
    try:
        write_probe(cfg, now)
    except OSError as e:
        return [Problem("icloud", "icloud:stalled", "iCloud 沒在同步",
                        f"探針檔寫不進 iCloud 雲碟({cfg.icloud_probe_dir}):{e}")]
    return []


def icloud_probe(cfg: Config, now: float, synced=icloud_synced) -> list[Problem]:
    """沒丟檔時 iCloud 本來就不同步,「最後同步時間」舊了分不出壞了還是沒事做,所以自己製造一點流量:
    每 icloud_probe_every 寫一次探針,寫了 icloud_sync_timeout 還沒傳上去才算卡住。
    時間用不含睡眠的時鐘:睡前寫的探針,醒來牆上時間過了很久,不算卡住。"""
    if cfg.icloud_probe_dir is None:
        return []
    try:
        state = json.loads(cfg.icloud_probe_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    up_w, written = state.get("up"), state.get("written")
    age = uptime() - up_w if isinstance(up_w, (int, float)) else -1
    if age < 0 or not isinstance(written, (int, float)) or (not state.get("pending") and age >= cfg.icloud_probe_every):
        return _rewrite_probe(cfg, now)   # 沒寫過、重開機過(不含睡眠的時鐘歸零)、或該寫下一次了
    if not state.get("pending") or age < cfg.icloud_sync_timeout:
        return []
    ok, detail = synced(probe_path(cfg), written)
    if ok:
        state["pending"] = False
        cfg.icloud_probe_state_path.write_text(json.dumps(state), encoding="utf-8")
        return []
    if ok is False and last_net_down(cfg) >= written:
        # 寫入之後斷過網(帶筆電出門、Wi-Fi 斷線):沒傳上去是網路的事,重寫探針、從現在重新計時(2026-10-22 實例)
        return _rewrite_probe(cfg, now)
    if ok is None:
        return [Problem("resource", "icloud:check", "iCloud 同步檢查跑不起來",
                        f"查不了 iCloud 有沒有在同步(不是 iCloud 本身的問題,是檢查的工具):{detail}", report_only=True)]
    return [Problem("icloud", "icloud:stalled", "iCloud 沒在同步",
                    f"探針檔 {probe_path(cfg)} 寫進去 {age / 60:.0f} 分鐘還沒傳上 iCloud(上限 "
                    f"{cfg.icloud_sync_timeout / 60:.0f} 分鐘)。{detail}")]


# -- iCloud 下載端:定時重啟 bird ---------------------------------------------------
# 探針只測得到「上傳」:2026-10-22 手機 16:32 送出的檔 Mac 一直沒下載,探針 16:35:50 寫入、16:35:54 照樣傳上去
# (last-sync 就是被它刷新的),所以探針看來一切正常;16:46 手動重啟 bird,10 秒內檔就到了。Mac 看不到還沒下載的檔,
# 下載端卡住沒有訊號可查,last-sync 又被探針自己的上傳刷新,也不能拿來判斷。能做的只有定時重啟(repair._kick_icloud)。
# 「傳輸中不重啟」看收件匣的佔位檔(還在下載的檔就是佔位檔),不看流量:nettop 的 cloudd 位元組是「當下開著的連線」
# 的加總、cloudd 又是整台所有 CloudKit App 共用的(照片、鑰匙圈…),量不出 iCloud 雲碟在不在傳(2026-10-22 審查);
# brctl status 在 80 MB 上傳全程都是 client:idle(同日實測),也不能用。

BIRD = "/System/Library/PrivateFrameworks/iCloudDriveCore.framework/Versions/A/Support/bird"


def last_sync(text: str | None) -> float | None:
    m = LAST_SYNC.search(text or "")
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp() if m else None


def brctl_status(timeout: float = 60) -> str | None:
    """brctl status 的輸出(含錯誤訊息);60 秒沒回應回 None。要在有「完整磁碟取用權限」的 python 底下跑:
    launchd 直接跑 brctl 會被擋(self-check failed ... Access denied,2026-10-22 實測)。
    ⚠️ 這也是叫醒 bird 的呼叫:bird 不是 KeepAlive,砍掉後要有人用 IPC 找它才會被叫起來(2026-10-22 審查:
    沒人找的話空窗到下一輪看門狗、約 3 分鐘)。"""
    try:
        r = subprocess.run(["brctl", "status", "com.apple.CloudDocs"], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except OSError as e:
        return L("brctl 跑不起來:{e}", e=e)
    return r.stdout + r.stderr


def bird_running() -> bool:
    return any(p["comm"] == BIRD for p in processes())


def inbox_placeholders(folder: Path | None) -> list[str] | None:
    """收件匣裡內容還在雲端的檔(相對路徑);讀不到回 None。舊式 `.名稱.icloud` 記成原名。"""
    if folder is None:
        return None
    found = []
    try:
        for root, _dirs, files in os.walk(folder, onerror=_raise):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), folder)
                if fn.startswith(".") and fn.endswith(".icloud"):
                    found.append(os.path.join(os.path.dirname(rel), fn[1:-len(".icloud")]))
                elif is_placeholder(os.stat(os.path.join(root, fn), follow_symlinks=False)):
                    found.append(rel)
    except OSError:
        return None
    return sorted(found)


def _raise(e: OSError) -> None:
    raise e


def _kick_state(cfg: Config) -> dict:
    try:
        st = json.loads(cfg.icloud_kick_state_path.read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_kick_state(cfg: Config, st: dict) -> None:
    cfg.icloud_kick_state_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.icloud_kick_state_path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def mark_kicked(cfg: Config, now: float, net: str | None = None) -> None:
    """記下重啟 bird 的時間(牆上時間)與當時的網路(net_id;None = 查不到、不記)。探針卡住、聲紋橋樑的修理
    重啟 bird 也記這裡:定時重啟從那時重新計時,不會剛修完又被定時重啟一次;換網路後修理已經重啟過的,也不會再為了
    換網路砍一次。睡醒後第一輪多半就到期,照樣重啟——睡醒的 bird 常常沒接上。"""
    st = _kick_state(cfg)
    st["kicked"] = now
    if net is not None:
        st["net"] = net
    _save_kick_state(cfg, st)


def _probe_note(cfg: Config) -> tuple[str, bool]:
    """探針的狀態(寫進紀錄:定時重啟順手修好的上傳卡住,事後至少看得出來)與「剛寫入、還在等上傳」。"""
    if cfg.icloud_probe_dir is None:
        return "", False   # 朋友版沒有探針
    try:
        st = json.loads(cfg.icloud_probe_state_path.read_text(encoding="utf-8"))
        age = uptime() - st["up"]
    except (OSError, ValueError, KeyError, TypeError):
        return L("探針沒有狀態"), False
    if not st.get("pending"):
        return L("探針已確認傳上去"), False
    return L("探針寫入 {m} 分鐘、等確認", m=f"{age / 60:.0f}"), 0 <= age < KICK_PROBE_GRACE


KICK_PROBE_GRACE = 180   # 探針寫入後這麼久內不重啟(看門狗一輪):重啟會打斷它的上傳,修理時又被誤判成卡住


def net_id(timeout: float = 10) -> str | None:
    """這台現在接在哪個網路上:IPv4 與 IPv6 預設路由的介面＋閘道(本機查詢,不連網)。沒有預設路由回 ""(沒接網路);
    route 跑不起來回 None(查不到,不可當成換了網路)。
    2026-10-27:筆電從家裡帶到公司接 iPad 熱點,Mac 的 iCloud 很久沒把手機送來的檔載下來,使用者在 Finder 打開
    收件匣才 2 分鐘就到。IPv4 閘道 iPhone、iPad 熱點都是 172.20.10.1,分不出來;IPv6 的閘道是那台裝置自己的位址,分得出來。"""
    parts = []
    for fam in ("-inet", "-inet6"):
        try:
            r = subprocess.run(["route", "-n", "get", fam, "default"], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        info = dict(ln.strip().split(": ", 1) for ln in r.stdout.splitlines() if ": " in ln)
        if r.returncode == 0 and info.get("interface"):
            parts.append(f"{info['interface']}/{info.get('gateway', '')}")
    return "|".join(parts)


def icloud_kick(cfg: Config, now: float, status: str | None, pending: list[str] | None,
                net: str | None = None) -> tuple[bool, str]:
    """這一輪該不該重啟 bird,以及寫進 icloud.log 的那一行(連不連得上 iCloud 由呼叫端在要重啟時才查)。
    pending:收件匣的佔位檔(None = 讀不到);每個佔位檔記下第一次看到的時間,icloud_busy_max 內算「下載中」、
    不重啟;超過的就是下載卡住了,照樣重啟。
    net:現在的網路(net_id;None = 查不到)。跟上次重啟時記的不一樣(換了網路,或斷過網又接上)就不等 15 分鐘,
    其他擋著的條件照舊。沒接網路("")也記下來:接回同一個網路時才看得出「斷過」。"""
    st = _kick_state(cfg)
    kicked = st.get("kicked")
    old_net = st.get("net")
    if net == "" and old_net != "":
        st["net"] = ""
        _save_kick_state(cfg, st)
    moved = bool(net) and isinstance(old_net, str) and net != old_net
    last = last_sync(status)
    if last is not None:
        parts = [L("last-sync 距今 {s} 秒", s=f"{now - last:.0f}")]
    elif status is None:
        parts = [L("brctl status 60 秒沒回應")]
    else:
        parts = [L("讀不到 last-sync:") + " ".join(status.split())[:200]]
    probe, probe_fresh = _probe_note(cfg)
    if probe:
        parts.append(probe)
    downloading = None
    if pending is None:
        parts.append(L("收件匣讀不到"))
    else:
        old = st.get("placeholders") if isinstance(st.get("placeholders"), dict) else {}
        seen = {n: old.get(n, now) for n in pending}
        if seen != old:
            st["placeholders"] = seen
            _save_kick_state(cfg, st)
        downloading = [n for n, t in seen.items() if now - t < cfg.icloud_busy_max]
        stuck = len(seen) - len(downloading)
        parts.append(L("收件匣佔位檔 {n} 個(下載中 {d}、超過 {m} 分鐘 {s})", n=len(seen), d=len(downloading),
                       m=f"{cfg.icloud_busy_max / 60:.0f}", s=stuck) if seen else L("收件匣沒有佔位檔"))
    if net is not None:
        parts.append(L("網路 {net}", net=net or L("沒接上")))
    if bool(net) and not isinstance(old_net, str):
        st["net"] = net   # 第一次看到網路:當基準,不算換了網路
        _save_kick_state(cfg, st)
    since = now - kicked if isinstance(kicked, (int, float)) else None
    if moved:
        parts.append(L("網路換了(上次重啟時是 {old})", old=old_net or L("沒接上")))
    if since is not None and 0 <= since < cfg.icloud_kick_every and not moved:
        return False, L("、").join(parts) + L(";距上次重啟 {m} 分鐘,不重啟", m=f"{since / 60:.0f}")
    if downloading is None:
        return False, L("、").join(parts) + L(";看不到收件匣有沒有檔在下載,這輪不重啟")
    if downloading:
        # 重啟會打斷下載(檔維持佔位、重開後重載);大檔下載超過 icloud_kick_every 的話每到期就被打斷一次
        return False, L("、").join(parts) + L(";收件匣有檔在下載,不重啟")
    if probe_fresh:
        return False, L("、").join(parts) + L(";探針剛寫入,下一輪再重啟")
    return True, L("、").join(parts)


def icloud_log(cfg: Config, now: float, line: str) -> None:
    """每輪一行(使用者 2026-10-22 要求看得到 last-sync 距今幾秒、有沒有重啟);只留 icloud_log_keep_days 天。
    不寫進 feeder.log:每 3 分鐘一行會把那邊的輪替洗掉(重啟另外記一行在 feeder.log)。
    第一行比保留天數再舊一天才整份重寫:每輪都剛好有一行過期,照「過期就重寫」會變成每 3 分鐘重寫 0.5 MB。"""
    path = cfg.icloud_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%Y-%m-%d %H:%M:%S"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.fromtimestamp(now).strftime(fmt)} {line}\n")
    with open(path, encoding="utf-8", errors="replace") as f:
        first = f.readline()
    if first[:19] >= datetime.fromtimestamp(now - (cfg.icloud_log_keep_days + 1) * 86400).strftime(fmt):
        return
    cutoff = datetime.fromtimestamp(now - cfg.icloud_log_keep_days * 86400).strftime(fmt)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(ln for ln in lines if ln[:19] >= cutoff), encoding="utf-8")
    os.replace(tmp, path)


# -- 聲紋同步橋樑 -------------------------------------------------------------------

def vp_bridge_failing(cfg: Config, now: float) -> dict[str, dict]:
    """橋樑狀態檔裡卡太久的檔。狀態檔太舊(睡醒後橋樑還沒跑、或已經不跑了)不算:那份「讀不到」可能早就好了。"""
    if cfg.vp_bridge_status is None:
        return {}
    try:
        st = json.loads(cfg.vp_bridge_status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    t = st.get("time") if isinstance(st, dict) else None
    if not isinstance(t, (int, float)) or now - t > cfg.vp_bridge_fresh:
        return {}
    failing = st.get("failing") if isinstance(st.get("failing"), dict) else {}
    return {n: f for n, f in failing.items()
            if isinstance(f, dict) and isinstance(f.get("since"), (int, float))
            and now - f["since"] >= cfg.vp_bridge_stuck_after}


def vp_bridge_problems(cfg: Config, now: float) -> list[Problem]:
    stuck = vp_bridge_failing(cfg, now)
    if not stuck:
        return []
    lines = [f"- {n}:{f.get('path', '')} 已經 {(now - f['since']) / 60:.0f} 分鐘讀不到({f.get('error', '')})"
             for n, f in sorted(stuck.items())]
    return [Problem("vpbridge", "vpbridge:stuck", "聲紋同步橋樑讀不到雲端檔",
                    "聲紋同步橋樑(iCloud ⇄ OneDrive 的 _聲紋同步)這些檔一直讀不到,手機與電腦之間的聲紋沒在同步:\n"
                    + "\n".join(lines))]


# -- 解開卡住的一輪 ------------------------------------------------------------------

def unstick(cfg: Config, now: float | None = None, procs: list[dict] | None = None, wait: float = 10) -> str:
    """只處理超過心跳上限的那一輪:先砍它的子孫(卡住的 git／ssh／claude／doc2md),讓那一輪自己照失敗處理收尾;
    沒有子孫(卡在 python 本身)才砍它。2026-10-05 實例:ssh 卡 44 分鐘,砍掉 ssh 之後那輪照「讀不到」收尾。

    攝入那輪被砍的話處理紀錄會留著 ingesting,下一輪轉成 STOP,一樣有人(或自動修理)接手。
    """
    import signal

    if deploying(cfg):
        return "正在發佈新版(發佈握著全部的鎖,這時不會有任何一輪在跑),不動"
    now = time.time() if now is None else now
    procs = processes() if procs is None else procs
    msgs = []
    for r in running(cfg):
        idle = idle_of(r, now)
        if idle <= r["limit"]:
            msgs.append(f"{r['stage']}(pid {r['pid']})還在心跳內({idle / 60:.0f} 分鐘),不動")
            continue
        kids = _descendants(procs, {r["pid"]}) - {r["pid"]}
        targets = kids or {r["pid"]}
        names = {p["pid"]: p["comm"] for p in procs}
        for pid in targets:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:   # 已經結束(ProcessLookupError)或不是自己的行程(PermissionError):都不動
                pass
        time.sleep(wait)
        for pid in targets:
            if _alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        msgs.append(f"{r['stage']}(pid {r['pid']})卡住 {idle / 60:.0f} 分鐘,已結束:"
                    + "、".join(f"{pid} {Path(names.get(pid, '?')).name}" for pid in sorted(targets)))
    return "\n".join(msgs) or "沒有正在跑的一輪"
