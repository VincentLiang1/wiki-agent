"""M2:轉寫與 OCR。doc2md 換成假腳本(測接線);front matter、空內文、
長段空白等計算用真的函式與真的音檔(測計算)。"""
from __future__ import annotations

import json
import os
import sys
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from wiki_feeder import silence
from wiki_feeder.collect import collect
from wiki_feeder.convert import convert
from wiki_feeder.doc2md import parse_md
from wiki_feeder.ledger import Ledger
from wiki_feeder.mover import sha256_of

FAKE = Path(__file__).with_name("fake_doc2md.py")


def _windows_ffmpeg() -> str:
    """Windows 沒有 afconvert:用這台裝的 meeting-scribe 自帶的 ffmpeg(和朋友那台同一種);找不到回空字串。"""
    from wiki_feeder.config import find_ffmpeg
    for exe in sorted(Path(__file__).resolve().parents[2].glob("meeting-scribe*/.venv/Scripts/doc2md.exe")):
        if found := find_ffmpeg(exe):
            return found
    return ""


WIN_FFMPEG = _windows_ffmpeg() if sys.platform == "win32" else ""
needs_decoder = pytest.mark.skipif(sys.platform == "win32" and not WIN_FFMPEG,
                                   reason="Windows 要 meeting-scribe 的 ffmpeg 才解得了音檔,這台沒裝")


@pytest.fixture
def ccfg(cfg, tmp_path, monkeypatch):
    args_log = tmp_path / "doc2md_args.jsonl"
    monkeypatch.setenv("FAKE_DOC2MD_ARGS", str(args_log))
    monkeypatch.delenv("FAKE_DOC2MD_MODE", raising=False)
    return replace(cfg, onedrive_inbox=None, doc2md_cmd=(sys.executable, str(FAKE)), silence_min_gap=5.0,
                   ffmpeg=WIN_FFMPEG)


def _drop(cfg, name: str, data: bytes) -> Path:
    (cfg.icloud_inbox / name).write_bytes(data)
    r = collect(cfg)
    assert r.ok, r.alerts
    return cfg.pending_dir / name


def _side(path: Path) -> dict:
    return json.loads(path.with_name(path.name + ".feeder.json").read_text(encoding="utf-8"))["轉寫"]


def _calls(cfg) -> list[list[str]]:
    """假 doc2md 被呼叫的參數(每次一行)。"""
    log = Path(os.environ["FAKE_DOC2MD_ARGS"])
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


def _wav(path: Path, segments: list[tuple[str, float]], rate: int = 16000) -> bytes:
    """segments:("tone"|"quiet", 秒數)。quiet 是 -50 dB 的底噪(真的錄音不會是數位零)。"""
    rng = np.random.default_rng(0)
    parts = []
    for kind, sec in segments:
        n = int(rate * sec)
        if kind == "tone":
            t = np.arange(n) / rate
            parts.append(0.3 * np.sin(2 * np.pi * 440 * t) + rng.normal(0, 0.003, n))
        else:
            parts.append(rng.normal(0, 0.003, n))
    x = (np.concatenate(parts) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(x.tobytes())
    return path.read_bytes()


def test_document_is_converted_with_required_flags(ccfg):
    p = _drop(ccfg, "白板.jpg", b"jpeg-bytes")

    r = convert(ccfg)

    assert r.ok and r.done == ["白板.jpg"]
    side = _side(p)
    assert side["類型"] == "文件"
    assert Path(side["md"]).parent == ccfg.md_cache
    assert "捨棄候選" not in side
    (args,) = _calls(ccfg)
    assert "--no-ocr" not in args
    assert args[args.index("--out-dir") + 1] == str(ccfg.md_cache)
    assert args[args.index("--prune-days") + 1] == "0"


def test_text_files_are_not_converted(ccfg):
    p = _drop(ccfg, "逐字稿.md", "# 會議\n內容".encode())
    convert(ccfg)
    assert _side(p)["md"] == str(p)
    assert _calls(ccfg) == []


def test_empty_ocr_becomes_discard_candidate(ccfg, monkeypatch):
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "empty")
    p = _drop(ccfg, "空白頁.pdf", b"%PDF-empty")
    convert(ccfg)
    assert "轉不出內文" in _side(p)["捨棄候選"]


