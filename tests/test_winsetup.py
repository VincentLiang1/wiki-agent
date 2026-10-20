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
