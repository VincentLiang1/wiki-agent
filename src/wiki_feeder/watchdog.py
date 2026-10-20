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
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .collect import build_inboxes, run_file, uptime
from .config import Config
from .ledger import Ledger

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
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _nobody_holds(lock: Path, run: Path) -> bool:
    """這一階段沒有人在跑(拿得到鎖):.run 是當掉、被 SIGKILL、關機留下的,順手清掉。

    不能只看 .run 裡的 pid 還在不在:重開機或過一陣子 pid 會被別的行程用掉,照 pid 判斷會把不相干的行程
    當成卡住的一輪,unstick 就去砍它。清檔要在握著鎖的時候做:新的一輪先拿到獨佔鎖才寫 .run,不會刪到它的。
    """
    import fcntl   # 看門狗只在 Mac 跑;放在函式裡,Windows 上 import 這個模組(附錄常數的測試)才不會失敗
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


def agents_not_loaded() -> list[str]:
    dom = f"gui/{os.getuid()}"
    return [lb for lb in AGENT_LABELS
            if subprocess.run(["launchctl", "print", f"{dom}/{lb}"], capture_output=True).returncode != 0]


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
    for name, n in sorted(streak.items()):
        if name in inboxes and isinstance(n, int) and n >= cfg.unavailable_alert_after:
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
    """連續幾次檢查都超標才算(一次高峰不算);計數記在 resource_watch.json,換了 pid 重新算。"""
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
        k = str(p["pid"])
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
    m = re.search(r"last-sync:(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", st.stdout)
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
        try:   # 沒寫過、重開機過(不含睡眠的時鐘歸零)、或該寫下一次了
            write_probe(cfg, now)
        except OSError as e:
            return [Problem("icloud", "icloud:stalled", "iCloud 沒在同步",
                            f"探針檔寫不進 iCloud 雲碟({cfg.icloud_probe_dir}):{e}")]
        return []
    if not state.get("pending") or age < cfg.icloud_sync_timeout:
        return []
    ok, detail = synced(probe_path(cfg), written)
    if ok:
        state["pending"] = False
        cfg.icloud_probe_state_path.write_text(json.dumps(state), encoding="utf-8")
        return []
    if ok is None:
        return [Problem("resource", "icloud:check", "iCloud 同步檢查跑不起來",
                        f"查不了 iCloud 有沒有在同步(不是 iCloud 本身的問題,是檢查的工具):{detail}", report_only=True)]
    return [Problem("icloud", "icloud:stalled", "iCloud 沒在同步",
                    f"探針檔 {probe_path(cfg)} 寫進去 {age / 60:.0f} 分鐘還沒傳上 iCloud(上限 "
                    f"{cfg.icloud_sync_timeout / 60:.0f} 分鐘)。{detail}")]


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
