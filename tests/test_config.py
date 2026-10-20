"""設定檔(朋友的 Windows 版):單庫、沒有 FUTURES、拼錯的鍵要大聲失敗。全部用 tmp_path,不讀真的家目錄。"""
from __future__ import annotations

import sys
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
    (GOOD.replace("doc2md = ", "# doc2md = "), "doc2md"),
    (GOOD.replace("icloud = ", "# icloud = "), "收件匣"),
    ("[wiki\n", "讀不了"),
])
def test_bad_config_fails_loudly(tmp_path, text, said):
    with pytest.raises(ConfigError, match=said.replace("[", r"\[").replace("]", r"\]")):
        Config.from_file(_write(tmp_path, text), tmp_path / "state")


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


def test_mac_without_config_file_refuses_when_it_is_not_the_owners_mac(tmp_path, monkeypatch):
    """公開 repo 沒有 owner_mac.py:Mac 朋友少放一個設定檔,不可安靜地用別人的路徑收件、寄別人的信。"""
    import wiki_feeder

    monkeypatch.setattr("wiki_feeder.config.PLATFORM", "darwin")
    monkeypatch.setitem(sys.modules, "wiki_feeder.owner_mac", None)    # 等於沒有這個檔
    monkeypatch.delattr(wiki_feeder, "owner_mac", raising=False)
    with pytest.raises(ConfigError, match="找不到設定檔.*install.sh"):
        Config.default()


def test_config_file_wins_over_owner_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("wiki_feeder.config.PLATFORM", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    state = tmp_path / "wiki-feeder"
    state.mkdir()
    (state / CONFIG_FILE).write_text(GOOD.format(root=tmp_path.as_posix()), encoding="utf-8")
    c = Config.default()
    assert c.futures is None and c.state_dir == state
