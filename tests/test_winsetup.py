"""朋友那台的安裝問答(scripts/winsetup.py)與三個 .bat:問答本身要人操作,這裡守寫出來的設定檔與 .bat 的格式。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from wiki_feeder.config import CONFIG_FILE, ConfigError

ROOT = Path(__file__).parents[1]
BATS = ["安裝.bat", "更新.bat", "移除排程.bat"]


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


@pytest.mark.parametrize("name", BATS)
def test_bat_is_cp950_crlf_and_switches_code_page_first(name):
    """cmd 照主控台碼頁讀 .bat:cp950 無 BOM、CRLF,而且任何中文之前先 chcp 950(全域規則)。"""
    data = (ROOT / name).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    text = data.decode("cp950")
    assert "\n" not in text.replace("\r\n", "")                     # 沒有單獨的 LF
    first_non_ascii = next(i for i, ch in enumerate(text) if ord(ch) > 127)
    assert "chcp 950 >nul" in text[:first_non_ascii]


def test_install_bat_elevates_only_the_long_path_step():
    """整個 bat 用管理員跑,設定檔與排程會裝到管理員帳號底下:只有寫 HKLM 那一行提升權限。"""
    text = (ROOT / "安裝.bat").read_bytes().decode("cp950")
    assert text.count("-Verb RunAs") == 1
    assert "LongPathsEnabled','/t'" in text


def test_update_bat_waits_for_the_running_round_and_always_reenables():
    """更新不砍正在跑的一輪(攝入做到一半被砍會 STOP),pull／sync 失敗也要重新啟用排程。"""
    lines = (ROOT / "更新.bat").read_bytes().decode("cp950").splitlines()
    i_disable = next(i for i, ln in enumerate(lines) if "winsched.py disable" in ln)
    i_pull = next(i for i, ln in enumerate(lines) if ln.strip() == "git pull")
    i_enable = next(i for i, ln in enumerate(lines) if "winsched.py enable" in ln)
    assert i_disable < i_pull < i_enable
    assert not any("goto" in ln for ln in lines[i_pull:i_enable])    # 失敗也走到 enable
    assert not any("/End" in ln or "taskkill" in ln for ln in lines)


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
