"""知識庫、原件資料夾在雲端同步資料夾裡(使用者 2026-10-27,spec §5.15):安裝時提醒、說明、建議換位置;
朋友堅持照用就把 git 的資料移出同步資料夾,先列後果、打 yes 才算。

偵測是純函式(平台、家目錄、環境變數、系統查得到的東西都當參數),Windows 的情況在 Mac 上模擬。
"""
from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

from wiki_feeder.config import Config
from wiki_feeder.syncdirs import (BOX, DROPBOX, GDRIVE, ICLOUD, ICLOUD_DESKTOP, ONEDRIVE, ONEDRIVE_DESKTOP, OTHER,
                                  Probe, sync_kind)

ROOT = Path(__file__).parents[1]
MAC_HOME = "/Users/amy"
WIN_HOME = r"C:\Users\amy"
OFF = Probe(finder={"FXICloudDriveDesktop": "0", "FXICloudDriveDocuments": "0"})


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ws = _mod("winsetup")


@pytest.mark.parametrize("path,kind", [
    ("/Users/amy/Library/CloudStorage/OneDrive-個人/WIKI", ONEDRIVE),
    ("/Users/amy/Library/CloudStorage/OneDrive-SharedLibraries-公司/WIKI", ONEDRIVE),
    ("/Users/amy/Library/CloudStorage/Dropbox/WIKI", DROPBOX),
    ("/Users/amy/Library/CloudStorage/GoogleDrive-amy/我的雲端硬碟/WIKI", GDRIVE),
    ("/Users/amy/Library/CloudStorage/Box-Box/WIKI", BOX),
    ("/Users/amy/Library/CloudStorage/pCloudDrive/WIKI", OTHER),
    ("/Users/amy/Library/Mobile Documents/com~apple~CloudDocs/WIKI", ICLOUD),
    ("/Users/amy/Dropbox/WIKI", DROPBOX),
    ("/Users/amy/Google Drive/WIKI", GDRIVE),
])
def test_every_kind_of_mac_sync_folder_is_noticed(path, kind):
    assert sync_kind(path, "darwin", MAC_HOME, {}, OFF) == kind


def test_mac_documents_and_desktop_count_unless_icloud_says_no():
    """iCloud「桌面與文件」:Finder 設定是 1 或讀不到都提醒(查不準寧可提醒),明確是 0 才不提醒。"""
    for p in ("/Users/amy/Documents/WIKI", "/Users/amy/Desktop/LLMWiki/Raw_Sources"):
        assert sync_kind(p, "darwin", MAC_HOME, {}, OFF) is None
        assert sync_kind(p, "darwin", MAC_HOME, {}, Probe()) == ICLOUD_DESKTOP
        on = Probe(finder={"FXICloudDriveDesktop": "1", "FXICloudDriveDocuments": "1"})
        assert sync_kind(p, "darwin", MAC_HOME, {}, on) == ICLOUD_DESKTOP


@pytest.mark.parametrize("path,env,probe,kind", [
    (r"C:\Users\amy\OneDrive\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"}, Probe(), ONEDRIVE),
    (r"c:\users\AMY\onedrive - 公司\WIKI", {"OneDriveCommercial": r"C:\Users\amy\OneDrive - 公司"}, Probe(), ONEDRIVE),
    (r"D:\OD\WIKI", {"OneDriveConsumer": r"D:\OD"}, Probe(), ONEDRIVE),
    (r"D:\OD\WIKI", {"ONEDRIVE": r"D:\OD"}, Probe(), ONEDRIVE),       # Windows 上 dict(os.environ) 的鍵是全大寫
    # 「文件」「桌面」被 OneDrive 接管:實際位置(選擇視窗、檔案總管左邊欄給的)提醒;資料夾名照 Windows 的語言
    (r"C:\Users\amy\OneDrive\文件\WIKI", {}, Probe(known={"Documents": r"C:\Users\amy\OneDrive\文件"}), ONEDRIVE_DESKTOP),
    (r"C:\Users\amy\OneDrive\Documents\WIKI", {}, Probe(known={"Documents": r"C:\Users\amy\OneDrive\Documents"}),
     ONEDRIVE_DESKTOP),
    (r"C:\Users\amy\OneDrive\Desktop\WIKI", {}, Probe(known={"Desktop": r"C:\Users\amy\OneDrive\Desktop"}), ONEDRIVE_DESKTOP),
    (r"C:\Users\amy\iCloudDrive\WIKI", {}, Probe(), ICLOUD),
    (r"E:\Dropbox (公司)\WIKI", {}, Probe(dropbox=(r"E:\Dropbox (公司)",)), DROPBOX),
    (r"C:\Users\amy\Dropbox\WIKI", {}, Probe(), DROPBOX),
    (r"G:\我的雲端硬碟\WIKI", {}, Probe(), GDRIVE),
    (r"G:\Shared\WIKI", {}, Probe(labels={"G:": "Google Drive"}), GDRIVE),
    (r"C:\Users\amy\Google Drive\WIKI", {}, Probe(), GDRIVE),
    (r"C:\Users\amy\Box\WIKI", {}, Probe(), BOX),
])
def test_every_kind_of_windows_sync_folder_is_noticed(path, env, probe, kind):
    assert sync_kind(path, "win32", WIN_HOME, env, probe) == kind


