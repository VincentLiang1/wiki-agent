"""朋友版的自動更新:watch 那一輪決定要不要換版,換版交給另一個獨立的行程(使用者 2026-10-23;spec §7.9)。
Windows 與 Mac 共用這一支(平台不同的地方都看 `UpdateDeps.windows`),換版程式各一支:`scripts/winautoupdate.py`、
`scripts/macautoupdate.py`。

- 一天查一次(`update_check_every`),只換到**最新版**,而且要發佈滿 1 天(`update_min_age`;使用者 2026-10-23:
  發佈後 24 小時內發現問題可以趕快補發下一版)。最新版還不滿 1 天就先不換——不退而求其次換上一版(關機好幾天的電腦
  開機時會先拿到上一版、隔天再換一次)——記下它滿 1 天的時間,到了那一輪就換。git 裝的看 origin/main 最新 commit
  的時間,zip／App 裝的看附了安裝包的最新 Release 的 published_at(Windows 那一步轉正式的時間)
- 只動朋友的安裝:git 裝的 origin 要是公開 repo(看設定裡的原始 URL,不看 insteadOf 改寫後的);Windows 從 zip 裝的
  要有 VERSION 與 MANIFEST、沒有 .git;Mac 雙擊 App 裝的要有 .app-bundle 與 VERSION、沒有 .git。使用者自己的開發目錄
  與發佈副本(origin 是私人 repo 或本機路徑)永遠不動
- 公開 repo 根目錄的 `UPDATES.json` 是更新說明(publish_public 發佈時蓋上來源與日期;Mac App 的 payload 也帶一份):
  本機沒有的那幾筆就是這次會換上的版本,其中任何一筆 `needs_human` 就不自動裝,寄信請朋友手動更新(兩個平台共用)
- Windows:換版程式用 DETACHED_PROCESS 開(watch 自己的 python 載入了 numpy,Windows 上換不掉被載入的檔;
  2026-10-23 實測:watch 結束後任務回到 Ready,子行程照跑)。watch 任務**不停用**:換版程式中途死掉(斷電)時,
  下一輪 watch 看到鎖檔的 pid 不在就把排程重新啟用
- Mac:換版程式用 setsid 開(2026-10-23 實測:launchd 結束或 bootout 那個 job 時只砍它自己的行程群組)。agent 不停用,
  換版程式拿 deploy.lock 的獨佔鎖等正在跑的那一輪;中途死掉時鎖跟著放掉,下一輪 watch 照樣 macsched install 一次
- 結果另寄一封信(不併進當日摘要);同一個版本、同一種結果只寄一次,寄不出去下一輪再寄;每次都寫 logs/update.log
- 連不上網路只寫 log、不寄信、不算失敗,一小時後再查
"""
from __future__ import annotations

import io
import json
import logging
import os
import plistlib
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .collect import network_down
from .config import Config
from .i18n import L, get_lang
from .osplat import friend_claude_hint, friend_update_hint, pid_alive
from .proc import run_net

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"
PUBLIC_URLS = ("https://github.com/vincentliang1/wiki-agent.git", "https://github.com/vincentliang1/wiki-agent")
RELEASES_API = "https://api.github.com/repos/VincentLiang1/wiki-agent/releases?per_page=30"
ASSET = "wiki-agent-win.zip"        # 與 scripts/winupdate.py、release_win.py 同一個名字
MAC_ASSET = "wiki-agent-mac.zip"    # 與 scripts/make_mac_app.ZIP_NAME 同一個名字
MAC_APP = "wiki-agent.app"
NOTES = "UPDATES.json"
FETCH_TIMEOUT = 180
DETACHED = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


@dataclass
class UpdateDeps:
    """測試換成假的:不碰網路、不開行程、不寄信。"""
    now: Callable[[], float] = time.time
    run: Callable[..., subprocess.CompletedProcess] = None       # 本機的 git(不連網)
    run_net: Callable[..., subprocess.CompletedProcess] = run_net
    get: Callable[[str], bytes] = None                            # HTTP GET(zip／App 裝的才用)
    mail: Callable[[Config, str, str], None] = None
    spawn: Callable[[list[str]], int] = None                      # 開換版程式,回傳 pid
    alive: Callable[[int], bool] = pid_alive
    enable: Callable[[str], None] = None                          # 換版程式死掉時把排程重新啟用／裝回去
    windows: bool = WINDOWS
    extra: dict = field(default_factory=dict)


