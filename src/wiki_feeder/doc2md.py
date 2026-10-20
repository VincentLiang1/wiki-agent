"""包裝 meeting-scribe 的 doc2md:分類、呼叫、讀它產出的 md。

WIKI CLAUDE.md〈二進位文件的預先轉檔〉的硬規則在這裡落地:
- 一律 `--out-dir`(否則產物留在 _待處理/ 原檔旁)
- 絕不 `--no-ocr`(掃描件會產出只有頁面圖、沒有內文的 md,之後還被當成已轉過)
- `--prune-days 0`(預設 14 天會把還沒攝入的產出清掉)
- 沒印出「執行記錄:」= 指令根本沒跑到,跟「轉檔失敗」是兩回事
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TEXT_EXTS = {".md", ".txt"}  # 本來就是文字:不轉,直接攝入
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".mp4", ".mov", ".avi"}
DOC_EXTS = {
    ".docx", ".pptx", ".xlsx", ".xlsm", ".docm", ".pptm", ".csv", ".rtf", ".html", ".htm",
    ".mht", ".mhtml", ".epub", ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp",
    ".gif", ".webp", ".heic", ".doc", ".ppt", ".xls", ".odt", ".ods", ".odp", ".vsd",
    ".vsdx", ".msg", ".eml",
}
SIDECAR_EXT = ".feeder.json"


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
        raise Doc2mdUnavailable("沒有設定 doc2md 指令", "沒有設定 doc2md 指令")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(build_args(cmd, src, out_dir), capture_output=True, text=True, timeout=timeout)
    except OSError as e:   # 找不到、沒有執行權限(例如重新安裝 meeting-scribe 到一半)
        raise Doc2mdUnavailable(f"doc2md 指令無法執行:{e}", f"指令無法執行 {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ConvertError(f"doc2md 超過 {timeout:.0f} 秒沒跑完") from e
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    m = re.search(r"執行記錄[::]\s*(\S.*)", out)
    tail = " / ".join(x for x in out.strip().splitlines()[-3:])
    if not m:
        raise Doc2mdUnavailable(f"doc2md 沒有真的執行(沒有印出「執行記錄:」):{tail}",
                                "啟動就結束、沒有印出「執行記錄:」")
    log_path = m.group(1).strip()
    # 絕對路徑的那幾行(Windows 是 C:\…,不以 / 開頭)
    mds = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip().endswith(".md") and Path(ln.strip()).is_absolute()]
    if r.returncode != 0 or not mds or not Path(mds[-1]).is_file():
        raise ConvertError(f"doc2md 轉換失敗(紀錄檔 {log_path}):{tail}", log_path)
    return Path(mds[-1]), log_path


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
