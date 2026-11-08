"""三平台共用的逐字稿約定(iPhone、Android、電腦版產出的 md),wiki-feeder 每一種寫法都要讀得懂(spec §4.2)。

實際會進 parse_md 的只有本機 doc2md(Scribe2MD 核心)轉錄音的產出(App 交來的 .md 是「文字」、不經 parse_md);
暫停行、重點說明行、機器辨識的名字來源批次轉錄不會寫,照約定一併認得、以防日後改走這裡。
樣本由 scribe2md-ios 的 ContractSamplesTests 從 iOS 程式產生(`Tests/Resources/contract_samples.json`),
約定一漂移這裡就紅;**不要改那個 json**,約定要改先改 iPhone 那邊(交代格式見 iPhone repo 的 docs/跨平台交代範本.md)。
**跑之前先 `git -C ~/SOURCE5/iOS/scribe2md-ios pull --ff-only`**:不 pull 比對的是舊樣本,太舊的版本沒有樣本檔、整個檔會被跳過。
測試本身不 pull(測試絕不碰真實 repo、也不連網,spec §8.1)。
wiki-feeder 沒有「還沒命名(Untitled-／未命名-)」的判斷,所以 json 的 `untitled` 段不比對。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wiki_feeder import doc2md


def _real_home() -> Path | None:
    # 用帳號資料找真的家目錄,不看 HOME(conftest 的假 HOME 在收集之後才換上,這裡不靠那個時序;
    # 從發佈副本、修理用的 clone 跑也找得到同一份)。只讀這一個 json,不碰收件匣與 repo
    if sys.platform == "win32":
        return None
    import os
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


_HOME = _real_home()
SAMPLES = (_HOME / "SOURCE5" / "iOS" / "scribe2md-ios" / "Tests" / "Resources" / "contract_samples.json"
           if _HOME else None)

pytestmark = pytest.mark.skipif(
    SAMPLES is None or not SAMPLES.is_file(),
    reason="這台沒有 iPhone repo 的約定樣本(~/SOURCE5/iOS/scribe2md-ios/Tests/Resources/contract_samples.json):"
           "只有維護者的 Mac 驗得了;朋友版、Windows 一律跳過")


@pytest.fixture(scope="module")
def samples() -> dict:
    return json.loads(SAMPLES.read_text(encoding="utf-8"))


LANGS = ("zh_TW", "zh_CN", "en")


def test_format_version_is_one_we_read(samples):
    """iPhone 升了 format_version 而 wiki-feeder 還讀不懂就紅。常數是「讀得懂的最新版」(比它新的逐字稿,
    轉寫時加警告);照約定「先讀後寫」,wiki-feeder 可以先改好、先升常數,所以比的是「樣本不比我們新」。"""
    assert samples["format_version"] <= doc2md.TRANSCRIPT_FORMAT_VERSION


def test_vocab_matches_our_constants(samples):
    """三語的診斷段標題、名字來源、暫停行頭尾、重點說明行(整句),逐字跟 doc2md 的常數一樣(兩個方向都比)。
    要多認舊寫法就另外放常數,不混進這幾組。"""
    v = samples["vocab"]
    assert set(v) == set(LANGS) == set(samples["lines"]), f"樣本的語言變了:{sorted(v)}"
    assert set(doc2md.DIAG_HEADINGS) == {v[k]["diagnostic_heading"] for k in LANGS}
    assert doc2md.NAME_SOURCE_NONE == {v[k]["name_source_none"] for k in LANGS}
    assert doc2md.NAME_SOURCE_AUTO == {v[k]["name_source_auto"] for k in LANGS}
    assert set(doc2md.PAUSE_MARKS) == {(v[k]["pause_head"], v[k]["pause_tail"]) for k in LANGS}
    assert set(doc2md.HIGHLIGHT_NOTES) == {v[k]["highlight_note"] for k in LANGS}


def _transcript(tmp_path: Path, lang: str, samples: dict, extra: str = "") -> Path:
    v, ln = samples["vocab"][lang], samples["lines"][lang]
    md = tmp_path / f"{lang}.md"
    md.write_text(
        f"---\nformat_version: {samples['format_version']}\nlossy_kinds: []\n---\n\n# 錄音\n\n"
        f"{v['highlight_note']}\n\n{v['transcript_heading']}2026-11-07\n\n"
        f"{ln['speaker']}\n\n{ln['speaker_marks']}\n\n{ln['pause']}\n\n{ln['unknown_speaker']}\n\n{extra}"
        f"{v['diagnostic_heading']}\n\n| A | B | C |\n|---|---|---|\n"
        f"| {v['speaker_prefix']}1 | 3 | {v['name_source_none']} |\n"
        f"| Alice | 2 | {v['name_source_auto']} |\n"
        f"| Bob | 1 | {v['name_source_confirmed']} |\n",
        encoding="utf-8",
    )
    return md


@pytest.mark.parametrize("lang", LANGS)
def test_every_line_kind_is_recognized(tmp_path, samples, lang):
    """只有講者標頭、暫停行、重點說明、診斷段 → 0 字(只有標頭的英文、簡中逐字稿也要被標捨棄候選);
    診斷表的未命名／機器辨識講者各認得一個。樣本多了新的行種類就紅(這裡要跟著加)。"""
    assert set(samples["lines"][lang]) == {"speaker", "speaker_marks", "pause", "unknown_speaker"}, \
        f"樣本的行種類變了:{sorted(samples['lines'][lang])}"
    info = doc2md.parse_md(_transcript(tmp_path, lang, samples), transcript=True)
    assert info.format_version == samples["format_version"]
    assert info.body_chars == 0
    assert info.unnamed_speakers == [samples["vocab"][lang]["speaker_prefix"] + "1"]
    assert info.machine_named == ["Alice"]


@pytest.mark.parametrize("lang", LANGS)
def test_real_speech_is_kept(tmp_path, samples, lang):
    """標頭剝掉、講的話留著:字數剛好是那一句。"""
    ln = samples["lines"][lang]
    extra = f"{ln['speaker_marks']}\n\n八個字的內文在這\n\n"
    assert doc2md.parse_md(_transcript(tmp_path, lang, samples, extra), transcript=True).body_chars == 8


def test_readable_speaker_lines_new_and_old(tmp_path, samples):
    """新舊寫法的講者行(含 2026-11-07 以前英文 md 的〔highlight〕)都當標頭剝掉。
    wiki-feeder 不從講者行抽名字與標記(名字只從診斷表取),所以 name／marks 不比對。"""
    for i, r in enumerate(samples["readable"]):
        md = tmp_path / f"r{i}.md"
        md.write_text(f"{r['line']}\n\n{r['line']}說了一句話\n", encoding="utf-8")
        assert doc2md.parse_md(md, transcript=True).body_chars == len("說了一句話"), r["line"]


@pytest.mark.parametrize("lang", LANGS)
def test_diag_table_last_column_is_the_name_source(tmp_path, samples, lang):
    """iPhone 實際產生的講者診斷表:最後一欄是名字來源——
    未命名的兩人列進未命名講者;命名後 Alice(人工確認)不提醒、Bob(機器辨識)列進機器辨識講者;
    兩人都機器辨識就都列;機器辨識後把 Alice 改名 Alicia 算人工確認、Bob 沒換照舊是機器辨識
    (iOS abf0daa 起,講者行與表格保證一致)。樣本裡的講者行放進內文,表格放在診斷段底下,
    講者行一律當標頭剝掉、不算字數。"""
    if "diag_table" not in samples:
        pytest.skip("約定樣本太舊、沒有 diag_table(iOS dfb87e6 起才有):先 git pull iPhone 的 repo")
    v = samples["vocab"][lang]
    p = v["speaker_prefix"]
    want = {
        "unnamed": ([p + "1", p + "2"], []),
        "named": ([], ["Bob"]),
        "auto_named": ([], ["Alice", "Bob"]),
        "renamed_after_auto": ([], ["Bob"]),
    }
    tables = samples["diag_table"][lang]
    assert set(tables) == set(want), f"樣本的表種類變了:{sorted(tables)}"
    for kind, rows in tables.items():
        speakers = [r for r in rows if not r.startswith("|")]
        table = [r for r in rows if r.startswith("|")]
        md = tmp_path / f"{lang}-{kind}.md"
        md.write_text("".join(f"{s}\n\n" for s in speakers)
                      + f"{v['diagnostic_heading']}\n\n" + "\n".join(table) + "\n", encoding="utf-8")
        info = doc2md.parse_md(md, transcript=True)
        assert (info.unnamed_speakers, info.machine_named, info.body_chars) == (*want[kind], 0), kind
