"""公開 repo 的 README 與安裝說明(本 repo 的 public/,發佈時放到根目錄):連結、指令要跟實際的檔案對得上。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
# 本 repo 放在 public/,公開 repo 放在根目錄(發佈腳本去掉 public/)
PUBLIC = ROOT / "public" if (ROOT / "public").is_dir() else ROOT
ONE_LINER = "curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash"


# 三種語言(spec §10):每一份都有繁中、簡中、英文版,頁首互相連結;README 各自連到同語言的安裝說明
# 檔名比照 scribe2md(使用者 2026-10-23):X.md 英文是預設、X.zh-TW.md 繁中、X.zh-CN.md 簡中
READMES = ("README.zh-TW.md", "README.zh-CN.md", "README.md")
GUIDES = {"mac": ("Mac-Install-Guide.zh-TW.md", "Mac-Install-Guide.zh-CN.md", "Mac-Install-Guide.md"),
          "win": ("Windows-Install-Guide.zh-TW.md", "Windows-Install-Guide.zh-CN.md", "Windows-Install-Guide.md")}
# 〈什麼是 LLM Wiki〉:會議助手 App「送進知識庫」連到這三個檔名(使用者 2026-10-24),改名要一起改 App
WHAT_IS = ("What-is-LLM-Wiki.zh-TW.md", "What-is-LLM-Wiki.zh-CN.md", "What-is-LLM-Wiki.md")
# 〈會議助手全套服務架構〉:內容對齊 iOS 設定 › 關於(使用者 2026-11-09),README 開頭連過去
OVERVIEW = ("How-Notetaker-Fits-Together.zh-TW.md", "How-Notetaker-Fits-Together.zh-CN.md", "How-Notetaker-Fits-Together.md")
# 〈Scribe2MD〉:是什麼、怎麼取得(使用者 2026-11-10 定案:核心不給人單獨裝,要用就裝電腦版)
SCRIBE2MD = ("Scribe2MD.zh-TW.md", "Scribe2MD.zh-CN.md", "Scribe2MD.md")


def _head(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8").split("\n## ", 1)[0]


def test_readme_in_three_languages_links_to_its_guides_and_states_the_license():
    for i, name in enumerate(READMES):
        text = (PUBLIC / name).read_text(encoding="utf-8")
        assert "All rights reserved" in text, name
        assert all(f"]({other})" in _head(name) for other in READMES if other != name), name
        assert GUIDES["mac"][i] in text and GUIDES["win"][i] in text, name
        assert f"]({WHAT_IS[i]})" in text, name   # 「LLM Wiki」連到同語言的〈什麼是 LLM Wiki〉
        assert f"]({OVERVIEW[i]})" in text, name  # 跟手機 App、電腦版的關係連到同語言的〈會議助手全套服務架構〉


def test_the_one_line_install_matches_install_sh():
    """README 與 Mac 安裝說明貼的那一行、install.sh 自己註解裡的那一行、它 clone 的 repo,四處要是同一個。"""
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert ONE_LINER in sh and 'repo_url="https://github.com/VincentLiang1/wiki-agent.git"' in sh
    for doc in (*READMES, *GUIDES["mac"]):
        assert ONE_LINER in (PUBLIC / doc).read_text(encoding="utf-8"), doc


def test_every_public_md_links_resolve():
    for md in PUBLIC.glob("*.md"):
        # `[名稱](路徑.md)` 這種寫在程式碼格式裡的是語法範例(〈什麼是 LLM Wiki〉的規則檔一節),不是連結
        text = re.sub(r"`[^`\n]*`", "", md.read_text(encoding="utf-8"))
        for name in re.findall(r"\]\(([^)#:]+\.md)\)", text):
            assert (PUBLIC / name).is_file(), (md.name, name)


def test_each_guide_links_to_its_other_two_languages():
    for trio in (*GUIDES.values(), WHAT_IS, OVERVIEW, SCRIBE2MD):
        for name in trio:
            assert all(f"]({other})" in _head(name) for other in trio if other != name), name


def test_overview_shows_the_diagram_in_its_own_language():
    """〈會議助手全套服務架構〉的架構圖是 SVG(2026-11-09 使用者嫌 Mermaid 醜),每種語言連自己那張。"""
    for name in OVERVIEW:
        svg = name[:-len(".md")] + ".svg"
        assert f"]({svg})" in (PUBLIC / name).read_text(encoding="utf-8") and (PUBLIC / svg).is_file(), name


def test_entry_files_and_guides_have_english_names():
    """朋友雙擊、執行的入口與說明的檔名一律英文(使用者 2026-10-22:多語系版本的安裝檔是中文檔名,
    看不懂中文的朋友找不到要點哪一個;比照 meeting-scribe-native)。內容照樣三種語言。"""
    entries = [p.name for p in ROOT.iterdir() if p.suffix in (".bat", ".command", ".sh")]
    assert entries and all(n.isascii() for n in entries), entries
    docs = [p.name for p in PUBLIC.glob("*.md")]
    assert docs and all(n.isascii() for n in docs), docs


def test_simplified_docs_link_to_simplified_guides():
    """簡中 README 與說明的內文只連到簡中那份說明(頁首的語言切換列除外)。"""
    for name in ("README.zh-CN.md", GUIDES["mac"][1], GUIDES["win"][1], WHAT_IS[1], OVERVIEW[1], SCRIBE2MD[1]):
        body = (PUBLIC / name).read_text(encoding="utf-8").split("\n", 3)[3]
        assert ".zh-TW.md" not in body, name


def test_docs_no_longer_send_friends_to_the_old_scribe2md_download():
    """2026-11-07 起 Scribe2MD 核心由安裝程式從 wiki-agent 的 Release 下載(spec §4.9);舊的 scribe2md repo 停在橋接版,
    說明書不可再叫朋友去那裡下載 zip、自己解壓到 C:\\scribe2md。"""
    for f in PUBLIC.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        assert "scribe2md/releases" not in text and "scribe2md-mac.zip" not in text and "scribe2md-win.zip" not in text, f.name


def test_docs_use_the_public_app_names():
    """iPhone App 對外叫「會議助手」/ Notetaker(2026-10-16 起),電腦版叫「會議助手電腦版」/ Notetaker Desktop;
    scribe2md 只是 bundle id 與 repo 這些內部名稱,說明書不可再叫朋友去開「scribe2md App」(scribe2md-ios 2026-11-07)。"""
    for f in PUBLIC.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        for bad in ("scribe2md iPhone app", "scribe2md app", "scribe2md App", "[scribe2md sync folder]", "【scribe2md 同步資料夾】"):
            assert bad not in text, f"{f.name}:{bad}"


def test_guides_name_the_files_that_really_exist():
    for zh_or_en in GUIDES["mac"]:
        mac = (PUBLIC / zh_or_en).read_text(encoding="utf-8")
        for name in ("Update.command", "Remove-Schedule.command"):
            assert name in mac and (ROOT / name).is_file()
        assert "Scribe2MD" in mac and "notetaker-desktop/releases" in mac
    for zh_or_en in GUIDES["win"]:
        win = (PUBLIC / zh_or_en).read_text(encoding="utf-8")
        for name in ("Install.bat", "Update.bat", "Remove-Schedule.bat"):
            assert name in win and (ROOT / name).is_file()
        assert "Scribe2MD" in win and "notetaker-desktop/releases" in win


def test_scribe2md_page_sends_people_to_notetaker_desktop_not_the_core_zip():
    """核心是 wiki-agent 的元件、不給人單獨裝(使用者 2026-11-10 定案,電腦版 docs/dev/publish.md §4.7):〈Scribe2MD〉
    叫人裝會議助手電腦版,不可再教人下載 scribe2md-core 的 zip、自己跑安裝程式;〈會議助手全套服務架構〉與 README 連到這一頁。"""
    for i, name in enumerate(SCRIBE2MD):
        text = (PUBLIC / name).read_text(encoding="utf-8")
        assert "notetaker-desktop/releases/latest" in text, name
        for bad in ("releases/download/scribe2md-core", "install.command", "install.ps1"):
            assert bad not in text, (name, bad)
        assert f"]({name})" in (PUBLIC / OVERVIEW[i]).read_text(encoding="utf-8"), OVERVIEW[i]
        assert f"]({name})" in (PUBLIC / READMES[i]).read_text(encoding="utf-8"), READMES[i]
