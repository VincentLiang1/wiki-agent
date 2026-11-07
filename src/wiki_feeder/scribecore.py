"""Scribe2MD 核心的下載與安裝(spec §4.9):wiki-agent 的安裝程式從 wiki-agent 固定 tag 的 Release `scribe2md-core`
下載 `scribe2md-core-{mac,win}.zip`,照同名 manifest 驗大小與 sha256,解壓到暫存資料夾、執行核心自己的非互動安裝程式
(它把整包複製進 meeting-scribe/core/、uv sync、建 bin 連結),最後問固定入口的版本確認裝好。

核心是 1 GB 上下的下載:先比磁碟空間,下載先寫 `.part`、驗過才改名,暫存與 zip 裝完一律刪掉。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import doc2md
from .config import PLATFORM
from .i18n import L

log = logging.getLogger(__name__)

# 固定 tag、不標 latest、原地換附檔:跟 wiki-agent 本身的版本脫鉤(與電腦版的契約,2026-11-07)
RELEASE = "https://github.com/VincentLiang1/wiki-agent/releases/download/scribe2md-core/"
INSTALL_TIMEOUT = 30 * 60      # 第一次要下載 uv、Python 與相依套件(數百 MB)
READ_TIMEOUT = 60              # 下載時每一次讀取的上限;卡住就停,不無限等
CHUNK = 1 << 20
SPACE_FACTOR = 3               # zip、解壓的暫存、裝好的 core/ 同時在磁碟上
MIN_FREE = 3 * 10**9           # zip 只有幾 MB,安裝時 uv 另外下載:venv 約 0.8 GB、Python 約 70 MB、ffmpeg 約 190 MB(電腦版 2026-11-07 實測)
INSTALLED = "SCRIBE2MD-INSTALLED"
_SHA = re.compile(r"[0-9a-f]{64}")


class CoreError(Exception):
    pass


def asset_names(platform: str = PLATFORM) -> tuple[str, str]:
    """(zip, manifest) 的檔名。"""
    p = "win" if platform == "win32" else "mac"
    return f"scribe2md-core-{p}.zip", f"scribe2md-core-{p}.json"


def _open(url: str, timeout: float):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "wiki-feeder"}), timeout=timeout)


def fetch_manifest(base: str = RELEASE, platform: str = PLATFORM) -> dict:
    """Release 上的 manifest:version、sha256、size 都要在、格式要對,否則不下載。"""
    url = base + asset_names(platform)[1]
    try:
        with _open(url, READ_TIMEOUT) as r:
            m = json.loads(r.read(1 << 16).decode("utf-8"))
    except (OSError, ValueError) as e:
        raise CoreError(L("讀不到 Scribe2MD 的版本資訊 {url}:{e}", url=url, e=e)) from e
    if not (isinstance(m, dict) and isinstance(m.get("version"), str) and isinstance(m.get("sha256"), str)
            and _SHA.fullmatch(m["sha256"]) and isinstance(m.get("size"), int) and m["size"] > 0):
        raise CoreError(L("Scribe2MD 的版本資訊格式不對:{url}", url=url))
    return m


def download(url: str, dest: Path, size: int, sha256: str, progress: Callable[[int, int], None]) -> None:
    """串流下載到 dest.part,大小與 sha256 都對才改名成 dest;不對就刪掉 .part、丟 CoreError。"""
    part = dest.with_name(dest.name + ".part")
    h, got = hashlib.sha256(), 0
    try:
        with _open(url, READ_TIMEOUT) as r, open(part, "wb") as f:
            while chunk := r.read(CHUNK):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                progress(got, size)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise CoreError(L("下載 Scribe2MD 失敗:{e}", e=e)) from e
    if got != size or h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise CoreError(L("下載的 Scribe2MD 跟版本資訊記的大小或 sha256 對不上,沒有安裝"))
    part.replace(dest)


def extract(zip_path: Path, out: Path, platform: str = PLATFORM) -> Path:
    """解壓,回傳裡面的 scribe2md-core/。Mac 用 ditto:Python 的 zipfile 不保留執行權限位元。"""
    out.mkdir(parents=True, exist_ok=True)
    try:
        if platform == "win32":
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(out)
        else:
            r = subprocess.run(["/usr/bin/ditto", "-x", "-k", str(zip_path), str(out)], capture_output=True, text=True)
            if r.returncode != 0:
                raise CoreError(L("解壓 Scribe2MD 失敗:{e}", e=(r.stderr or r.stdout).strip()[-300:]))
    except (OSError, zipfile.BadZipFile) as e:
        raise CoreError(L("解壓 Scribe2MD 失敗:{e}", e=e)) from e
    src = out / "scribe2md-core"
    if not src.is_dir():
        raise CoreError(L("Scribe2MD 的 zip 裡沒有 scribe2md-core 資料夾"))
    return src


def installer_cmd(src: Path, platform: str = PLATFORM) -> list[str]:
    """核心的非互動安裝程式;Mac 用 zsh 叫、不靠執行權限位元。"""
    if platform == "win32":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                str(src / "install.ps1"), "-Yes"]
    return ["/bin/zsh", str(src / "install.command"), "--yes"]


def run_installer(cmd: list[str], timeout: float = INSTALL_TIMEOUT) -> str:
    """執行安裝程式、把輸出原樣印給人看;離開碼 0 而且最後一行 stdout 是 `SCRIBE2MD-INSTALLED <版本>` 才算裝好,
    回傳版本。"""
    last = ""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise CoreError(L("Scribe2MD 的安裝程式無法執行:{e}", e=e)) from e
    try:
        assert p.stdout is not None
        for line in p.stdout:
            print(line, end="", flush=True)
            if line.strip():
                last = line.strip()
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        p.kill()
        raise CoreError(L("Scribe2MD 的安裝程式超過 {minutes} 分鐘沒跑完", minutes=int(timeout // 60))) from e
    if rc != 0 or not last.startswith(INSTALLED + " "):
        raise CoreError(L("Scribe2MD 的安裝程式沒有裝好(離開碼 {rc})", rc=rc))
    return last[len(INSTALLED) + 1:].strip()


def read_version(version_text: str, pyproject_text: str = "") -> str:
    """VERSION 第二行起的 `version=`;沒有就退回 pyproject.toml 的 [project] version(核心第一版的 VERSION 只有
    `<commit> <日期>` 一行,2026-11-07 驗 dist 時發現)。都沒有回空字串。"""
    lines = version_text.splitlines()
    v = next((ln.split("=", 1)[1].strip() for ln in lines[1:] if ln.startswith("version=")), "")
    if v:
        return v
    try:
        v = tomllib.loads(pyproject_text).get("project", {}).get("version", "")
    except tomllib.TOMLDecodeError:
        return ""
    return v if isinstance(v, str) else ""


def installed_version(root: Path) -> str:
    """核心自己那份(meeting-scribe/core)的版本;不是固定入口指到的那份(那可能是較新的電腦版)。"""
    def read(name: str) -> str:
        try:
            return (root / "core" / name).read_text(encoding="utf-8")
        except OSError:
            return ""
    return read_version(read("VERSION"), read("pyproject.toml"))


def _parts(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except ValueError:
        return None


def newer(a: str, b: str) -> bool:
    """語意版號 a 比 b 新;看不懂的一律當成不新(寧可不更新,不可裝回舊版)。"""
    pa, pb = _parts(a), _parts(b)
    return pa is not None and pb is not None and pa > pb


def update(cfg, target: str) -> dict:
    """背景的核心更新(自動更新開的獨立行程跑這個):全程握轉寫的鎖,不跟正在跑的 doc2md 搶 core/ 裡的檔;
    拿不到鎖回 busy(不算失敗,改天再試)。回傳要寫進結果檔的內容。"""
    from .collect import run_lock
    with run_lock(cfg.convert_lock_path) as got:
        if not got:
            return {"result": "busy", "target": target}
        try:
            info = install(cfg.doc2md_root, cfg.state_dir / "downloads", log.info)
        except CoreError as e:
            return {"result": "failed", "target": target, "detail": str(e)}
        return {"result": "ok", "target": target, "version": str(info.get("version", target))}


def install(root: Path, work: Path, say: Callable[[str], None], base: str = RELEASE,
            platform: str = PLATFORM, probe_timeout: float = 60.0) -> dict:
    """下載、驗證、安裝 Scribe2MD 核心,回傳固定入口的版本資訊;任何一步不對丟 CoreError。暫存與 zip 一律刪掉。"""
    m = fetch_manifest(base, platform)
    zip_name = asset_names(platform)[0]
    work.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(work).free
    need = max(m["size"] * SPACE_FACTOR, MIN_FREE)
    if free < need:
        raise CoreError(L("磁碟空間不夠裝 Scribe2MD:要 {need} GB,只剩 {free} GB",
                          need=f"{need / 1e9:.1f}", free=f"{free / 1e9:.1f}"))
    say(L("  下載 Scribe2MD {version}({size} MB)…", version=m["version"], size=f"{m['size'] / 1e6:.0f}"))
    shown = [-1]

    def progress(got: int, size: int) -> None:
        pct = got * 100 // size if size else 100
        if pct // 10 != shown[0]:
            shown[0] = pct // 10
            say(f"  {pct}%")

    zip_path, tmp = work / zip_name, work / "scribe2md-core-tmp"
    try:
        download(base + zip_name, zip_path, m["size"], m["sha256"], progress)
        shutil.rmtree(tmp, ignore_errors=True)
        src = extract(zip_path, tmp, platform)
        say(L("  執行 Scribe2MD 的安裝程式(第一次要下載 Python 與相依套件,可能要幾分鐘)…"))
        run_installer(installer_cmd(src, platform))
    finally:
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    info = doc2md.probe(doc2md.entry_exe(root, platform), probe_timeout)
    if info is None:
        raise CoreError(L("Scribe2MD 裝完了,但固定入口 {path} 問不出版本", path=doc2md.entry_exe(root, platform)))
    return info