def test_garbled_text_layer_is_flagged(ccfg, monkeypatch):
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "garbled")
    p = _drop(ccfg, "掃描.pdf", b"%PDF-garbled")
    convert(ccfg)
    assert "garbled_text_layer" in _side(p)["警告"]


def test_failure_retries_then_alerts_and_stops(ccfg, monkeypatch):
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "fail")
    p = _drop(ccfg, "壞檔.pdf", b"%PDF-broken")

    for i in range(ccfg.convert_max_attempts):
        r = convert(ccfg)
        assert r.failed == ["壞檔.pdf"]
    assert any("連續失敗 3 次" in a for a in r.alerts)
    with Ledger(ccfg.ledger_path) as led:
        assert "紀錄檔 /tmp/fake-doc2md.log" in led.conversion(sha256_of(p))[4]

    r = convert(ccfg)  # 已達上限:不再呼叫
    assert r.failed == [] and len(_calls(ccfg)) == ccfg.convert_max_attempts
    assert p.exists()  # 原件絕不因轉檔失敗而動到


def test_command_that_never_ran_is_reported_as_such(ccfg, monkeypatch):
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "norun")
    _drop(ccfg, "a.pdf", b"%PDF-a")
    r = convert(ccfg)
    assert any("沒有印出「執行記錄:」" in a for a in r.alerts)    # 說的是指令沒跑到,不是檔案轉壞


@pytest.mark.parametrize("broken", ["norun", "missing"])
def test_doc2md_down_skips_the_round_without_counting_against_files(ccfg, monkeypatch, broken):
    """doc2md 跑不起來是環境的問題:算在檔案上的話,三分鐘內所有待轉寫的檔都「已停止重試」、
    修好也不會自己恢復(2026-10-05 審查)。整輪略過、警示文字固定(每天寄一次,不是每分鐘)。"""
    if broken == "norun":
        monkeypatch.setenv("FAKE_DOC2MD_MODE", "norun")
        c = ccfg
    else:
        c = replace(ccfg, doc2md_cmd=(str(ccfg.state_dir / "沒有這個" / "doc2md"),))
    _drop(c, "a.pdf", b"%PDF-a")
    _drop(c, "b.pdf", b"%PDF-b")

    alerts = set()
    for _ in range(c.convert_max_attempts + 2):
        r = convert(c)
        assert r.failed == []
        alerts |= {a for a in r.alerts if "doc2md 跑不起來" in a}
    assert len(alerts) == 1
    with Ledger(c.ledger_path) as led:
        assert led._db.execute("SELECT COUNT(*) FROM conversions").fetchone()[0] == 0

    monkeypatch.delenv("FAKE_DOC2MD_MODE", raising=False)
    assert sorted(convert(ccfg).done) == ["a.pdf", "b.pdf"]       # 修好後自動繼續


def test_stuck_files_are_reminded_every_round_and_can_be_reconverted(ccfg, monkeypatch):
    """停止重試的檔只在失敗那輪報一次的話,漏看那封信就永遠卡著:之後每輪都列(去重後一天一封)。"""
    from wiki_feeder.cli import main

    monkeypatch.setenv("FAKE_DOC2MD_MODE", "fail")
    p = _drop(ccfg, "壞檔.pdf", b"%PDF-broken")
    for _ in range(ccfg.convert_max_attempts):
        convert(ccfg)
    monkeypatch.delenv("FAKE_DOC2MD_MODE")

    r = convert(ccfg)
    assert r.done == [] and any("卡在 _待處理" in a and "壞檔.pdf" in a for a in r.alerts)

    assert main(["reconvert", "壞檔.pdf"], cfg=ccfg) == 0
    r = convert(ccfg)
    assert r.done == ["壞檔.pdf"] and not any("卡在" in a for a in r.alerts)
    assert p.exists()


