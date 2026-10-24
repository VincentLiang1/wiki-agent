"""三種介面語言(i18n.py):譯文齊全、佔位符對得上、給程式比對的字沒被翻掉;選語言與設定檔。"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from wiki_feeder import i18n
from wiki_feeder.config import Config, ConfigError

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location("l10n_sync", ROOT / "scripts" / "l10n_sync.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

KEYS = sync.extract()
EN = json.loads((i18n.LOCALES / "en.json").read_text(encoding="utf-8"))
HANS = json.loads((i18n.LOCALES / "zh-Hans.json").read_text(encoding="utf-8"))
# 英文譯文裡可以留的中文:程式寫死的資料夾名、doc2md 印的字、scribe2md 的 App 名與畫面字(它還沒有英文版)
CJK_ALLOWED = ("_待處理", "_捨棄候選", "_收件區", "執行記錄", "_聲紋同步", "AI 文件.MD 轉換器")
CJK = re.compile(r"[㐀-鿿！-｠　-〿]")


def test_hans_doc_points_links_at_the_simplified_guides():
    """說明檔名 2026-10-22 起是英文:OpenCC 不會再把連結裡的繁中檔名轉成簡中那份,要 hans_doc 自己換。"""
    class Same:
        convert = staticmethod(lambda s: s)
    src = ("[English](Mac-Install-Guide.md) | **繁體中文** | [简体中文](Mac-Install-Guide.zh-CN.md)\n\n"
           "看 [Windows-Install-Guide.zh-TW.md](Windows-Install-Guide.zh-TW.md)。照 README.md 做\n")
    head, body = sync.hans_doc(src, Same()).split("\n", 1)
    assert head == "[English](Mac-Install-Guide.md) | [繁體中文](Mac-Install-Guide.zh-TW.md) | **简体中文**"
    assert "[Windows-Install-Guide.zh-CN.md](Windows-Install-Guide.zh-CN.md)" in body and "README.md" in body


def _fields(s: str) -> tuple:
    return (sorted(re.findall(r"(?<!\{)\{(\w*)[^{}]*\}(?!\})", s)), len(re.findall(r"%[sdfr]", s)))


def test_every_string_has_english_and_simplified_chinese():
    """缺的話跑 scripts/l10n_sync.py(簡中自動轉;英文要給 --en)。"""
    assert KEYS, "程式裡找不到任何 L(…)"
    assert [KEYS[k] for k in KEYS if k not in EN] == []
    assert [KEYS[k] for k in KEYS if k not in HANS] == []


def test_no_stale_translations():
    assert sorted(set(EN) - set(KEYS)) == [] and sorted(set(HANS) - set(KEYS)) == []


@pytest.mark.parametrize("cat", [EN, HANS], ids=["en", "zh-Hans"])
def test_placeholders_match_the_original(cat):
    """{name} 少一個,L(…, name=…) 就丟 KeyError;%s 數量不對,log 就印不出來。"""
    bad = [KEYS[k] for k, v in cat.items() if k in KEYS and _fields(k) != _fields(v)]
    assert bad == []


@pytest.mark.parametrize("cat", [EN, HANS], ids=["en", "zh-Hans"])
def test_tokens_the_program_matches_on_survive(cat):
    """ingest 以 `STOP:` 開頭判斷要不要整個停下(ingest.py);譯文也要以它開頭。"""
    bad = [KEYS[k] for k, v in cat.items() if k.startswith("STOP:") and not v.startswith("STOP:")]
    assert bad == []
    # collect.network_down 以「訊息裡有沒有 STOP」決定斷網時要不要照樣報:原文有 STOP 的譯文也要有
    assert [KEYS[k] for k, v in cat.items() if "STOP" in k and "STOP" not in v] == []



def test_system_folder_names_are_never_baked_into_messages():
    """原件樹的系統資料夾名依安裝而不同(新裝 _Pending,舊版 _待處理):要翻的字裡寫死了,
    英文朋友就看到中文資料夾名、舊庫的人看到他磁碟上沒有的英文名(使用者 2026-10-24)。一律用佔位符代入。"""
    from wiki_feeder.config import SYSTEM_DIRS
    assert [(KEYS[k], d) for k in KEYS for d in SYSTEM_DIRS if d in k] == []


def test_english_has_no_leftover_chinese():
    bad = []
    for k, v in EN.items():
        s = v
        for w in CJK_ALLOWED:
            s = s.replace(w, "")
        if CJK.search(s):
            bad.append((KEYS.get(k), v[:60]))
    assert bad == []


def test_simplified_is_not_just_a_copy():
    """自動轉換沒跑的話簡中會等於繁中原文:有簡繁差異字的鍵,譯文不可以一模一樣。"""
    diff = [k for k in KEYS if re.search("[這們說時為與會檔設讀頁寫錄點]", k)]
    assert diff and [KEYS[k] for k in diff if HANS.get(k) == k] == []


def test_L_formats_and_falls_back_to_the_original():
    assert i18n.L("沒有這個鍵 {x}", x=1) == "沒有這個鍵 1"
    i18n.set_lang("en")
    k = next(k for k in KEYS if "{" not in k)
    assert i18n.L(k) == EN[k]
    i18n.set_lang("xx")
    assert i18n.get_lang() == i18n.SOURCE


@pytest.mark.parametrize("tag,lang", [("zh-Hant-TW", "zh-Hant"), ("zh_TW.UTF-8", "zh-Hant"), ("zh-HK", "zh-Hant"),
                                      ("zh-Hans-CN", "zh-Hans"), ("zh_CN.UTF-8", "zh-Hans"), ("zh-SG", "zh-Hans"),
                                      ("en-US", "en"), ("ja-JP", "en"), ("de_DE.UTF-8", "en")])
def test_from_locale(tag, lang):
    assert i18n.from_locale(tag) == lang


def test_detect_on_mac_reads_the_first_preferred_language():
    class R:
        def __init__(self, out):
            self.stdout = out

    assert i18n.detect("darwin", {}, lambda *a, **k: R('(\n    "zh-Hant-TW",\n    "en-TW"\n)')) == "zh-Hant"
    assert i18n.detect("darwin", {}, lambda *a, **k: R('(\n    "zh-Hans-CN"\n)')) == "zh-Hans"
    assert i18n.detect("darwin", {}, lambda *a, **k: R('(\n    "en-GB",\n    "zh-Hant-TW"\n)')) == "en"
    assert i18n.detect("darwin", {}, lambda *a, **k: R("(\n    en\n)")) == "en"

    def boom(*a, **k):
        raise OSError("沒有 defaults")
    assert i18n.detect("darwin", {"LANG": "en_US.UTF-8"}, boom) == "en"
    assert i18n.detect("darwin", {"LANG": "C"}, boom) == i18n.SOURCE
    assert i18n.detect("darwin", {}, boom) == i18n.SOURCE


def _cfg_text(tmp_path: Path, extra: str = "") -> Path:
    p = tmp_path / "config.toml"
    p.write_text(f"""{extra}
