"""設定檔(朋友的 Windows 版):單庫、沒有 FUTURES、拼錯的鍵要大聲失敗。全部用 tmp_path,不讀真的家目錄。"""
from __future__ import annotations

import os
import shutil
import sys
import re
from pathlib import Path

import pytest

from wiki_feeder.config import CONFIG_FILE, Config, ConfigError, state_dir_for

GOOD = """
[inbox]
icloud = '{root}/iCloudDrive/_WikiBox'

[wiki]
dir = '{root}/WIKI'
raw = '{root}/Raw_Sources'

[mail]
from = "friend@example.com"
to = "friend@example.com"

[tools]
doc2md = '{root}/scribe2md/.venv/Scripts/doc2md.exe'
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / CONFIG_FILE
    p.write_text(text.format(root=tmp_path.as_posix()), encoding="utf-8")
    return p


def test_single_repo_config_from_file(tmp_path):
    c = Config.from_file(_write(tmp_path, GOOD), tmp_path / "state")

    (rc,) = c.repos
    assert rc.repo_dir == tmp_path / "WIKI" and rc.raw_root == tmp_path / "Raw_Sources"
    assert c.target_repo == rc.key and c.backfill_repo == ""
    # 收件區不是原件樹的 _待處理(同一個的話,搬進 _待處理 會把自己改名成 X_2),也不算原件
    assert c.pending_dir == tmp_path / "Raw_Sources" / "_收件區" and c.raw_roots == (rc.raw_root,)
    assert "_收件區" in c.raw_skip_dirs and rc.managed
    assert c.futures is None and c.onedrive_inbox is None and c.repair_repo is None
    assert c.icloud_inbox == tmp_path / "iCloudDrive" / "_WikiBox"
    assert c.state_dir == tmp_path / "state"
    assert c.mail_to == "friend@example.com" and c.doc2md_cmd[0].endswith("doc2md.exe")


def test_config_saved_with_a_bom_is_read(tmp_path):
    """記事本選「UTF-8 (BOM)」、PowerShell 5.1 的 Set-Content -Encoding utf8 都會在開頭加 BOM;
    tomllib 不認它,整份設定讀不了(2026-10-19 Windows 實測)。"""
    p = tmp_path / CONFIG_FILE
    p.write_bytes(b"\xef\xbb\xbf" + GOOD.format(root=tmp_path.as_posix()).encode("utf-8"))
    assert Config.from_file(p, tmp_path / "state").mail_to == "friend@example.com"


@pytest.mark.parametrize("text, said", [
    (GOOD.replace("[mail]", "[mial]"), "[mial]"),                              # 段落拼錯:寄信就安靜地沒設定
    (GOOD.replace("icloud =", "iclod ="), "[inbox] iclod"),                     # 收件匣拼錯:檔案一直沒人收
    (GOOD.replace("dir = ", "# dir = "), "[wiki] dir"),
    (GOOD.replace("icloud = ", "# icloud = "), "收件匣"),
    ("[wiki\n", "讀不了"),
])
def test_bad_config_fails_loudly(tmp_path, text, said):
    with pytest.raises(ConfigError, match=said.replace("[", r"\[").replace("]", r"\]")):
        Config.from_file(_write(tmp_path, text), tmp_path / "state")


def test_doc2md_is_optional(tmp_path):
    """[tools] doc2md 沒填 = 沒裝 scribe2md(朋友版選裝,使用者 2026-10-29,§4.8):讀得了,轉寫指令與 ffmpeg 都是空的;
    填了不是字串才報錯。"""
    c = Config.from_file(_write(tmp_path, GOOD.replace("doc2md = ", "# doc2md = ")), tmp_path / "state")
    assert c.doc2md_cmd == () and c.ffmpeg == ""
    with pytest.raises(ConfigError, match="doc2md"):
        Config.from_file(_write(tmp_path, re.sub(r"doc2md = .*", "doc2md = 3", GOOD)), tmp_path / "state")


def test_state_dir_per_platform(tmp_path):
    assert state_dir_for("win32", tmp_path, {"LOCALAPPDATA": str(tmp_path / "L")}) == tmp_path / "L" / "wiki-feeder"
    assert state_dir_for("win32", tmp_path, {}) == tmp_path / "AppData" / "Local" / "wiki-feeder"
    assert state_dir_for("darwin", tmp_path, {}) == tmp_path / "Library" / "Application Support" / "wiki-feeder"


def test_windows_without_config_file_refuses_instead_of_using_the_owners_mac_setup(tmp_path, monkeypatch):
    """朋友 clone 下來還沒寫設定檔:不可照使用者的 Mac 設定去寄信、取 FUTURES。"""
    monkeypatch.setattr("wiki_feeder.config.PLATFORM", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(ConfigError, match="找不到設定檔"):
        Config.default()


def test_mac_without_config_file_refuses_when_it_is_not_the_owners_mac(tmp_path):
    """公開 repo 沒有 owner_mac.py:Mac 朋友少放一個設定檔,不可安靜地用別人的路徑收件、寄別人的信。

    真的複製一份不含 owner_mac.py 的套件、在子行程裡讀:原本用 sys.modules[...] = None 假裝沒有這個檔,
    丟的是 ModuleNotFoundError,跟真的少一個檔(ImportError)不一樣,程式只接前者也照樣過(2026-10-21)。"""
    import subprocess

    import wiki_feeder

    pkg = tmp_path / "pkg" / "wiki_feeder"
    shutil.copytree(Path(wiki_feeder.__file__).parent, pkg,
                    ignore=shutil.ignore_patterns("owner_mac.py", "__pycache__"))
    code = ("import wiki_feeder.config as c\n"
            "assert c.__file__.startswith(%r), c.__file__\n"
            "c.PLATFORM = 'darwin'\n"
            "try:\n    c.Config.default()\nexcept c.ConfigError as e:\n    print('ConfigError', e)\n") % str(pkg)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "PYTHONPATH": str(pkg.parent), "HOME": str(home)}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-800:]
    assert "ConfigError" in r.stdout and "install.sh" in r.stdout


def test_config_file_wins_over_owner_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("wiki_feeder.config.PLATFORM", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    state = tmp_path / "wiki-feeder"
    state.mkdir()
    (state / CONFIG_FILE).write_text(GOOD.format(root=tmp_path.as_posix()), encoding="utf-8")
    c = Config.default()
    assert c.futures is None and c.state_dir == state


def test_config_errors_follow_the_interface_language(tmp_path):
    """朋友看得到的錯誤:英文介面時是英文(路徑與鍵名照原樣)。"""
    import re

    from wiki_feeder import i18n

    i18n.set_lang("en")
    for text, said in [(GOOD.replace("[mail]", "[mial]"), "[mial]"), (GOOD.replace("dir = ", "# dir = "), "[wiki] dir"),
                       (GOOD + "\n[general]\nlanguage = 'fr'\n", "'fr'")]:
        with pytest.raises(ConfigError) as e:
            Config.from_file(_write(tmp_path, text), tmp_path / "state")
        assert said in str(e.value) and not re.search(r"[㐀-鿿]", str(e.value)), str(e.value)


def test_language_comes_from_the_config_file(tmp_path):
    c = Config.from_file(_write(tmp_path, GOOD + "\n[general]\nlanguage = 'en'\n"), tmp_path / "state")
    assert c.lang == "en"
    assert Config.from_file(_write(tmp_path, GOOD), tmp_path / "state").lang == "zh-Hant"


def test_friends_config_turns_auto_update_on_by_default_on_both_platforms(tmp_path):
    """朋友版的自動更新兩個平台都預設打開(使用者 2026-10-23);設定檔 [general] auto_update = false 關掉。"""
    assert Config.from_file(_write(tmp_path, GOOD), tmp_path / "state").auto_update is True
    off = GOOD + "\n[general]\nauto_update = false\n"
    assert Config.from_file(_write(tmp_path, off), tmp_path / "state").auto_update is False