def test_reingest_refuses_a_file_whose_conversion_is_stuck(ccfg, monkeypatch):
    """實測(審查):reingest 對轉寫失敗的檔回報「已搬回、下一輪會用到」,其實什麼都不會發生。"""
    from wiki_feeder.config import RepoConfig
    from wiki_feeder.ingest import IngestError, reingest

    fraw = ccfg.state_dir.parent / "FRaw_Sources"
    c = replace(ccfg, repos=(RepoConfig("company", "公事庫", ccfg.state_dir.parent / "FWIKI", fraw, "me/FWIKI"),))
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "fail")
    p = _drop(c, "壞檔.pdf", b"%PDF-broken")
    for _ in range(c.convert_max_attempts):
        convert(c)
    with pytest.raises(IngestError, match="reconvert"):
        reingest(c, "壞檔.pdf", "背景")
    assert not (fraw / "_待處理").exists()
    assert p.exists()


@needs_decoder
def test_transcript_reports_long_gaps_and_unnamed_speakers(ccfg, tmp_path):
    data = _wav(tmp_path / "x.wav", [("tone", 2), ("quiet", 12), ("tone", 2)])
    p = _drop(ccfg, "2026-10-04_150000_iPhone_錄音.wav", data)

    convert(ccfg)

    side = _side(p)
    assert side["類型"] == "逐字稿"
    assert side["長度"] == "00:16"
    assert side["長段空白"] == ["第 00:02–00:14 無語音"]
    assert side["未命名講者"] == ["講者 1"]
    assert side["機器辨識講者"] == ["王小明"]


@needs_decoder
def test_continuous_recording_has_no_gaps(ccfg, tmp_path):
    data = _wav(tmp_path / "x.wav", [("tone", 4), ("quiet", 3), ("tone", 4)])  # 3 秒停頓 < 5 秒門檻
    p = _drop(ccfg, "連續.wav", data)
    convert(ccfg)
    assert _side(p)["長段空白"] == []


def test_without_scribe2md_pdf_and_images_are_read_directly(ccfg):
    """朋友版沒裝 scribe2md(使用者 2026-10-29:「scribe2md 是可以節省 TOKEN 不安裝也OK」,§4.8):PDF 與圖片記為已轉、
    md 空、sidecar 標「直接讀原件」,不呼叫 doc2md;攝入時 claude 直接讀原件。"""
    c = replace(ccfg, doc2md_cmd=())
    pdf = _drop(c, "scan.pdf", b"%PDF-1.4 x")
    jpg = _drop(c, "photo.jpg", b"\xff\xd8\xff")
    r = convert(c)
    assert r.ok and sorted(r.done) == ["photo.jpg", "scan.pdf"]
    assert _side(pdf)["md"] is None and _side(pdf)["直接讀原件"] and _side(jpg)["類型"] == "文件"
    assert _calls(c) == []
    with Ledger(c.ledger_path) as ledger:
        assert ledger.pending_conversions(c.convert_max_attempts) == []


def test_without_scribe2md_office_and_eml_are_read_directly(ccfg):
    """Office 新格式:記為已轉、sidecar 說攝入時用 office-dump(程式自己的 python-docx 等);.eml 是純文字直接讀
    (使用者 2026-10-29:「應該可以才對,只是多一點 TOKEN」)。"""
    c = replace(ccfg, doc2md_cmd=())
    docx = _drop(c, "memo.docx", b"d")
    eml = _drop(c, "mail.eml", b"Subject: x\n\nhi")
    r = convert(c)
    assert r.ok and sorted(r.done) == ["mail.eml", "memo.docx"] and _calls(c) == []
    assert "office-dump" in _side(docx)["直接讀原件"] and _side(docx)["md"] is None
    assert _side(eml)["直接讀原件"] and _side(eml)["md"] is None


