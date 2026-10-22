"""公開 repo 的 README 與安裝說明(本 repo 的 public/,發佈時放到根目錄):連結、指令要跟實際的檔案對得上。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
# 本 repo 放在 public/,公開 repo 放在根目錄(發佈腳本去掉 public/)
PUBLIC = ROOT / "public" if (ROOT / "public").is_dir() else ROOT
ONE_LINER = "curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash"


# 三種語言(spec §10):每一份都有繁中、簡中、英文版,頁首互相連結;README 各自連到同語言的安裝說明
READMES = ("README.md", "README.zh-Hans.md", "README.en.md")
GUIDES = {"mac": ("Mac-Install-Guide.zh-Hant.md", "Mac-Install-Guide.zh-Hans.md", "Mac-Install-Guide.md"),
          "win": ("Windows-Install-Guide.zh-Hant.md", "Windows-Install-Guide.zh-Hans.md", "Windows-Install-Guide.md")}


def _head(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8").split("\n## ", 1)[0]


def test_readme_in_three_languages_links_to_its_guides_and_states_the_license():
    for i, name in enumerate(READMES):
        text = (PUBLIC / name).read_text(encoding="utf-8")
        assert "All rights reserved" in text, name
        assert all(f"]({other})" in _head(name) for other in READMES if other != name), name
        assert GUIDES["mac"][i] in text and GUIDES["win"][i] in text, name


def test_the_one_line_install_matches_install_sh():
    """README 與 Mac 安裝說明貼的那一行、install.sh 自己註解裡的那一行、它 clone 的 repo,四處要是同一個。"""
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert ONE_LINER in sh and 'repo_url="https://github.com/VincentLiang1/wiki-agent.git"' in sh
    for doc in (*READMES, *GUIDES["mac"]):
        assert ONE_LINER in (PUBLIC / doc).read_text(encoding="utf-8"), doc


def test_every_public_md_links_resolve():
    for md in PUBLIC.glob("*.md"):
        for name in re.findall(r"\]\(([^)#:]+\.md)\)", md.read_text(encoding="utf-8")):
            assert (PUBLIC / name).is_file(), (md.name, name)


def test_each_guide_links_to_its_other_two_languages():
    for trio in GUIDES.values():
        for name in trio:
            assert all(f"]({other})" in _head(name) for other in trio if other != name), name


def test_entry_files_and_guides_have_english_names():
    """朋友雙擊、執行的入口與說明的檔名一律英文(使用者 2026-10-22:多語系版本的安裝檔是中文檔名,
    看不懂中文的朋友找不到要點哪一個;比照 meeting-scribe-native)。內容照樣三種語言。"""
    entries = [p.name for p in ROOT.iterdir() if p.suffix in (".bat", ".command", ".sh")]
    assert entries and all(n.isascii() for n in entries), entries
    docs = [p.name for p in PUBLIC.glob("*.md")]
    assert docs and all(n.isascii() for n in docs), docs


def test_simplified_docs_link_to_simplified_guides():
    """簡中 README 與說明的內文只連到簡中那份說明(頁首的語言切換列除外)。"""
    for name in ("README.zh-Hans.md", GUIDES["mac"][1], GUIDES["win"][1]):
        body = (PUBLIC / name).read_text(encoding="utf-8").split("\n", 3)[3]
        assert ".zh-Hant.md" not in body, name


def test_guides_name_the_files_that_really_exist():
    for zh_or_en in GUIDES["mac"]:
        mac = (PUBLIC / zh_or_en).read_text(encoding="utf-8")
        for name in ("Update.command", "Remove-Schedule.command"):
            assert name in mac and (ROOT / name).is_file()
        assert "scribe2md-mac.zip" in mac
    for zh_or_en in GUIDES["win"]:
        win = (PUBLIC / zh_or_en).read_text(encoding="utf-8")
        for name in ("Install.bat", "Update.bat", "Remove-Schedule.bat"):
            assert name in win and (ROOT / name).is_file()
        assert "scribe2md-win.zip" in win
