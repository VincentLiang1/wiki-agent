"""朋友那台的安裝問答(scripts/winsetup.py)與三個 .bat:問答本身要人操作,這裡守寫出來的設定檔與 .bat 的格式。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from wiki_feeder.config import CONFIG_FILE, ConfigError

ROOT = Path(__file__).parents[1]
BATS = ["Install.bat", "Update.bat", "Remove-Schedule.bat"]


def _mod():
    spec = importlib.util.spec_from_file_location("winsetup_script", ROOT / "scripts" / "winsetup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ANSWERS = {"icloud": r"C:\Users\阿明\iCloudDrive\_WikiBox", "wiki": r"C:\LLMWIKI\WIKI",
           "raw": r"C:\LLMWIKI\Raw_Sources", "label": '阿明的"知識庫"',
           "doc2md": r"C:\Users\阿明\Downloads\scribe2md\.venv\Scripts\doc2md.exe",
           "mail_from": "amy@gmail.com", "mail_to": "amy@gmail.com"}


def test_answers_round_trip_through_the_real_config_reader(tmp_path):
    """Windows 路徑的反斜線(\\U、\\a…)寫進 TOML 不可被當成跳脫:讀回來要一字不差。"""
    m = _mod()
    cfg = m.write_config(m.render_config(ANSWERS), tmp_path)
    assert cfg.icloud_inbox == Path(ANSWERS["icloud"])
    assert cfg.repos[0].repo_dir == Path(ANSWERS["wiki"]) and cfg.repos[0].label == ANSWERS["label"]
    assert cfg.raw_roots == (Path(ANSWERS["raw"]),)
    assert cfg.doc2md_cmd == (ANSWERS["doc2md"],)
    assert (cfg.mail_from, cfg.mail_to) == ("amy@gmail.com", "amy@gmail.com")
    assert (tmp_path / CONFIG_FILE).is_file() and not (tmp_path / (CONFIG_FILE + ".new")).exists()


def test_mail_can_be_left_empty(tmp_path):
    m = _mod()
    cfg = m.write_config(m.render_config({**ANSWERS, "mail_from": "", "mail_to": ""}), tmp_path)
    assert cfg.mail_from == ""


def test_path_with_a_single_quote_is_refused():
    """TOML 字面字串跳脫不了單引號:寫進去整份設定檔就讀不了,所以當場請朋友改資料夾名。"""
    with pytest.raises(ValueError):
        _mod().render_config({**ANSWERS, "wiki": r"C:\Amy's\WIKI"})


def test_unreadable_config_is_not_written(tmp_path):
    """寫之前先用真的 Config.from_file 讀:讀不了就不留檔(下一分鐘的排程不會拿到壞掉的設定)。"""
    m = _mod()
    (tmp_path / CONFIG_FILE).write_text("舊的\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        m.write_config(m.render_config(ANSWERS).replace("doc2md =", "doc2nd ="), tmp_path)
    assert (tmp_path / CONFIG_FILE).read_text(encoding="utf-8") == "舊的\n"
    assert not (tmp_path / (CONFIG_FILE + ".new")).exists()


def _bat(name: str) -> str:
    return (ROOT / name).read_bytes().decode("utf-8")


def _l10n():
    spec = importlib.util.spec_from_file_location("l10n_sync_bat", ROOT / "scripts" / "l10n_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("name", BATS)
def test_bat_is_utf8_crlf_and_switches_code_page_first(name):
    """三種語言要 UTF-8(cp950 寫不出簡體字):無 BOM、CRLF,任何非 ASCII 之前先 chcp 65001(docs/dev/Windows安裝.md)。"""
    data = (ROOT / name).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")                        # BOM 會讓第一行變成「'﻿@echo' 不是指令」
    text = data.decode("utf-8")
    assert "\n" not in text.replace("\r\n", "")                     # 沒有單獨的 LF
    first_non_ascii = next(i for i, ch in enumerate(text) if ord(ch) > 127)
    assert "chcp 65001 >nul" in text[:first_non_ascii] and "chcp 950" not in text


@pytest.mark.parametrize("name", BATS)
def test_bat_chinese_appears_only_in_message_arguments(name):
    """65001 底下 cmd 會把中文附近的行讀錯、切掉半截當指令執行(2026-10-21 實測:直接 echo 中文的下一行、
    標籤前後的中文 rem 都出過事):中文只准出現在 `call :msg／:pick` 的三個參數裡(由副程式 echo 變數),rem 也不行。"""
    pat = _l10n().BAT_MSG
    for ln in _bat(name).splitlines():
        s = ln.strip()
        if s.isascii():
            continue
        assert pat.search(s), f"中文不在 :msg／:pick 的參數裡:{s}"
        assert pat.sub("", s).isascii(), f"參數之外還有中文:{s}"


@pytest.mark.parametrize("name", BATS)
def test_bat_line_before_every_label_is_ascii(name):
    """65001 底下標籤的前一行有中文,cmd 跳過去(call :msg、goto)會落在前一行中間,先執行半截垃圾
    (2026-10-21 真的 Install.bat:每印一行訊息前面都多一個「'��一行' is not recognized」)。註解寫在標籤之後。"""
    lines = _bat(name).splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(":") and i:
            assert lines[i - 1].isascii(), f"{ln} 的前一行有中文:{lines[i - 1]}"


@pytest.mark.parametrize("name", BATS)
def test_bat_messages_are_safe_for_cmd_and_complete(name):
    """訊息會經過 call 與 echo:& | < > ^ ! 與 ASCII 括號會被 cmd 當成語法(在 if ( … ) 裡更會提早結束區塊);
    三種語言都要有,英文不夾中文(檔名例外),簡中要是 l10n_sync.py 轉過的(沒跑就還是繁體字)。"""
    l10n = _l10n()
    rows = [m.groups()[1:] for ln in _bat(name).splitlines() if not ln.strip().lower().startswith("rem ")
            for m in l10n.BAT_MSG.finditer(ln)]
    assert rows
    hant_only = set("裝資設視檔載啟網開註體們這個從後說時處紀錄執")      # 簡中裡出現就是沒轉
    for hant, hans, en in rows:
        for s in (hant, hans, en):
            assert s.strip() and not set(s) & set("&|<>^!()"), s
            assert "%" not in s.replace("%FAIL%", ""), s
        assert not set(hans) & hant_only, f"簡中沒轉:{hans}"
        assert "纪录" not in hans and "帐号" not in hans
        assert en.isascii(), en


def test_bats_share_one_copy_of_the_language_helpers():
    """語言判斷、:msg、:pick、:pause 三個 .bat 一字不差(改一份忘了另外兩份,更新／移除的畫面就跟安裝不一樣)。"""
    mark = "rem ==== same in all three .bat files from here to the end"
    tails = {name: _bat(name).split(mark, 1)[1] for name in BATS}
    assert len(set(tails.values())) == 1
    tail = tails["Install.bat"]
    assert all(f":{label}\r\n" in tail for label in ("lang", "msg", "pick", "pause"))
    for name in BATS:
        code = [ln.strip() for ln in _bat(name).split(mark, 1)[0].splitlines()
                if not ln.strip().lower().startswith("rem ")]
        first = next(i for i, s in enumerate(code) if "call :msg" in s or "call :pick" in s or "call :pause" in s)
        assert "call :lang" in code[:first]                              # 印第一個字之前先定語言
        assert "pause" not in code                                       # 65001 底下 cmd 的 pause 是英文


def test_bat_language_rule_matches_i18n_detect():
    """.bat 在 Python 之前跑,自己判斷語言:設定檔優先、再 GetUserDefaultUILanguage,對照要與 i18n.detect 相同。
    不可用 Get-UICulture:它跟著主控台碼頁走,65001 底下台灣的 Windows 也回 en-US。"""
    import inspect
    import re

    from wiki_feeder import i18n
    lang = next(ln for ln in _bat("Install.bat").splitlines() if ln.startswith("for /f") and "powershell" in ln)
    hexes = lambda s: {int(h, 16) for h in re.findall(r"0x[0-9A-Fa-f]+", s)}   # noqa: E731
    assert hexes(lang) == {0x3FF, 0x804, 0x1004} <= hexes(inspect.getsource(i18n.detect))
    assert "-eq 4" in lang and "== 0x04" in inspect.getsource(i18n.detect)
    assert "GetUserDefaultUILanguage" in lang and "Get-UICulture" not in lang
    assert "wiki-feeder\\config.toml" in lang and 'if not defined WL set "WL=zh-Hant"' in _bat("Install.bat")


@pytest.mark.skipif(not __import__("sys").platform == "win32", reason="要 Windows 的 PowerShell 與 kernel32")
def test_bat_language_detection_really_runs(tmp_path):
    """把 .bat 那段 PowerShell 拿出來真的跑:設定檔寫什麼就是什麼(英文、簡中),沒有設定檔就跟 i18n.detect() 一樣。"""
    import os
    import re
    import subprocess

    from wiki_feeder import i18n
    line = next(ln for ln in _bat("Install.bat").splitlines() if ln.startswith("for /f") and "powershell" in ln)
    ps = re.search(r'-Command "(.*)"`\)', line)[1]
    cfg = tmp_path / "wiki-feeder" / "config.toml"
    cfg.parent.mkdir()

    def run() -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, env={**os.environ, "LOCALAPPDATA": str(tmp_path)})
        return r.stdout.strip()

    assert run() == i18n.detect()
    for lang in ("en", "zh-Hans", "zh-Hant"):
        cfg.write_text(f"# 設定\n\n[general]\nlanguage = \"{lang}\"\n\n[paths]\nwiki = 'C:\\x'\n", encoding="utf-8")
        assert run() == lang
    cfg.write_text("[general]\nlanguage = \"xx\"\n", encoding="utf-8")
    assert run() == i18n.detect()


def test_l10n_sync_rewrites_only_the_hans_column_of_bats():
    """簡中那一欄由 l10n_sync.py 從繁中重轉;繁中、英文、rem 註解、其他指令一個字都不動。"""
    text = ('rem call :msg "繁中" "簡中" "English"\r\n'
            'if errorlevel 1 call :msg "裝好" "舊的" "Installed"\r\n'
            'call :pick T "安裝" "x" "Setup"\r\ntitle %T%\r\n')
    out = _l10n().hans_bat(text, lambda s: f"<{s}>")
    assert out == ('rem call :msg "繁中" "簡中" "English"\r\n'
                   'if errorlevel 1 call :msg "裝好" "<裝好>" "Installed"\r\n'
                   'call :pick T "安裝" "<安裝>" "Setup"\r\ntitle %T%\r\n')


def test_install_bat_elevates_only_the_long_path_step():
    """整個 bat 用管理員跑,設定檔與排程會裝到管理員帳號底下:只有寫 HKLM 那一行提升權限。"""
    text = _bat("Install.bat")
    assert text.count("-Verb RunAs") == 1
    assert "LongPathsEnabled','/t'" in text


def test_update_bat_waits_for_the_running_round_and_always_reenables():
    """更新不砍正在跑的一輪(攝入做到一半被砍會 STOP),pull／下載／sync 失敗也要重新啟用排程。"""
    lines = [ln if not ln.lower().startswith("rem ") else "" for ln in _bat("Update.bat").splitlines()]
    i_disable = next(i for i, ln in enumerate(lines) if "winsched.py disable" in ln)
    i_pull = next(i for i, ln in enumerate(lines) if ln.strip() == "git pull")
    i_zip = next(i for i, ln in enumerate(lines) if "winupdate.py" in ln)
    i_enable = next(i for i, ln in enumerate(lines) if "winsched.py enable" in ln)
    assert i_disable < i_pull < i_enable and i_disable < i_zip < i_enable
    labels = {ln.strip()[1:].lower(): i for i, ln in enumerate(lines) if ln.startswith(":")}
    for ln in lines[i_disable:i_enable]:                              # 失敗也走到 enable:只跳到 enable 之前的標籤
        if "goto" in ln:
            assert labels[ln.split("goto", 1)[1].strip().lower()] < i_enable, ln
    assert not any("/End" in ln or "taskkill" in ln for ln in lines)


def test_update_bat_runs_from_a_copy_in_temp():
    """cmd 照位元組位置讀正在跑的 .bat:git pull／zip 更新換掉 Update.bat 之後,後半段會從某一行的中間讀起
    (改名那次實測是直接中斷、排程停在停用)。開頭先複製到 %TEMP% 從副本跑。"""
    lines = _bat("Update.bat").splitlines()
    i_copy = next(i for i, ln in enumerate(lines) if ln.startswith("copy ") and "%~f0" in ln)
    i_disable = next(i for i, ln in enumerate(lines) if "winsched.py disable" in ln)
    assert i_copy < i_disable and any('"%TEMP%' in ln and "--copy" in ln for ln in lines[:i_disable])
    assert all(ord(ch) < 128 for ln in lines[:i_copy + 3] for ch in ln)   # chcp 之前只能是 ASCII


# -- 介面語言(繁中原文／簡中／English):問答第一題選,寫進設定檔 [general] language ---------------------

def _cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def test_language_question_defaults_and_ignores_a_bad_choice(monkeypatch):
    """還不知道語言時三種寫法並列;直接按 Enter／打錯都用預設(偵測到的或設定檔裡的)。"""
    from wiki_feeder import i18n
    m = _mod()
    prompts = []
    for answer, default, want in (("", "zh-Hans", "zh-Hans"), ("9", "en", "en"), ("2", "en", "zh-Hans"),
                                  ("1", "en", "zh-Hant"), ("", "xx", "zh-Hant")):
        monkeypatch.setattr("builtins.input", lambda p, a=answer: prompts.append(p) or a)
        assert m.ask_lang(default) == want and i18n.get_lang() == want
    assert all(s in prompts[0] for s in ("繁體中文", "简体中文", "English", "Language"))


def test_choosing_english_makes_the_following_prompts_english(monkeypatch):
    """選 3 之後 ask／yes 的提示(含「直接按 Enter = …」「Y/n」)都是英文。要等主代理合併 locales/en.json 才會過。"""
    m = _mod()
    answers = iter(["3", "", ""])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda p: prompts.append(p) or next(answers))
    assert m.ask_lang("zh-Hant") == "en"
    assert m.ask(m.L("  收件信箱"), "amy@gmail.com") == "amy@gmail.com"
    assert m.yes(m.L("沿用這份(不重填)?"))
    assert not any(_cjk(p) for p in prompts[1:]), prompts
    assert "amy@gmail.com" in prompts[1] and "Y/n" in prompts[2]
    assert m.L("知識庫") != "知識庫" and not _cjk(m.L("知識庫"))


def test_config_records_the_chosen_language_first(tmp_path):
    from wiki_feeder import i18n
    m = _mod()
    text = m.render_config({**ANSWERS, "lang": "en"})
    lines = text.splitlines()
    assert lines[0].startswith("#") and lines[2:4] == ["[general]", 'language = "en"']
    assert m.write_config(text, tmp_path).lang == "en"
    i18n.set_lang("zh-Hans")                                            # 沒給就用現在的介面語言
    assert 'language = "zh-Hans"' in m.render_config(ANSWERS)
    assert m.config_lang(tmp_path / CONFIG_FILE) == "en"
    assert m.config_lang(tmp_path / "沒有.toml") is None


def test_reusing_an_old_config_only_switches_the_language(tmp_path):
    """沿用舊設定檔(沒有 [general] 的舊版、或已經有的)又換了語言:只改那一行,其他照舊、讀得回來。"""
    m = _mod()
    old = "\n".join(ln for ln in m.render_config(ANSWERS).splitlines()
                    if ln not in ("[general]", 'language = "zh-Hant"')) + "\n"
    assert "[general]" not in old
    cfg = m.write_config(m.set_config_lang(old, "en"), tmp_path)
    assert cfg.lang == "en" and cfg.repos[0].label == ANSWERS["label"]
    again = m.set_config_lang((tmp_path / CONFIG_FILE).read_text(encoding="utf-8"), "zh-Hans")
    assert again.count("[general]") == 1 and again.count("language =") == 1
    assert m.write_config(again, tmp_path).lang == "zh-Hans"


# -- 一開始就選語言(使用者 2026-10-27:「一開始時確認語言後,就只用使用者選定的語言顯示」) --------------------

def test_language_chosen_by_the_entry_script_is_not_asked_again(monkeypatch):
    """入口(Install.bat、install.sh、App 的 setup.zsh)問過、用 WIKI_AGENT_LANG 帶進來:問答不再問;沒帶或帶錯照舊問。"""
    from wiki_feeder import i18n
    m = _mod()
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("問了第二次語言"))
    assert m.entry_lang({m.LANG_ENV: "en"}) == "en" and i18n.get_lang() == "en"
    assert m.entry_lang({m.LANG_ENV: "zh-Hans"}) == "zh-Hans" and i18n.get_lang() == "zh-Hans"
    assert m.entry_lang({}) is None and m.entry_lang({m.LANG_ENV: "fr"}) is None
    for name in ("winsetup", "macsetup"):
        assert "entry_lang() or " in (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")


def test_install_bat_asks_the_same_language_question_before_anything_else():
    """Install.bat 的那一行是 base64(中文不可以出現在 :msg／:pick 之外):解出來要跟問答的一字不差,
    印第一句訊息之前就問,選的結果交給 winsetup.py。"""
    import base64
    import re
    m = _mod()
    text = _bat("Install.bat")
    code = [ln for ln in text.splitlines() if not ln.lower().startswith("rem ")]
    assert code.index("call :asklang") < next(i for i, s in enumerate(code) if "call :msg" in s or "call :pick" in s)
    lines = {"zh-Hant": next(ln for ln in code if ln.startswith('set "LB='))}
    for lang in ("zh-Hans", "en"):
        lines[lang] = next(ln for ln in code if ln.startswith(f'if "%WL%"=="{lang}" set "LB='))
    for lang, ln in lines.items():
        b = re.search(r'LB=([A-Za-z0-9+/=]+)"', ln)[1]
        assert base64.b64decode(b).decode("utf-8") == m.lang_prompt(lang)
    assert 'set "WIKI_AGENT_LANG=%WL%"' in code and m.LANG_ENV == "WIKI_AGENT_LANG"
    asked = [ln for ln in code if ln.startswith('if "%LA%"==')]
    assert asked == ['if "%LA%"=="1" set "WL=zh-Hant"', 'if "%LA%"=="2" set "WL=zh-Hans"', 'if "%LA%"=="3" set "WL=en"']