def test_without_scribe2md_images_and_epub_are_converted_by_the_program(ccfg):
    """TIFF／BMP 用 Pillow 轉成 JPG 副本(Claude 的圖片輸入只收 JPEG／PNG／GIF／WebP)、EPUB 抽成純文字,都放轉寫快取、
    記成處理紀錄的 md 路徑(7 天後跟著清);EPUB 照 spine 順序。"""
    from io import BytesIO
    from zipfile import ZipFile

    from PIL import Image

    c = replace(ccfg, doc2md_cmd=())
    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "BMP")
    bmp = _drop(c, "scan.bmp", buf.getvalue())
    buf = BytesIO()
    Image.new("RGB", (8, 8), (30, 200, 30)).save(buf, "TIFF")
    tif = _drop(c, "page.tif", buf.getvalue())
    buf = BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package><manifest><item id="b" href="b.xhtml"/><item id="a" href="a.xhtml"/></manifest>'
                   '<spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
        z.writestr("OEBPS/a.xhtml", "<html><body><p>第二章 結論</p><script>x()</script></body></html>")
        z.writestr("OEBPS/b.xhtml", "<html><body><h1>第一章</h1><p>開場白</p></body></html>")
    epub = _drop(c, "book.epub", buf.getvalue())
    r = convert(c)
    assert r.ok and sorted(r.done) == ["book.epub", "page.tif", "scan.bmp"] and _calls(c) == []
    for p in (bmp, tif):
        jpg = Path(_side(p)["替代檔"])
        assert jpg.parent == c.md_cache and jpg.suffix == ".jpg" and _side(p)["md"] is None
        with Image.open(jpg) as im:
            assert im.format == "JPEG" and im.size == (8, 8)
    text = Path(_side(epub)["md"]).read_text(encoding="utf-8")
    assert text.index("第一章") < text.index("開場白") < text.index("第二章 結論") and "x()" not in text
    with Ledger(c.ledger_path) as ledger:
        assert ledger.conversion(sha256_of(bmp))[2] == _side(bmp)["替代檔"]     # 副本記成 md 路徑:7 天後清快取時一起刪
        assert ledger.pending_conversions(c.convert_max_attempts) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="HEIC 只有 Mac 用內建的 sips 轉;Windows 要 pillow-heif,使用者選不裝")
def test_without_scribe2md_heic_is_converted_with_sips_on_mac(ccfg, tmp_path):
    import subprocess

    from PIL import Image

    png = tmp_path / "x.png"
    Image.new("RGB", (8, 8), (10, 10, 200)).save(png)
    heic = tmp_path / "x.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(png), "--out", str(heic)], check=True, capture_output=True)
    c = replace(ccfg, doc2md_cmd=())
    p = _drop(c, "photo.heic", heic.read_bytes())
    assert convert(c).done == ["photo.heic"]
    with Image.open(_side(p)["替代檔"]) as im:
        assert im.format == "JPEG"
    from wiki_feeder.doc2md import handled_without_scribe2md
    assert not handled_without_scribe2md(Path("a.heic"), platform="win32")     # Windows 沒有 sips:留著提醒