[inbox]
icloud = '{tmp_path / "in"}'
[wiki]
dir = '{tmp_path / "WIKI"}'
raw = '{tmp_path / "Raw"}'
[tools]
doc2md = '{tmp_path / "doc2md"}'
""", encoding="utf-8")
    return p


def test_config_language(tmp_path):
    assert Config.from_file(_cfg_text(tmp_path), tmp_path).lang == "zh-Hant"
    for lang in i18n.LANGS:
        assert Config.from_file(_cfg_text(tmp_path, f'[general]\nlanguage = "{lang}"'), tmp_path).lang == lang
    with pytest.raises(ConfigError):
        Config.from_file(_cfg_text(tmp_path, '[general]\nlanguage = "fr"'), tmp_path)


def test_simplified_texts_have_no_doubled_wen():
    """OpenCC 把「文件」轉成「文档」,ZH_HANS_FIX 的「档 → 文件」又把它改成「文文件」(2026-10-22 在簡中說明裡發現,
    已發佈好幾次):l10n_sync.py 在最後補「文文件 → 文档」。簡中的說明、譯文檔、.bat 都不可以出現。"""
    public = ROOT / "public" if (ROOT / "public").is_dir() else ROOT
    texts = [p.read_text(encoding="utf-8") for p in public.glob("*zh-Hans*.md")]
    texts.append((ROOT / "src" / "wiki_feeder" / "locales" / "zh-Hans.json").read_text(encoding="utf-8"))
    texts += [p.read_bytes().decode("utf-8") for p in ROOT.glob("*.bat")]
    assert texts and not [t for t in texts if "文文件" in t]
