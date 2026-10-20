"""公開 repo 的 README 與安裝說明(本 repo 的 public/,發佈時放到根目錄):連結、指令要跟實際的檔案對得上。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
# 本 repo 放在 public/,公開 repo 放在根目錄(發佈腳本去掉 public/)
PUBLIC = ROOT / "public" if (ROOT / "public").is_dir() else ROOT
ONE_LINER = "curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash"


def test_readme_links_to_both_guides_and_states_the_license():
    text = (PUBLIC / "README.md").read_text(encoding="utf-8")
    for name in re.findall(r"\]\(([^)#:]+\.md)\)", text):
        assert (PUBLIC / name).is_file(), name
    assert "Mac安裝說明.md" in text and "Windows安裝說明.md" in text
    assert "All rights reserved" in text and "## English" in text
    # 頁首就看得到英文說明的連結(GitHub 把「## English」的錨點產生成 #english)
    assert "](#english)" in text.split("\n## ", 1)[0]


def test_the_one_line_install_matches_install_sh():
    """README 與 Mac 安裝說明貼的那一行、install.sh 自己註解裡的那一行、它 clone 的 repo,四處要是同一個。"""
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert ONE_LINER in sh and 'repo_url="https://github.com/VincentLiang1/wiki-agent.git"' in sh
    for doc in ("README.md", "Mac安裝說明.md"):
        assert ONE_LINER in (PUBLIC / doc).read_text(encoding="utf-8"), doc


def test_guides_name_the_files_that_really_exist():
    mac = (PUBLIC / "Mac安裝說明.md").read_text(encoding="utf-8")
    win = (PUBLIC / "Windows安裝說明.md").read_text(encoding="utf-8")
    for name in ("更新.command", "移除排程.command"):
        assert name in mac and (ROOT / name).is_file()
    for name in ("安裝.bat", "更新.bat", "移除排程.bat"):
        assert name in win and (ROOT / name).is_file()
    assert "scribe2md-mac.zip" in mac and "scribe2md-win.zip" in win
