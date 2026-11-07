"""包裝 meeting-scribe 的 doc2md:分類、呼叫、讀它產出的 md。

WIKI CLAUDE.md〈二進位文件的預先轉檔〉的硬規則在這裡落地:
- 一律 `--out-dir`(否則產物留在 _待處理/ 原檔旁)
- 絕不 `--no-ocr`(掃描件會產出只有頁面圖、沒有內文的 md,之後還被當成已轉過)
- `--prune-days 0`(預設 14 天會把還沒攝入的產出清掉)
- 沒印出「執行記錄:」= 指令根本沒跑到,跟「轉檔失敗」是兩回事

Scribe2MD 核心的固定入口(spec §4.9):`entry_exe`、`probe`、`relink`。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import PLATFORM
from .i18n import L
from .office import DUMPERS as OFFICE_DUMP_EXTS

log = logging.getLogger(__name__)

TEXT_EXTS = {".md", ".txt"}  # 本來就是文字:不轉,直接攝入
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".mp4", ".mov", ".avi"}
DOC_EXTS = {
    ".docx", ".pptx", ".xlsx", ".xlsm", ".docm", ".pptm", ".csv", ".rtf", ".html", ".htm",
    ".mht", ".mhtml", ".epub", ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".gif", ".webp", ".heic", ".doc", ".ppt", ".xls", ".odt", ".ods", ".odp", ".vsd",
    ".vsdx", ".msg", ".eml",
}
SIDECAR_EXT = ".feeder.json"
# 沒裝 scribe2md(朋友版選裝,spec §4.8)時不靠它也能處理的格式(使用者 2026-10-29:「應該可以才對,只是多一點 TOKEN」):
# - 攝入的 claude 直接讀:PDF、一般圖片(Claude Code 的 Read 讀得了)、本來就是文字的 CSV／HTML、.eml(MIME 純文字)
# - Office 新格式(OFFICE_DUMP_EXTS):攝入時用 office-dump(程式自己的 python-docx／openpyxl／python-pptx)讀,少的只有文件裡的圖
# - TIFF／BMP:Claude 的圖片輸入只收 JPEG／PNG／GIF／WebP,程式用 Pillow 轉成 JPG 副本;HEIC 在 Mac 用系統的 sips 轉,
#   Windows 要 pillow-heif(使用者 2026-10-29 選不裝)
# - EPUB:壓縮的 XHTML,程式解開抽純文字
# 其餘(錄音、影片、舊版 .doc／.xls／.ppt、Outlook .msg)要等裝了 scribe2md 才處理
DIRECT_READ_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".csv", ".html", ".htm", ".eml"}
IMAGE_CONVERT_EXTS = {".tif", ".tiff", ".bmp"}
HEIC_EXTS = {".heic"}
EPUB_EXTS = {".epub"}


def handled_without_scribe2md(path: Path, platform: str = PLATFORM) -> bool:
    """沒裝 scribe2md 時這個檔能不能處理(上面四類;HEIC 只有 Mac)。錄音、影片一律不能:Claude 沒有聽覺。"""
    ext = path.suffix.lower()
    return (ext in DIRECT_READ_EXTS or ext in OFFICE_DUMP_EXTS or ext in IMAGE_CONVERT_EXTS or ext in EPUB_EXTS
            or (ext in HEIC_EXTS and platform == "darwin"))


class ConvertError(Exception):
    def __init__(self, msg: str, log_path: str | None = None):
        super().__init__(msg)
        self.log_path = log_path


class Doc2mdUnavailable(ConvertError):
    """doc2md 本身跑不起來(環境壞了,不是這個檔的問題):整輪略過、不算在檔案的重試次數上。

    算在檔案上的話,每分鐘一輪、三輪之內所有待轉寫的檔都會「已停止重試」,環境修好也不會自己恢復。
    `reason` 是不含變動內容的短句,當警示用(警示以全文去重,每輪都不同就會每分鐘寄一封信)。"""

    def __init__(self, msg: str, reason: str):
        super().__init__(msg)
        self.reason = reason


def classify(path: Path) -> str:
    """'ours'(程式補的 sidecar)/'sidecar'(捷徑寫的 .json)/'text'/'transcript'/'document'/'unsupported'"""
    name = path.name.lower()
    if name.endswith(SIDECAR_EXT):
        return "ours"
    ext = path.suffix.lower()
    if ext == ".json":
        return "sidecar"
    if ext in TEXT_EXTS:
        return "text"
    if ext in AUDIO_EXTS:
        return "transcript"
    if ext in DOC_EXTS:
        return "document"
    return "unsupported"


def build_args(cmd: tuple[str, ...], src: Path, out_dir: Path) -> list[str]:
    return [*cmd, str(src), "--out-dir", str(out_dir), "--prune-days", "0"]


def run(cmd: tuple[str, ...], src: Path, out_dir: Path, timeout: float) -> tuple[Path, str]:
    """轉一個檔,回傳 (md 路徑, 紀錄檔路徑)。"""
    if not cmd:
        raise Doc2mdUnavailable(L("沒有設定 doc2md 指令"), L("沒有設定 doc2md 指令"))
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(build_args(cmd, src, out_dir), capture_output=True, text=True, timeout=timeout)
    except OSError as e:   # 找不到、沒有執行權限(例如重新安裝 meeting-scribe 到一半)
        raise Doc2mdUnavailable(L("doc2md 指令無法執行:{e}", e=e), L("指令無法執行 {cmd}", cmd=cmd[0])) from e
    except subprocess.TimeoutExpired as e:
        raise ConvertError(L("doc2md 超過 {seconds} 秒沒跑完", seconds=f"{timeout:.0f}")) from e
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    # 新版核心另印語言無關的標記(stderr);舊版只有中文那行,兩種都認、標記優先(§4.9)
    m = LOG_MARKER.search(out) or LEGACY_LOG.search(out)
    tail = " / ".join(x for x in out.strip().splitlines()[-3:])
    if not m:
        raise Doc2mdUnavailable(L("doc2md 沒有真的執行(沒有印出「執行記錄:」):{tail}", tail=tail),
                                L("啟動就結束、沒有印出「執行記錄:」"))
    log_path = m.group(1).strip()
    # 絕對路徑的那幾行(Windows 是 C:\…,不以 / 開頭)
    mds = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip().endswith(".md") and Path(ln.strip()).is_absolute()]
    if r.returncode != 0 or not mds or not Path(mds[-1]).is_file():
        raise ConvertError(L("doc2md 轉換失敗(紀錄檔 {log}):{tail}", log=log_path, tail=tail), log_path)
    return Path(mds[-1]), log_path


# --- Scribe2MD 核心的固定入口(spec §4.9;與電腦版 meeting-scribe-native 的契約,2026-11-07) ---
# <root>/bin 是連結(Mac symlink、Windows junction),指向核心或電腦版裡較新那份的 venv 執行檔資料夾,
# 由兩邊的安裝／更新／電腦版啟動時重指;<root>/current.json(不放 bin/:那是連結,寫進去等於寫進某一份 venv)記同一個選擇,junction 出狀況時的退路。
ENTRY_CONTRACT = 1
LOG_MARKER = re.compile(r"SCRIBE2MD-LOG:[ \t]*(\S.*)")
LEGACY_LOG = re.compile(r"執行記錄[::][ \t]*(\S.*)")


def entry_exe(root: Path, platform: str = PLATFORM) -> Path:
    """固定入口:Windows 是真的 .exe(不經 cmd.exe:檔名來自收件匣,`&` `%` 會被解讀成指令)。"""
    return root / "bin" / ("doc2md.exe" if platform == "win32" else "doc2md")


def relink_cmd(root: Path, platform: str = PLATFORM) -> list[str]:
    """核心自己的重指指令:只重比版本、重建 bin 與 current.json,不下載、不重裝。
    Mac 用 zsh 叫、不靠執行權限位元。"""
    if platform == "win32":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                str(root / "core" / "install.ps1"), "-Relink"]
    return ["/bin/zsh", str(root / "core" / "install.command"), "--relink"]


def current_exe(root: Path) -> Path | None:
    """<root>/current.json 記的那顆 doc2md;讀不到、不是絕對路徑就回 None。"""
    try:
        v = json.loads((root / "current.json").read_text(encoding="utf-8")).get("doc2md")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(v) if isinstance(v, str) and Path(v).is_absolute() else None


def probe(exe: Path, timeout: float) -> dict | None:
    """`<exe> --version --json`:離開碼 0、最後一行是 JSON、`entry_contract` 是不小於 ENTRY_CONTRACT 的整數,
    才算新版核心;其他一律 None(舊版是 argparse 報錯、離開碼 2,不會把參數當檔名去轉)。"""
    if not exe.is_file():
        return None
    try:
        r = subprocess.run([str(exe), "--version", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(L("doc2md 的版本查不到(%s):%s"), exe, e)
        return None
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    if r.returncode != 0 or not lines:
        return None
    try:
        info = json.loads(lines[-1])
    except ValueError:
        return None
    contract = info.get("entry_contract") if isinstance(info, dict) else None
    if not isinstance(contract, int) or isinstance(contract, bool) or contract < ENTRY_CONTRACT:
        return None
    return info


def tool_path(info: dict, key: str) -> str:
    """版本資訊裡 ffmpeg／libreoffice 的路徑:要是存在的檔才算,其他回空字串。"""
    v = info.get(key)
    return v if isinstance(v, str) and v and Path(v).is_file() else ""


def relink(root: Path, timeout: float) -> bool:
    """叫核心 `--relink` 重指一次;回傳離開碼是不是 0。"""
    cmd = relink_cmd(root)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(L("Scribe2MD 的固定入口重指失敗:%s"), e)
        return False
    if r.returncode != 0:
        log.warning(L("Scribe2MD 的固定入口重指失敗(離開碼 %d):%s"), r.returncode,
                    " / ".join((r.stderr or r.stdout or "").strip().splitlines()[-3:]))
    return r.returncode == 0


@dataclass
class MdInfo:
    front: dict = field(default_factory=dict)
    body_chars: int = 0          # 扣掉標題、圖片、工具註記、診斷段之後的實際內文字數
    unnamed_speakers: list[str] = field(default_factory=list)
    machine_named: list[str] = field(default_factory=list)

    @property
    def lossy_kinds(self) -> list[str]:
        v = self.front.get("lossy_kinds", [])
        return v if isinstance(v, list) else []


def _parse_value(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip('"') for x in v[1:-1].split(",") if x.strip()]
    if v in ("true", "false"):
        return v == "true"
    return v.strip('"')


def parse_md(path: Path) -> MdInfo:
    text = path.read_text(encoding="utf-8", errors="replace")
    info = MdInfo()
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    info.front[k.strip()] = _parse_value(v)
            body = text[end + 4:]
    diag_at = body.find("## 講者辨識診斷")
    diag = body[diag_at:] if diag_at != -1 else ""
    content = body[:diag_at] if diag_at != -1 else body
    kept = []
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("![") or (s.startswith("〔") and s.endswith("〕")):
            continue
        s = re.sub(r"^\*\*[^*]+\*\*(〔[^〕]*〕)?\s*\(\d+:\d+:\d+\)", "", s)  # 講者標頭(含機器辨識的名字)
        kept.append(s)
    info.body_chars = len(re.sub(r"\s", "", "".join(kept)))
    for row in re.findall(r"^\|\s*([^|]+?)\s*\|.*\|\s*([^|]+?)\s*\|\s*$", diag, flags=re.M):
        speaker, source = row
        if source == "未命名":
            info.unnamed_speakers.append(speaker)
        elif source == "機器辨識":
            info.machine_named.append(speaker)
    return info
