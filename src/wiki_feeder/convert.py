"""第二步:_待處理/ 裡已取到的檔 → 轉寫／OCR → 結果寫回 <檔名>.feeder.json 的「轉寫」欄。

- 錄音、影片 → doc2md 逐字稿 + 長段空白偵測
- 照片、掃描 PDF、Office → doc2md(含 OCR)
- .md／.txt → 不轉(本來就是文字)
- 捷徑寫的 .json sidecar、程式補的 .feeder.json → 略過
- 轉不出內文 → 標「捨棄候選」,不默默丟掉;失敗重試 N 輪後發警示

只轉 dest_path 還在 _待處理/ 的項目:M3 搬走之後的舊紀錄自然不再出現。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import zipfile
from html.parser import HTMLParser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import doc2md, silence
from .office import DUMPERS
from .collect import _alert, _streak, heartbeat, run_lock
from .config import Config
from .i18n import L
from .ledger import Ledger

log = logging.getLogger(__name__)

MIN_BODY_CHARS = 5  # 少於這個字數視為「轉不出內文」
_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{6})_")


@dataclass
class ConvertReport:
    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    new_alerts: list[str] = field(default_factory=list)
    needs_scribe2md: list[str] = field(default_factory=list)   # 沒裝 scribe2md、claude 讀不了的檔(§4.8)
    locked: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed and not self.alerts


def convert(cfg: Config) -> ConvertReport:
    report = ConvertReport()
    with run_lock(cfg.convert_lock_path) as got:
        if not got:
            log.info(L("另一個 convert 正在執行,這次直接結束"))
            report.locked = True
            return report
        with Ledger(cfg.ledger_path) as ledger:
            try:
                for sha, dest in ledger.pending_conversions(cfg.convert_max_attempts):
                    path = Path(dest)
                    if path.exists():
                        heartbeat(cfg.convert_lock_path)
                        _convert_one(cfg, ledger, sha, path, report)
            except doc2md.Doc2mdUnavailable as e:
                _doc2md_down(cfg, e, report)
            else:
                _streak(cfg, "doc2md", reset=True)
            _remind_stuck(cfg, ledger, report)
            _remind_needs_scribe2md(cfg, report)
    report.new_alerts = [m for m in report.alerts if _alert(cfg, m)]
    return report


def _convert_one(cfg: Config, ledger: Ledger, sha: str, path: Path, report: ConvertReport) -> None:
    kind = doc2md.classify(path)
    if kind in ("ours", "sidecar"):
        ledger.conversion_done(sha, kind, "skipped", None)
        report.skipped.append(path.name)
        return
    if kind in ("transcript", "document") and not cfg.doc2md_cmd \
            and not doc2md.handled_without_scribe2md(path):
        # 沒裝 scribe2md(朋友版選裝,§4.8):錄音、影片、舊版 Office、.msg 這些處理不了的留在待處理、每輪提醒;
        # 不記處理紀錄、不算失敗、不扣重試次數,裝好 scribe2md 的下一輪就照常轉
        report.needs_scribe2md.append(path.name)
        return
    try:
        result = _result_for(cfg, kind, path)
        _update_sidecar(path, result)
    except doc2md.Doc2mdUnavailable:
        raise   # 環境壞了:整輪略過,不算這個檔的失敗
    except Exception as e:  # noqa: BLE001 —— 任何失敗:記錄、下一輪重試
        log_path = getattr(e, "log_path", None)
        n = ledger.conversion_failed(sha, kind, str(e), log_path)
        log.error(L("%s 轉檔失敗(第 %d 次):%s"), path.name, n, e)
        report.failed.append(path.name)
        if n >= cfg.convert_max_attempts:
            report.alerts.append(L("{name} 轉檔連續失敗 {n} 次,已停止重試:{e}。"
                                   "查明原因後用 `uv run wiki-feeder reconvert {name}` 救回", name=path.name, n=n, e=e))
        return
    status = "done" if kind != "unsupported" else "skipped"
    ledger.conversion_done(sha, kind, status, result.get("md") or result.get("替代檔"))   # 替代檔也在快取,7 天後一起清
    (report.done if status == "done" else report.skipped).append(path.name)
    log.info("%s → %s", path.name, result.get("md") or result["類型"])


def _doc2md_down(cfg: Config, e: doc2md.Doc2mdUnavailable, report: ConvertReport) -> None:
    """doc2md 跑不起來:這輪不轉、不扣任何檔的次數。連續幾輪才警示(重新安裝 meeting-scribe 的那一分鐘
    也會碰到,不必每次都寄信);警示文字固定,卡著的期間每天寄一次。"""
    n = _streak(cfg, "doc2md")
    log.warning(L("%s(連續第 %d 輪,這輪不轉寫)"), e, n)
    if n >= cfg.unavailable_alert_after:
        report.alerts.append(L("doc2md 跑不起來({reason}),轉寫暫停中:待轉寫的檔不算失敗,修好後下一輪自動繼續。"
                               "確認 {cmd} 能執行", reason=e.reason, cmd=cfg.doc2md_cmd[0] if cfg.doc2md_cmd else "doc2md"))


def _remind_needs_scribe2md(cfg: Config, report: ConvertReport) -> None:
    """沒裝 scribe2md 時 claude 讀不了的檔:每輪列進警示(文字固定、全文去重、一天一封),裝好後下一輪自動處理,
    沒有要解除的狀態。跟 §4.5「doc2md 跑不起來」不同:那是裝了但壞了,這是正常狀態,第一輪就提醒。"""
    if report.needs_scribe2md:
        report.alerts.append(L("有 {n} 個檔要裝 scribe2md 才會處理(錄音、影片、舊版 .doc／.xls／.ppt、Outlook .msg 等),"
                               "先留在 {dir}/:{names}。裝好之後不必做任何事,下一輪自動轉寫",
                               n=len(report.needs_scribe2md), dir=cfg.pending_dir.name,
                               names=L("、").join(sorted(report.needs_scribe2md)[:10])))


def _remind_stuck(cfg: Config, ledger: Ledger, report: ConvertReport) -> None:
    """已停止重試、還卡在收件落點(_待處理/、朋友版的收件區)的檔:每輪都列(警示以全文去重,清單不變就一天寄一次信)。
    只在失敗那一輪報一次的話,漏看那封信,檔案就永遠卡著沒人知道。"""
    stuck = [Path(d).name for _, d, _ in ledger.stuck_conversions(cfg.convert_max_attempts) if Path(d).exists()]
    if stuck:
        report.alerts.append(L("有 {n} 個檔轉寫已停止重試,卡在 {dir}/:{names}。"
                               "查明原因後用 `uv run wiki-feeder reconvert <檔名>`(或 `--all`)救回",
                               n=len(stuck), dir=cfg.pending_dir.name, names=L("、").join(sorted(stuck)[:10])))


def reconvert(cfg: Config, name: str | None) -> str:
    """把已停止重試的轉寫重新排入(name=None 表示全部);次數歸零,下一輪再試滿 convert_max_attempts 次。"""
    with Ledger(cfg.ledger_path) as ledger:
        stuck = ledger.stuck_conversions(cfg.convert_max_attempts)
        if name is not None:
            stuck = [s for s in stuck if Path(s[1]).name == name]
        if not stuck:
            return L("沒有叫 {name} 的已停止重試的轉寫檔", name=name) if name else L("沒有已停止重試的轉寫檔")
        for sha, _, _ in stuck:
            ledger.conversion_reset(sha)
    names = L("、").join(Path(d).name for _, d, _ in stuck)
    return L("已重新排入轉寫:{names};下一輪(約一分鐘內)開始,再失敗 {n} 次才會停", names=names,
             n=cfg.convert_max_attempts)


def _result_for(cfg: Config, kind: str, path: Path) -> dict:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    base = {"類型": {"text": "文字", "transcript": "逐字稿", "document": "文件", "unsupported": "不支援"}[kind],
            "轉寫時間": now, "配對": _pairs(path)}
    if kind == "text":
        return {**base, "md": str(path)}
    if kind == "unsupported":
        return {**base, "md": None, "捨棄候選": f"doc2md 不支援 {path.suffix or '無副檔名'} 格式,請人工處理"}
    if not cfg.doc2md_cmd:
        return _without_scribe2md(cfg, path, base)

    md, log_path = doc2md.run(cfg.doc2md_cmd, path, cfg.md_cache, cfg.doc2md_timeout)
    info = doc2md.parse_md(md)
    out = {**base, "md": str(md), "doc2md紀錄": log_path,
           "lossy_kinds": info.lossy_kinds, "ocr_used": info.front.get("ocr_used")}
    if "garbled_text_layer" in info.lossy_kinds:
        out["警告"] = "PDF 文字層是亂碼(garbled_text_layer),內容可能不可靠;必要時用 --force-ocr 重轉"
    if info.body_chars < MIN_BODY_CHARS:
        out["捨棄候選"] = "轉不出內文(OCR 或語音辨識沒有文字)"
    if kind == "transcript":
        # 長段空白只是摘要裡的提示:量不出來(例如 afconvert 開不了影片檔)不可連累已轉好的逐字稿
        try:
            duration, gaps = silence.analyze(path, cfg.silence_window, cfg.silence_margin_db, cfg.silence_min_gap,
                                             cfg.ffmpeg)
            out["長度"] = silence.fmt_time(duration)
            out["長段空白"] = silence.describe(gaps)
        except Exception as e:  # noqa: BLE001
            log.warning(L("%s 無法分析長段空白:%s"), path.name, e)
            out["長段空白"] = None
            out["警告"] = f"無法分析音訊的長段空白:{e}"
        out["未命名講者"] = info.unnamed_speakers
        out["機器辨識講者"] = info.machine_named
    return out


def _without_scribe2md(cfg: Config, path: Path, base: dict) -> dict:
    """沒裝 scribe2md(§4.8):只有 handled_without_scribe2md 的檔走到這裡(其餘在 _convert_one 留著)。
    sidecar 的「直接讀原件」告訴攝入提示怎麼讀;轉出來的副本放轉寫快取(記成處理紀錄的 md 路徑,7 天後清)。"""
    ext = path.suffix.lower()
    if ext in DUMPERS:
        return {**base, "md": None, "直接讀原件": "沒裝 scribe2md,攝入時用 office-dump 讀(文件裡的圖讀不到)"}
    if ext in doc2md.IMAGE_CONVERT_EXTS or ext in doc2md.HEIC_EXTS:
        jpg = _to_jpeg(path, cfg.md_cache)
        return {**base, "md": None, "替代檔": str(jpg), "直接讀原件": "沒裝 scribe2md,原件是 Claude 讀不了的圖片格式,已轉成 JPG 副本"}
    if ext in doc2md.EPUB_EXTS:
        md = _epub_text(path, cfg.md_cache)
        out = {**base, "md": str(md), "直接讀原件": "沒裝 scribe2md,EPUB 由 wiki-feeder 抽成純文字"}
        if doc2md.parse_md(md).body_chars < MIN_BODY_CHARS:
            out["捨棄候選"] = "轉不出內文(EPUB 裡沒有文字)"
        return out
    return {**base, "md": None, "直接讀原件": "沒裝 scribe2md,攝入時直接讀原件"}


def _to_jpeg(src: Path, cache: Path) -> Path:
    """TIFF／BMP 用 Pillow 轉 JPG(多頁 TIFF 只取第一頁);HEIC 用 Mac 內建的 sips(Pillow 沒裝 pillow-heif 讀不了)。
    轉不了就是這個檔的問題:照一般失敗重試、達上限才警示。"""
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (src.name + ".jpg")
    if src.suffix.lower() in doc2md.HEIC_EXTS:
        r = subprocess.run(["sips", "-s", "format", "jpeg", str(src), "--out", str(out)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not out.is_file():
            raise doc2md.ConvertError(f"sips 轉不了 HEIC:{(r.stderr or r.stdout).strip()[-200:]}")
        return out
    from PIL import Image
    with Image.open(src) as im:
        im.convert("RGB").save(out, "JPEG", quality=85)
    return out


EPUB_MAX_BYTES = 50_000_000   # 解開後的 XHTML 總量上限:EPUB 是不可信的輸入,不讓壓縮炸彈吃光磁碟


class _TextOnly(HTMLParser):
    """XHTML → 純文字:略過 script／style,區塊標籤換行。"""
    BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "section", "article", "blockquote", "pre", "hr"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_text(html: str) -> str:
    p = _TextOnly()
    p.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(p.parts)).strip()


def _epub_order(z: zipfile.ZipFile, names: list[str]) -> list[str]:
    """照 OPF 的 spine 排章節;讀不到 OPF 就照檔名。"""
    try:
        opf_name = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode("utf-8", "replace")).group(1)
        opf = z.read(opf_name).decode("utf-8", "replace")
    except (KeyError, AttributeError, zipfile.BadZipFile):
        return sorted(names)
    base = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
    hrefs = {m.group(1): m.group(2) for m in re.finditer(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf)}
    hrefs.update({m.group(2): m.group(1) for m in re.finditer(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
    ordered = [base + hrefs[i] for i in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf) if i in hrefs]
    ordered = [n for n in ordered if n in names]
    return ordered + sorted(n for n in names if n not in ordered)


def _epub_text(src: Path, cache: Path) -> Path:
    """EPUB 是壓縮的 XHTML:照 spine 順序抽純文字,寫成 md 放轉寫快取。"""
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (src.name + ".md")
    parts = []
    with zipfile.ZipFile(src) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        if sum(z.getinfo(n).file_size for n in names) > EPUB_MAX_BYTES:
            raise doc2md.ConvertError(f"EPUB 解開後超過 {EPUB_MAX_BYTES} bytes,不抽")
        for n in _epub_order(z, names):
            parts.append(_html_text(z.read(n).decode("utf-8", "replace")))
    out.write_text(f"# {src.stem}\n\n" + "\n\n".join(p for p in parts if p) + "\n", encoding="utf-8")
    return out


def _pairs(path: Path) -> list[str]:
    """同一個時間戳開頭的其他檔(照片＋語音註記、掃描＋補 sidecar),留給 M3 合併。"""
    m = _TS.match(path.name)
    if not m:
        return []
    return sorted(
        p.name for p in path.parent.iterdir()
        if p != path and p.name.startswith(m.group(1) + "_") and not p.name.endswith(doc2md.SIDECAR_EXT)
        and not p.name.startswith(".")
    )


def _update_sidecar(path: Path, result: dict) -> None:
    side = path.with_name(path.name + doc2md.SIDECAR_EXT)
    data = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    data["轉寫"] = result
    tmp = side.with_name(f".{side.name}.partial")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(side)       # 不用 rename:Windows 的 rename 目標已存在就失敗(POSIX 兩者相同)