def test_without_scribe2md_audio_and_old_office_wait_without_counting_as_failures(ccfg):
    """錄音、舊版 .doc、Outlook .msg 留在待處理:不記處理紀錄、不扣重試次數(跑滿 convert_max_attempts 輪也不會
    「已停止重試」),每輪同一則固定警示;裝好 scribe2md 的下一輪照常轉,沒有要解除的狀態。"""
    c = replace(ccfg, doc2md_cmd=())
    _drop(c, "talk.m4a", b"a")
    _drop(c, "memo.doc", b"d")
    first = convert(c)
    assert first.failed == [] and first.done == [] and len(first.alerts) == 1 and "scribe2md" in first.alerts[0]
    assert "memo.doc" in first.alerts[0] and "talk.m4a" in first.alerts[0]
    for _ in range(c.convert_max_attempts):
        assert convert(c).alerts == first.alerts                 # 每輪同一句,全文去重後一天一封
    with Ledger(c.ledger_path) as ledger:
        assert {Path(d).name for _, d in ledger.pending_conversions(c.convert_max_attempts)} == {"memo.doc", "talk.m4a"}
        assert ledger.stuck_conversions(c.convert_max_attempts) == []
    r = convert(ccfg)                                             # 裝好 scribe2md、重跑安裝把路徑寫進設定檔之後
    assert r.ok and sorted(r.done) == ["memo.doc", "talk.m4a"] and len(_calls(ccfg)) == 2


def test_sidecars_skipped_unsupported_flagged(ccfg):
    _drop(ccfg, "t_錄音.json", b'{"x": 1}')
    p = _drop(ccfg, "奇怪.xyz", b"???")

    r = convert(ccfg)

    assert sorted(r.skipped) == ["t_錄音.json", "奇怪.xyz"]
    assert "不支援" in _side(p)["捨棄候選"]
    assert _calls(ccfg) == []


def test_items_no_longer_in_pending_are_ignored(ccfg):
    p = _drop(ccfg, "a.jpg", b"jpg")
    p.rename(p.with_name("moved.jpg"))  # M3 搬走了
    r = convert(ccfg)
    assert r.done == [] and _calls(ccfg) == []


def test_photo_and_voice_note_are_paired(ccfg):
    _drop(ccfg, "2026-10-04_143005_iPhone_照片.jpg", b"jpg")
    p = _drop(ccfg, "2026-10-04_143005_iPhone_註記.md", "語音註記".encode())
    convert(ccfg)
    assert _side(p)["配對"] == ["2026-10-04_143005_iPhone_照片.jpg"]


def test_converted_items_are_not_converted_again(ccfg):
    _drop(ccfg, "a.jpg", b"jpg")
    convert(ccfg)
    convert(ccfg)
    assert len(_calls(ccfg)) == 1


