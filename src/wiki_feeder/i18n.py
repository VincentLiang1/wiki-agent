"""介面語言:繁體中文(zh-Hant,原文)、簡體中文(zh-Hans)、English(en)。做法照 scribe2md-ios(其 spec 09)。

- **繁中是原文**:程式裡寫的字就是繁中;英文、簡中在 `locales/en.json`、`locales/zh-Hans.json`({繁中原文: 譯文})。
  使用者本人那台永遠是 zh-Hant(owner_mac 不設語言),輸出一個字都不變
- 要翻的字包 `L("…")`;模組層級的常數(載入時還不知道語言)用 `N_("…")` 登記、用的時候再 `L(常數)`
- 有佔位符的寫 `L("{name} 失敗:{e}", name=…, e=…)`(L 代入);給 logging 的 `%s` 照舊交給 logging 代入
- 改了文案跑 `scripts/l10n_sync.py`(補英文、自動轉簡中、刪掉程式裡已經沒有的鍵);缺譯文 `tests/test_i18n.py` 會紅
- 一個行程一種語言:CLI 讀完設定檔、安裝問答選完語言就 `set_lang`
- 程式拿來比對的字不翻:資料夾名(_待處理、_捨棄候選)、sidecar 的鍵、`STOP:` 開頭(譯文也要以它開頭,測試守著)、
  doc2md 印的「執行記錄」
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

LANGS = ("zh-Hant", "zh-Hans", "en")
NAMES = {"zh-Hant": "繁體中文", "zh-Hans": "简体中文", "en": "English"}
SOURCE = "zh-Hant"
LOCALES = Path(__file__).with_name("locales")

_lang = SOURCE
_catalogs: dict[str, dict[str, str]] = {}


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else SOURCE


def get_lang() -> str:
    return _lang


def catalog(lang: str) -> dict[str, str]:
    if lang not in _catalogs:
        try:
            _catalogs[lang] = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalogs[lang] = {}
    return _catalogs[lang]


def N_(text: str) -> str:
    """登記要翻的字(模組層級常數用);原樣回傳,用的時候再 L()。"""
    return text


def L(text: str, lang: str | None = None, **kw) -> str:
    lang = lang or _lang
    s = text if lang == SOURCE else catalog(lang).get(text, text)
    return s.format(**kw) if kw else s


def variants(text: str) -> tuple[str, ...]:
    """三種語言的寫法(比對「已經有這一節」之類的用)。"""
    return tuple(dict.fromkeys(L(text, lang) for lang in LANGS))


def detect(platform: str = sys.platform, env=os.environ, run=subprocess.run) -> str:
    """系統介面語言:繁中 zh-Hant、簡中 zh-Hans、其他 en;查不出來看 LANG,再查不出來 zh-Hant(原本的行為)。"""
    try:
        if platform == "darwin":
            r = run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=10)
            m = re.search(r'\(\s*"?([A-Za-z]+(?:[-_][A-Za-z0-9]+)*)', r.stdout or "")   # ( "zh-Hant-TW", "en-TW" )
            if m:
                return from_locale(m.group(1))
        elif platform == "win32":
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # 0x0404 台灣、0x0C04 香港、0x1404 澳門 = 繁中;0x0804 大陸、0x1004 新加坡 = 簡中;低 10 位元 0x04 = 中文
            if lid & 0x3FF == 0x04:
                return "zh-Hans" if lid in (0x0804, 0x1004) else "zh-Hant"
            return "en"
    except Exception:  # noqa: BLE001 —— 查不出來就往下猜,不可讓安裝停在這裡
        pass
    loc = env.get("LC_ALL") or env.get("LANG") or ""
    return from_locale(loc) if loc and loc.split(".")[0].upper() not in ("C", "POSIX") else SOURCE


def from_locale(tag: str) -> str:
    """zh-Hant-TW、zh_TW、zh-HK → zh-Hant;zh-Hans-CN、zh_CN、zh-SG → zh-Hans;其他 en。"""
    t = tag.replace("_", "-").lower()
    if not t.startswith("zh"):
        return "en"
    if "hans" in t or t.split(".")[0] in ("zh-cn", "zh-sg", "zh"):
        return "zh-Hans" if "hant" not in t else "zh-Hant"
    return "zh-Hant"