@pytest.mark.parametrize("platform,home,path,env,probe", [
    ("darwin", MAC_HOME, "/Users/amy/LLMWiki/WIKI", {}, OFF),
    ("darwin", MAC_HOME, "/Users/amy/SOURCE5/Raw_Sources", {}, Probe()),
    ("darwin", MAC_HOME, "/Users/amy/Library/CloudStorageX/WIKI", {}, OFF),
    ("win32", WIN_HOME, r"C:\Users\amy\LLMWiki\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"},
     Probe(known={"Documents": r"C:\Users\amy\OneDrive\文件"})),
    # 「文件」沒被接管:字面上的 Documents 就是本機的
    ("win32", WIN_HOME, r"C:\Users\amy\Documents\WIKI", {}, Probe(known={"Documents": r"C:\Users\amy\Documents"})),
    # 被接管了:字面上的 %USERPROFILE%\Documents、Desktop 是另一個本機資料夾,不會被同步(2026-10-28 Windows 11 實測)。
    # 英文版 Windows 兩邊都叫 Documents,更容易看成同一個
    ("win32", WIN_HOME, r"C:\Users\amy\Documents\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"},
     Probe(known={"Documents": r"C:\Users\amy\OneDrive\文件"})),
    ("win32", WIN_HOME, r"C:\Users\amy\Documents\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"},
     Probe(known={"Documents": r"C:\Users\amy\OneDrive\Documents"})),
    ("win32", WIN_HOME, r"C:\Users\amy\Desktop\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"},
     Probe(known={"Desktop": r"C:\Users\amy\OneDrive\Desktop"})),
    ("win32", WIN_HOME, r"C:\Users\amy\OneDriveBackup\WIKI", {"OneDrive": r"C:\Users\amy\OneDrive"}, Probe()),
])
def test_ordinary_folders_are_not_flagged(platform, home, path, env, probe):
    assert sync_kind(path, platform, home, env, probe) is None