def test_silence_analysis_failure_does_not_fail_transcript(ccfg, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("afconvert 解不開 a.mov")

    monkeypatch.setattr(silence, "analyze", boom)
    p = _drop(ccfg, "會議.mov", b"not-really-a-mov")

    r = convert(ccfg)

    assert r.done == ["會議.mov"] and r.ok
    side = _side(p)
    assert side["長段空白"] is None and "無法分析" in side["警告"]
    assert side["未命名講者"] == ["講者 1"]


# --- 純計算 -------------------------------------------------------------------

def test_gap_threshold_is_relative_to_noise_floor():
    """底噪 -40 dB 的錄音(吵雜會議室):固定 -50 dB 門檻會一段都抓不到,相對門檻抓得到。"""
    db = np.array([-40.0] * 20 + [-15.0] * 10 + [-41.0] * 200 + [-15.0] * 10)
    gaps = silence.find_gaps(db, window=1.0, margin_db=10.0, min_gap=180.0)
    assert gaps == [(30.0, 230.0)]


def test_mostly_speech_with_short_break_is_not_all_silence():
    """回歸:安靜只佔 4%(2 小時會議中場 5 分鐘)時,百分位法會把整場判成無語音。"""
    rng = np.random.default_rng(1)
    speech = rng.normal(-20, 3, 7200)
    speech[2820:3120] = rng.normal(-55, 1, 300)
    assert silence.find_gaps(speech, 1.0, 10.0, 180.0) == [(2820.0, 3120.0)]


def test_forgotten_recorder_long_silence_after_short_meeting():
    """30 分鐘會議後忘了按停、又錄了 2.5 小時空白:講話是少數也要抓得到。"""
    rng = np.random.default_rng(2)
    db = np.concatenate([rng.normal(-20, 3, 1800), rng.normal(-58, 1, 9000)])
    assert silence.find_gaps(db, 1.0, 10.0, 180.0) == [(1800.0, 10800.0)]


def test_quiet_speaker_talking_for_minutes_is_not_silence():
    """離手機遠的人連續講 5 分鐘(比其他人小聲約 10 dB):是講話、不是空白。"""
    rng = np.random.default_rng(3)
    blocks = [rng.normal(-20 if i % 2 == 0 else -30, 2, 300) for i in range(12)]
    assert silence.find_gaps(np.concatenate(blocks), 1.0, 15.0, 180.0) == []


def test_fmt_time_handles_hours():
    assert silence.describe([(2820, 3120), (3700, 3725)]) == ["第 47:00–52:00 無語音", "第 1:01:40–1:02:05 無語音"]


def test_parse_md_counts_only_real_text(tmp_path):
    md = tmp_path / "a.md"
    md.write_text(
        "---\nlossy_kinds: [scanned_page, ocr]\nocr_used: true\n---\n\n# 標題\n\n"
        "〔本文件共 1 頁,其中 1 頁抽不出文字層,已改用整頁文字辨識(OCR)〕\n\n## 第 1 頁\n\n"
        "![第 1 頁](a.assets/img-0001.png)\n\n〔以下文字由第 1 頁的整頁影像辨識而來,可能有誤〕\n\n八個字的內文在這\n",
        encoding="utf-8",
    )
    info = parse_md(md)
    assert info.lossy_kinds == ["scanned_page", "ocr"]
    assert info.front["ocr_used"] is True
    assert info.body_chars == 8


def test_transcript_with_only_speaker_headers_is_empty(tmp_path):
    """只有講者標頭、沒有任何一句話(含機器辨識出名字的標頭)→ 0 字。"""
    md = tmp_path / "a.md"
    md.write_text(
        "---\nlossy_kinds: []\n---\n\n# 錄音\n\n**講者 1** (00:00:00)\n\n**王小明**〔機器辨識〕 (00:00:14)\n\n"
        "## 講者辨識診斷\n\n| 講者 | 發言輪次 | 總時長 | 群內一致性 | 名字來源 |\n",
        encoding="utf-8",
    )
    assert parse_md(md).body_chars == 0



def test_stopped_retrying_alerts_follow_the_interface_language(ccfg, monkeypatch):
    """朋友選英文:停止重試的警示(進摘要信)是英文;英文不可被 network_down 當成斷網吞掉(逾時的說法不寫 timed out)。"""
    import re

    from wiki_feeder import i18n
    from wiki_feeder.collect import network_down

    i18n.set_lang("en")
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "fail")
    _drop(ccfg, "bad.pdf", b"%PDF-broken")
    for _ in range(ccfg.convert_max_attempts):
        r = convert(ccfg)
    stopped = [a for a in r.alerts if a.startswith("bad.pdf")]
    assert len(stopped) == 1 and "reconvert bad.pdf" in stopped[0]
    assert not re.search(r"[㐀-鿿]", stopped[0].split(":")[0])
    assert "已停止重試" not in stopped[0] and not network_down(stopped[0])
    stuck = [a for a in r.alerts if "_待處理" in a]
    assert len(stuck) == 1 and "卡在" not in stuck[0] and "bad.pdf" in stuck[0]
    assert not re.search(r"[㐀-鿿]", stuck[0].replace("_待處理", ""))


def test_timeouts_in_english_are_not_mistaken_for_network_down():
    """doc2md、run_net 的逾時是要人看的問題:譯文寫成 timed out 的話,會被當成斷網、不列進摘要。"""
    from wiki_feeder import i18n
    from wiki_feeder.collect import network_down

    for lang in i18n.LANGS:
        assert not network_down(i18n.L("doc2md 超過 {seconds} 秒沒跑完", lang, seconds="3600"))
        assert not network_down(i18n.L("{cmd} 逾時 {seconds} 秒,已中止", lang, cmd="git push", seconds="300"))