def _git_local(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wiki-agent-update", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _python(root: Path, windows: bool = WINDOWS) -> Path:
    return root / ".venv" / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


def _spawn(cmd: list[str]) -> int:
    return subprocess.Popen(cmd, creationflags=DETACHED, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid


def _spawn_mac(cmd: list[str]) -> int:
    # setsid:launchd 結束(或 bootout)watch 那個 job 時只砍它的行程群組(2026-10-23 實測),換版程式照跑
    return subprocess.Popen(cmd, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid


def default_deps(root: Path, windows: bool = WINDOWS) -> UpdateDeps:
    from .notify import send

    if windows:
        def enable(folder: str) -> None:
            subprocess.run([str(_python(root, True)), "-X", "utf8", str(root / "scripts" / "winsched.py"), "enable",
                            "--folder", folder], capture_output=True, timeout=600)
        return UpdateDeps(run=_git_local, get=_get, mail=send, spawn=_spawn, enable=enable, windows=True)

    def enable_mac(prefix: str) -> None:
        # agent 從頭到尾沒停用;換版程式死在 macsched install 的半途時可能少了幾個,裝一次
        subprocess.run([str(_python(root, False)), str(root / "scripts" / "macsched.py"), "install",
                        "--prefix", prefix], capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    return UpdateDeps(run=_git_local, get=_get, mail=send, spawn=_spawn_mac, enable=enable_mac, windows=False)


# -- 狀態與紀錄 ----------------------------------------------------------------------

def _load(path: Path) -> dict:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def update_log(cfg: Config, now: float, old: str, new: str, result: str, detail: str = "") -> None:
    """logs/update.log:一行一次(時間、舊版、新版、結果)。"""
    cfg.update_log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
    line = "\t".join([stamp, old or "-", new or "-", result] + ([detail.replace("\n", " ")[:500]] if detail else []))
    with open(cfg.update_log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# -- 安裝種類與候選版本 ----------------------------------------------------------------

def install_kind(root: Path, run=_git_local, windows: bool = WINDOWS) -> str:
    """'git'(origin 是公開 repo)、'zip'(Windows 從安裝包裝的)、'app'(Mac 雙擊 App 裝的)、
    ''(開發目錄、發佈副本或看不出來:不動)。⚠️ 一定先看 .git:有 .git 的只認 origin,不管旁邊還有什麼檔。"""
    if (root / ".git").exists():
        r = run(["git", "config", "--get", "remote.origin.url"], cwd=root)
        url = r.stdout.strip().lower().rstrip("/") if r.returncode == 0 else ""
        return "git" if url in PUBLIC_URLS else ""
    if windows:
        if (root / "VERSION").is_file() and (root / "MANIFEST").is_file():
            return "zip"
        return ""
    if (root / ".app-bundle").is_file() and (root / "VERSION").is_file():
        return "app"
    return ""


class NetDown(Exception):
    """連不上網路(或 GitHub 暫時出錯):只寫 log,一小時後再查。"""


class TooNew(Exception):
    """最新版發佈還不滿 update_min_age:等到 ready_at 那一輪再換(不換上一版)。"""

    def __init__(self, label: str, ready_at: float):
        super().__init__(label)
        self.label, self.ready_at = label, ready_at


def parse_notes(text: str | bytes | None) -> list[dict]:
    try:
        v = json.loads(text) if text else []
    except ValueError:
        return []
    return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []


def new_entries(local: list[dict], target: list[dict]) -> list[dict]:
    """目標版本的更新說明裡、本機還沒有的那幾筆(依 source 比);本機沒有說明檔就只算最新那一筆。"""
    have = {e.get("source") for e in local}
    if not local:
        return target[:1]
    return [e for e in target if e.get("source") not in have]


def notes_text(entries: list[dict]) -> str:
    lang = get_lang()
    out = []
    for e in entries:
        body = (e.get(lang) or e.get("zh-Hant") or "").strip()
        out.append(f"■ {e.get('date', '')}" + L("(來源 {s})", s=str(e.get("source", ""))[:7]) + f"\n{body}")
    return "\n\n".join(out)


@dataclass
class Candidate:
    kind: str
    target: str          # git:commit sha;zip／app:tag
    label: str           # 給人看的版本名
    entries: list[dict]
    current: str = ""
    zip_path: Path | None = None
    python_changed: str = ""   # Mac git 裝的:.python-version 變了(「舊 → 新」);換了完整磁碟取用權限會掉


def git_candidate(cfg: Config, root: Path, now: float, deps: UpdateDeps) -> Candidate | None:
    r = deps.run_net(["git", "fetch", "-q", "origin"], timeout=FETCH_TIMEOUT, cwd=root)
    if r.returncode != 0:
        err = (r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else r.stderr or "").strip()
        raise NetDown(err or "git fetch")
    run = deps.run
    head = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    target = run(["git", "rev-parse", "origin/main"], cwd=root).stdout.strip()
    if not target or target == head:
        return None
    if run(["git", "merge-base", "--is-ancestor", head, target], cwd=root).returncode != 0:
        log.warning("自動更新:本機的版本不在公開 repo 的 main 上,不更新(%s)", head[:7])
        return None
    published = float(run(["git", "log", "-1", "--format=%ct", target], cwd=root).stdout.strip() or 0)
    if now - published < cfg.update_min_age:
        raise TooNew(target[:7], published + cfg.update_min_age)
    msg = run(["git", "log", "-1", "--format=%cs%n%B", target], cwd=root).stdout
    day, _, body = msg.partition("\n")
    m = re.search(r"來源 ([0-9a-f]{7,})", body)        # publish_public 的訊息「發佈 日期(來源 <sha>)」
    src = m.group(1) if m else target
    local = parse_notes(_read(root / NOTES))
    shown = run(["git", "show", f"{target}:{NOTES}"], cwd=root)
    entries = new_entries(local, parse_notes(shown.stdout if shown.returncode == 0 else ""))
    cand = Candidate("git", target, f"{src[:7]}({day})", entries, current=head[:7])
    if not deps.windows:
        # Mac:launchd 直接跑 .venv 的 python,完整磁碟取用權限綁在 python 本體的路徑上;uv sync 照新的
        # .python-version 換了小版本,權限就掉了、收件匣讀不到。換之前就看出來,寄信請朋友手動更新、重加權限
        pv = [run(["git", "show", f"{rev}:.python-version"], cwd=root) for rev in (head, target)]
        old, new = (p.stdout.strip() if p.returncode == 0 else "" for p in pv)
        if old != new:
            cand.python_changed = f"{old or '?'} → {new or '?'}"
    return cand


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _published(rel: dict) -> float:
    try:
        return datetime.fromisoformat(rel["published_at"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError, AttributeError) as e:
        raise NetDown(f"published_at: {e}") from e


def _download(asset: dict, deps: UpdateDeps) -> bytes:
    try:
        data = deps.get(asset["browser_download_url"])
    except OSError as e:
        raise NetDown(str(e)) from e
    digest = (asset.get("digest") or "").removeprefix("sha256:")
    import hashlib
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise NetDown(L("下載的 zip 跟 GitHub 記的 sha256 對不上"))
    return data


def _releases(deps: UpdateDeps) -> list[dict]:
    try:
        v = json.loads(deps.get(RELEASES_API))
    except (OSError, ValueError) as e:
        raise NetDown(str(e)) from e
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def zip_candidate(cfg: Config, root: Path, now: float, deps: UpdateDeps) -> Candidate | None:
    sys.path.insert(0, str(root / "scripts"))
    from winupdate import UpdateError, local_version, parse_version, read_zip   # noqa: E402 —— 朋友那邊的驗法
    releases = _releases(deps)
    current = local_version(root).get("tag", "")
    pick = None
    for rel in releases:                       # 新的在前
        if rel.get("tag_name") == current:
            break
        if rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET), None)
        if asset:                              # 沒附安裝包的(Windows 還沒收尾)跳過,不當成最新版
            pick = (rel, asset)
            break
    if pick is None:
        return None
    rel, asset = pick
    published = _published(rel)
    if now - published < cfg.update_min_age:   # 先看時間再下載:不滿 1 天的不必下載
        raise TooNew(rel["tag_name"], published + cfg.update_min_age)
    data = _download(asset, deps)
    try:
        files = read_zip(data)
    except UpdateError as e:
        raise NetDown(str(e)) from e
    if parse_version(files["VERSION"].decode("utf-8")).get("tag") != rel["tag_name"]:
        raise NetDown(L("zip 裡的版本跟 Release 對不上"))
    path = cfg.state_dir / "update.zip"
    path.write_bytes(data)
    entries = new_entries(parse_notes(_read(root / NOTES)), parse_notes(files.get(NOTES)))
    return Candidate("zip", rel["tag_name"], rel["tag_name"], entries, current=current, zip_path=path)


def tag_source(tag: str) -> str:
    """Release 的 tag 最後一段是來源短 sha(`mac-20261023-158d716`、`20261024-abc1234`)。"""
    return tag.rsplit("-", 1)[-1]


def app_candidate(cfg: Config, root: Path, now: float, deps: UpdateDeps) -> Candidate | None:
    """Mac 雙擊 App 裝的:附了 wiki-agent-mac.zip 的最新正式 Release。簽章、公證、Team ID 由換版程式驗。"""
    current = _read(root / "VERSION").strip()
    pick = None
    for rel in _releases(deps):                # 新的在前
        tag = str(rel.get("tag_name", ""))
        if current and tag_source(tag) == current[:7]:
            break
        if rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == MAC_ASSET), None)
        if asset:
            pick = (rel, asset)
            break
    if pick is None:
        return None
    rel, asset = pick
    tag = rel["tag_name"]
    published = _published(rel)
    if now - published < cfg.update_min_age:
        raise TooNew(tag, published + cfg.update_min_age)
    data = _download(asset, deps)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        info = plistlib.loads(zf.read(f"{MAC_APP}/Contents/Info.plist"))
        try:
            notes = zf.read(f"{MAC_APP}/Contents/Resources/payload/{NOTES}")
        except KeyError:
            notes = b""
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise NetDown(L("下載的 App 讀不懂:{e}", e=e)) from e
    if str(info.get("CFBundleVersion", "")) != tag_source(tag):
        raise NetDown(L("zip 裡的版本跟 Release 對不上"))
    path = cfg.state_dir / "update-mac.zip"
    path.write_bytes(data)
    entries = new_entries(parse_notes(_read(root / NOTES)), parse_notes(notes))
    return Candidate("app", tag, tag, entries, current=current[:7], zip_path=path)


# -- 信 ----------------------------------------------------------------------------

def _queue(state: dict, key: str, subject: str, body: str) -> None:
    """同一個版本、同一種結果只寄一次:寄過的記在 mailed,還沒寄出的放 pending。"""
    if key in state.setdefault("mailed", {}) or any(m["key"] == key for m in state.setdefault("pending", [])):
        return
    state["pending"].append({"key": key, "subject": subject, "body": body})


def _flush(cfg: Config, state: dict, deps: UpdateDeps, now: float) -> None:
    left = []
    for m in state.get("pending", []):
        if not cfg.mail_to or not cfg.mail_from:      # 沒設定寄信:只寫 log(已經寫了)
            state.setdefault("mailed", {})[m["key"]] = now
            continue
        try:
            deps.mail(cfg, m["subject"], m["body"])
        except Exception as e:  # noqa: BLE001 —— 寄不出去下一輪再寄
            log.warning("自動更新的信寄不出去:%s", e)
            left.append(m)
            continue
        state.setdefault("mailed", {})[m["key"]] = now
    state["pending"] = left


def _root_hint() -> str:
    return str(Path(__file__).resolve().parents[2])


def _human(deps: UpdateDeps) -> str:
    return friend_update_hint(_root_hint(), deps.windows)


def _claude(deps: UpdateDeps) -> str:
    return friend_claude_hint(_root_hint(), deps.windows)


def _result_mail(cfg: Config, state: dict, res: dict, deps: UpdateDeps) -> None:
    new, kind = res.get("label", res.get("new", "")), res.get("result")
    key = f"{res.get('target', new)}:{kind}"
    if kind == "ok":
        _queue(state, key, L("wiki-feeder 已自動更新到 {v}", v=new),
               L("已經換成新版,收件與攝入照常在跑。\n\n這次改了什麼:\n\n{notes}", notes=res.get("notes") or "-"))
    elif kind == "failed":
        _queue(state, key, L("⚠️ 需要處理｜wiki-feeder 自動更新失敗,已退回 {old}", old=res.get("old", "")),
               L("要換到 {v} 時「{step}」這一步失敗,已經退回原本的版本 {old},系統照常在跑。\n\n原因:\n{detail}\n\n"
                 "不急著處理;要的話{claude},把這封信貼給 Claude",
                 v=new, step=_step_name(res.get("step", "")), old=res.get("old", ""), detail=res.get("detail", "")[-1500:],
                 claude=_claude(deps)))
    elif kind == "rollback_failed":
        _queue(state, key, L("⚠️ 需要處理｜wiki-feeder 自動更新失敗,也沒能退回"),
               L("要換到 {v} 時「{step}」這一步失敗,退回原本的版本也沒有成功,收件或攝入可能停了。\n\n原因:\n{detail}\n\n"
                 "請{human};還是不行的話,{claude},把這封信貼給 Claude",
                 v=new, step=_step_name(res.get("step", "")), detail=res.get("detail", "")[-1500:], human=_human(deps),
                 claude=_claude(deps)))
    elif kind == "interrupted":
        _queue(state, key, L("⚠️ 需要處理｜wiki-feeder 自動更新被中斷"),
               L("換到 {v} 的途中更新程式停掉了(多半是關機或斷電),排程已經重新啟用,但程式可能停在新舊版之間。\n\n請{human}",
                 v=new, human=_human(deps)))


def _step_name(step: str) -> str:
    return {"disable": L("停用排程"), "switch": L("換成新版的檔"), "sync": L("安裝新版需要的套件(uv sync)"),
            "enable": L("重新啟用排程"), "check": L("試讀收件匣、知識庫、原件資料夾"),
            "verify": L("驗新版 App 的簽章與公證"), "lock": L("等正在跑的那一輪做完"),
            "python": L("Python 換了版本(完整磁碟取用權限會掉)"), "guard": L("確認這是朋友的安裝")}.get(step, step)


# -- 一輪 --------------------------------------------------------------------------

def _day(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def _ok(state: dict, now: float) -> None:
    """這一天查成功了(有沒有新版都算):repair._update_stale 看這個,開機好幾天都沒有就發警示請朋友手動更新。"""
    state["ok_day"] = _day(now)


def tick(cfg: Config, root: Path, folder: str, deps: UpdateDeps | None = None) -> bool:
    """watch 那一輪呼叫(folder:Windows 是工作排程器的資料夾、Mac 是 launchd 標籤的開頭)。
    回傳 True = 換版正在進行(Windows 的收件、攝入任務被停用是正常的,這輪不查排程沒載入)。"""
    deps = deps or default_deps(root)
    now = deps.now()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state = _load(cfg.update_state_path)
    try:
        busy = _tick(cfg, root, folder, deps, now, state)
    finally:
        _flush(cfg, state, deps, now)
        _save(cfg.update_state_path, state)
    return busy


def _tick(cfg: Config, root: Path, folder: str, deps: UpdateDeps, now: float, state: dict) -> bool:
    lock = _load(cfg.update_lock_path)
    if lock:
        if deps.alive(int(lock.get("pid", 0))):
            return True
        if not cfg.update_result_path.exists():   # 換版程式死掉了(斷電、被砍):排程絕不能停在停用
            deps.enable(folder)
            res = {"result": "interrupted", "target": lock.get("target", ""), "label": lock.get("label", ""),
                   "old": lock.get("old", "")}
            update_log(cfg, now, res["old"], res["label"], "interrupted", L("換版程式中途停掉,已重新啟用排程"))
            _result_mail(cfg, state, res, deps)
        cfg.update_lock_path.unlink(missing_ok=True)
    res = _load(cfg.update_result_path)
    if res:
        update_log(cfg, now, res.get("old", ""), res.get("label", ""), res.get("result", "?"), res.get("detail", ""))
        if res.get("result") in ("failed", "rollback_failed"):
            state.setdefault("failed", []).append(res.get("target", ""))   # 同一版不再自動重試,等更新的版本
        _result_mail(cfg, state, res, deps)
        cfg.update_result_path.unlink(missing_ok=True)
    if not cfg.auto_update:
        return False
    if "ready_at" in state:                    # 最新版還不滿 1 天:等到它滿 1 天那一輪,不必再等一整天
        if now < float(state["ready_at"]):
            return False
    else:
        wait = cfg.update_retry_after if state.get("retry") else cfg.update_check_every
        if now - float(state.get("checked", 0)) < wait:
            return False
    state["checked"], state["retry"] = now, False
    state.pop("ready_at", None)
    kind = install_kind(root, deps.run, deps.windows)
    if not kind:
        _ok(state, now)
        return False                           # 開發目錄、發佈副本、看不出來的:不動,也不寄信
    finder = {"git": git_candidate, "zip": zip_candidate, "app": app_candidate}[kind]
    try:
        cand = finder(cfg, root, now, deps)
    except TooNew as e:
        _ok(state, now)
        state["ready_at"] = e.ready_at
        update_log(cfg, now, "", e.label, "waiting",
                   datetime.fromtimestamp(e.ready_at).strftime("%Y-%m-%d %H:%M"))
        return False
    except NetDown as e:
        state["retry"] = True
        msg = str(e)
        offline = network_down(msg) or not msg
        if offline:                            # 沒網路的那天不算「沒查成功」(repair._update_stale)
            state["offline_days"] = sorted(set(state.get("offline_days", [])) | {_day(now)})[-14:]
        update_log(cfg, now, "", "", "offline" if offline else "check_failed", msg)
        return False
    if cand is None or cand.target in state.get("failed", []):
        _ok(state, now)
        return False
    script = root / "scripts" / ("winautoupdate.py" if deps.windows else "macautoupdate.py")
    if not script.is_file():                   # 2026-10-23 實測:發佈漏了它,開出去的行程一開就死、被當成中斷
        update_log(cfg, now, cand.current, cand.label, "check_failed", f"{script} 不存在")
        return False
    _ok(state, now)
    if any(e.get("needs_human") for e in cand.entries):
        update_log(cfg, now, cand.current, cand.label, "needs_human")
        _queue(state, f"{cand.target}:needs_human", L("wiki-feeder 有新版 {v}:這一版要你動手更新", v=cand.label),
               L("這一版有要你自己做的步驟,所以沒有自動更新。請{human},畫面上會說明要做什麼。\n\n這次改了什麼:\n\n{notes}",
                 v=cand.label, human=_human(deps), notes=notes_text(cand.entries) or "-"))
        return False
    if cand.python_changed:
        update_log(cfg, now, cand.current, cand.label, "needs_human", f".python-version {cand.python_changed}")
        _queue(state, f"{cand.target}:python", L("wiki-feeder 有新版 {v}:這一版要你動手更新", v=cand.label),
               L("這一版換了 Python 的版本({change}),換了之後背景程式讀 iCloud 雲碟的「完整磁碟取用權限」要重新加,"
                 "所以沒有自動更新。請{human},更新完照畫面上的提示重新加權限。\n\n這次改了什麼:\n\n{notes}",
                 v=cand.label, change=cand.python_changed, human=_human(deps), notes=notes_text(cand.entries) or "-"))
        return False
    if cand.kind == "git":
        dirty = deps.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root).stdout.strip()
        if dirty:
            update_log(cfg, now, cand.current, cand.label, "dirty", dirty)
            _queue(state, f"{cand.target}:dirty", L("wiki-feeder 有新版 {v},但程式資料夾有改過的檔,沒有自動更新", v=cand.label),
                   L("程式資料夾 {root} 裡有改過、還沒 commit 的檔:\n\n{files}\n\n自動更新不會蓋掉它們。"
                     "不是你改的話,{claude},把這封信貼給 Claude",
                     root=_root_hint(), files=dirty, claude=_claude(deps)))
            return False
    common = ["--root", str(root), "--state", str(cfg.state_dir), "--kind", cand.kind, "--target", cand.target,
              "--label", cand.label]
    if deps.windows:
        cmd = [str(_python(root, True).with_name("pythonw.exe")), "-I", "-S", str(script), *common,
               "--folder", folder, "--parent", str(os.getpid()), "--current", cand.current,
               "--notes", notes_text(cand.entries)]
    else:
        # python 本體(uv 管的,不在 .venv、不在 App 裡):換版途中 .venv 與 App 都會被換掉;-B 不寫 .pyc
        cmd = [os.path.realpath(_python(root, False)), "-I", "-S", "-B", str(script), *common,
               "--prefix", folder, "--current", cand.current, "--notes", notes_text(cand.entries)]
    if cand.zip_path:
        cmd += ["--zip", str(cand.zip_path)]
    pid = deps.spawn(cmd)
    _save(cfg.update_lock_path, {"pid": pid, "started": now, "target": cand.target, "label": cand.label,
                                 "old": cand.current})
    update_log(cfg, now, cand.current, cand.label, "started")
    return True