def test_mac_probe_counts_icloud_desktop_folder_as_on(tmp_path, monkeypatch):
    """Finder 設定讀成 0,iCloud 雲碟裡卻有 Desktop(功能是開著的):照樣當成打開。"""
    from wiki_feeder import syncdirs
    monkeypatch.setattr(syncdirs, "_finder", lambda key: "0")
    assert syncdirs.probe("darwin", {}, tmp_path).finder == {"FXICloudDriveDesktop": "0", "FXICloudDriveDocuments": "0"}
    (tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop").mkdir(parents=True)
    assert syncdirs.probe("darwin", {}, tmp_path).finder["FXICloudDriveDesktop"] == "1"


def test_windows_probe_never_crashes_the_installer(monkeypatch):
    """查 Known Folder、磁碟標籤出任何錯(ctypes 的 ArgumentError 之類):不提醒那一種,不讓安裝當掉。"""
    from wiki_feeder import syncdirs

    def boom():
        raise RuntimeError("ctypes")
    monkeypatch.setattr(syncdirs, "_known_folders", boom)
    monkeypatch.setattr(syncdirs, "_drive_labels", boom)
    assert syncdirs.probe("win32", {}) == Probe()


# -- 安裝問答 ----------------------------------------------------------------------------

def _answers(monkeypatch, *answers: str) -> list:
    it, asked = iter(answers), []
    monkeypatch.setattr("builtins.input", lambda *a: (asked.append(a[0] if a else ""), next(it))[1])
    return asked


def _synced(*roots: Path):
    """roots 底下的都當成在 iCloud 雲碟裡(真的偵測在上面測過;這裡測問答怎麼接)。"""
    return lambda p: ICLOUD if any(Path(p).is_relative_to(r) for r in roots) else None


def _new_wiki(tmp_path, monkeypatch, synced: Path, *answers: str) -> tuple[str, str, dict]:
    monkeypatch.setattr(ws, "sync_kind_of", _synced(synced))
    monkeypatch.setattr(ws, "scaffold_wiki", lambda claude, w, r, windows: (
        (w / "CLAUDE.md").write_text("# 規則\n", encoding="utf-8"), (True, "ok"))[-1])
    out: dict = {}
    w, r = ws.ask_wiki(str(synced / "WIKI"), Path("/x/claude"), False, out)
    return w, r, out


def test_choosing_another_place_keeps_git_in_the_wiki(tmp_path, monkeypatch, capsys):
    """直接按 Enter = 換位置:再問一次知識庫,換到不同步的地方就照常,不關 git。"""
    cloud, home = tmp_path / "cloud", tmp_path / "LLMWiki"
    # 知識庫(預設在同步資料夾)、換位置、新位置、建立、原件資料夾、建立、請 claude 建、補 git 那一節
    asked = _answers(monkeypatch, "", "", str(home / "WIKI"), "", "", "", "", "")
    w, r, out = _new_wiki(tmp_path, monkeypatch, cloud)
    assert w == str(home / "WIKI") and out == {}
    said = capsys.readouterr().out
    assert "iCloud 雲碟" in said and "衝突副本" in said and "LLMWiki" in said    # 說了哪一種、為什麼、建議去哪
    assert not (cloud / "WIKI").exists()                                       # 換位置之前沒先建資料夾
    assert len(asked) == 8


def test_keeping_a_synced_wiki_needs_the_word_yes(tmp_path, monkeypatch, capsys):
    """選 2 之後只按 Enter(或打別的)不算:回到重選;打 yes 才照用,原因記下來。"""
    cloud = tmp_path / "cloud"
    _answers(monkeypatch, "", "2", "", str(tmp_path / "LLMWiki" / "WIKI"), "", "", "", "", "")
    _, _, out = _new_wiki(tmp_path, monkeypatch, cloud)
    assert out == {}
    _answers(monkeypatch, "", "2", "YES", "", "", "2", "", "", "")   # 旁邊的原件資料夾也在同步資料夾:照用
    w, r, out = _new_wiki(tmp_path, monkeypatch, cloud)
    assert w == str(cloud / "WIKI")
    assert re.fullmatch(r"iCloud 雲碟:.*WIKI\(\d{4}-\d\d-\d\d\)", out["git_outside_reason"])
    said = capsys.readouterr().out
    for e in ws.GIT_OUTSIDE_EFFECTS:                                           # 打 yes 之前每一條後果都列了
        assert ws.L(e) in said


def test_raw_sources_in_a_sync_folder_is_checked_too_but_does_not_move_git(tmp_path, monkeypatch, capsys):
    """只有原件資料夾在同步資料夾裡:一樣提醒;照樣用不必打 yes,也不動 git(.git 在知識庫裡)。"""
    cloud = tmp_path / "cloud"
    monkeypatch.setattr(ws, "sync_kind_of", _synced(cloud))
    monkeypatch.setattr(ws, "scaffold_wiki", lambda claude, w, r, windows: (
        (w / "CLAUDE.md").write_text("# 規則\n", encoding="utf-8"), (True, "ok"))[-1])
    out: dict = {}
    _answers(monkeypatch, "", "", str(cloud / "Raw_Sources"), "2", "", "", "")
    w, r = ws.ask_wiki(str(tmp_path / "LLMWiki" / "WIKI"), Path("/x/claude"), False, out)
    assert r == str(cloud / "Raw_Sources") and out == {}
    assert "衝突副本" in capsys.readouterr().out


def test_existing_wiki_in_a_sync_folder_is_not_moved_by_the_installer(tmp_path, monkeypatch, capsys):
    """已經有的知識庫選換位置:教他搬、重跑,安裝程式不自己搬檔。"""
    cloud = tmp_path / "cloud"
    w = cloud / "WIKI"
    (w / "Wiki_Pages").mkdir(parents=True)
    (cloud / "Raw_Sources").mkdir()
    (w / "CLAUDE.md").write_text("原件放在 ../Raw_Sources/\n", encoding="utf-8")
    monkeypatch.setattr(ws, "sync_kind_of", _synced(cloud))
    _answers(monkeypatch, "", "", "")                 # 有知識庫、CLAUDE.md 用預設、換位置
    with pytest.raises(SystemExit):
        ws.ask_library("", w, None, False, {})
    assert "重跑" in capsys.readouterr().out and (w / "CLAUDE.md").exists()

    out: dict = {}
    asked = _answers(monkeypatch, "", "", "2", "yes", "", "2", "")   # 知識庫照用、對、原件資料夾照用、補 git 那一節
    got = ws.ask_library("", w, None, False, out)
    assert len(asked) == 7                                    # 原件資料夾也問了
    assert got[0] == str(w.resolve()) and out["git_outside_reason"]


def test_config_records_git_outside_and_the_reason(tmp_path):
    a = {"wiki": str(tmp_path / "W"), "raw": str(tmp_path / "R"), "icloud": str(tmp_path / "I"), "doc2md": "x",
         "git_outside_reason": "iCloud 雲碟:/x/WIKI(2026-10-27)"}
    text = ws.render_config(a)
    assert tomllib.loads(text)["wiki"]["git_outside"] is True
    cfg = ws.write_config(text, tmp_path / "state")
    assert cfg.repo(cfg.target_repo).git_outside
    a.pop("git_outside_reason")
    assert "git_outside" not in ws.render_config(a)
    assert not ws.write_config(ws.render_config(a), tmp_path / "s2").repo("main").git_outside


def test_config_reader_rejects_a_non_boolean_git_outside(tmp_path):
    from wiki_feeder.config import ConfigError
    p = tmp_path / "config.toml"
    p.write_text(f"[inbox]\nicloud = '{tmp_path}'\n[wiki]\ndir = '{tmp_path}'\nraw = '{tmp_path}'\n"
                 f"git_outside = 'yes'\n[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.from_file(p, tmp_path)
