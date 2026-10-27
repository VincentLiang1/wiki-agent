"""第一次安裝的問答(Windows,給朋友用):問收件匣、知識庫、doc2md、寄信,寫 config.toml、存寄信密碼、
跑一輪只列收件匣、裝排程。由 `Install.bat` 在 `uv sync` 之後叫:

    uv run python -X utf8 scripts\\winsetup.py [--no-schedule]

設定檔寫在 %LOCALAPPDATA%\\wiki-feeder\\config.toml(`state_dir_for`;實測時把 LOCALAPPDATA 指到假目錄、
加 --no-schedule,排程才不會跑到真的 %LOCALAPPDATA%)。

- 問答與寫檔放在 Python、不放 .bat:`set /p` 與 `echo` 碰到 & ( ! 與 Big5 以外的字就壞,也沒辦法測
- 路徑一律寫成 TOML 單引號字串(反斜線不跳脫);路徑裡有單引號就請朋友改名,不硬跳脫
- 寫進去之前先用真的 `Config.from_file` 讀一次,讀不了就不寫(不留一份程式讀不了的設定檔)
- 已有設定檔:先問要沿用還是重填,重跑安裝不會安靜地蓋掉
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wiki_feeder import i18n, syncdirs  # noqa: E402
from wiki_feeder.config import (CONFIG_FILE, DISCARD, INTAKE, LEGACY, LEGACY_PENDING, PENDING,  # noqa: E402
                                SYSTEM_DIRS, Config, ConfigError, custom_dir_ok, folder_names, state_dir_for)
from wiki_feeder.i18n import L, N_  # noqa: E402

SMTP_SERVICE = "wiki-feeder-smtp"
HEADER = N_("# wiki-feeder 設定檔(Install.bat 問答產生;要改就用記事本改,改完下一分鐘生效)")


# -- 設定檔(純函式,測試在 Mac 也跑) --------------------------------------------------

def toml_path(p: str) -> str:
    """路徑寫成 TOML 字面字串:單引號裡反斜線照原樣。不能有單引號與換行(字面字串跳脫不了)。"""
    if "'" in p or "\n" in p or "\r" in p:
        raise ValueError(L("路徑裡有單引號或換行,設定檔寫不進去:{p}(請把資料夾改名)", p=p))
    return f"'{p}'"


def toml_text(s: str) -> str:
    """一般文字(知識庫名稱、信箱)寫成 TOML 基本字串;json 的跳脫在 TOML 也成立。"""
    return json.dumps(s, ensure_ascii=False)


def render_config(a: dict) -> str:
    """問答結果 → config.toml 的內容。鍵與 Config.from_file 認得的一致,沒填的選填鍵不寫。
    第一行是註解(macsetup 換成 Mac 的那一行);[general] language 放最前面,沒給就用現在的介面語言。"""
    lines = [L(HEADER), "", "[general]", f"language = {toml_text(a.get('lang') or i18n.get_lang())}", "",
             "[inbox]"]
    for k in ("icloud", "onedrive"):
        if a.get(k):
            lines.append(f"{k} = {toml_path(a[k])}")
    # 系統資料夾名照原件資料夾現況(config.folder_names):ask_wiki 已經照它建好待處理資料夾,這裡再看一次結果相同
    names = a.get("folders") or folder_names(Path(a["raw"]))
    lines += ["", "[wiki]", f"dir = {toml_path(a['wiki'])}", f"raw = {toml_path(a['raw'])}",
              f"label = {toml_text(a.get('label') or L('知識庫'))}",
              f"pending = {toml_text(names[PENDING])}", f"discard = {toml_text(names[DISCARD])}",
              f"intake = {toml_text(names[INTAKE])}"]
    if a.get("git_outside_reason"):
        # 知識庫在同步資料夾裡、朋友堅持照用(§5.15):git 的資料放執行狀態目錄;原因留著,之後才知道為什麼這樣設
        lines += ["git_outside = true", f"git_outside_reason = {toml_text(a['git_outside_reason'])}"]
    lines += [
              "", "[mail]", f"from = {toml_text(a.get('mail_from', ''))}", f"to = {toml_text(a.get('mail_to', ''))}",
              "", "[tools]", f"doc2md = {toml_path(a['doc2md'])}"]
    if a.get("claude"):
        lines.append(f"claude = {toml_path(a['claude'])}")
    return "\n".join(lines) + "\n"


def write_config(text: str, state: Path) -> Config:
    """先寫暫存檔、用 Config.from_file 讀過,讀得了才改名成 config.toml;讀不了丟 ConfigError、不留檔。"""
    state.mkdir(parents=True, exist_ok=True)
    tmp = state / (CONFIG_FILE + ".new")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    try:
        cfg = Config.from_file(tmp, state)
    except ConfigError:
        tmp.unlink()
        raise
    tmp.replace(state / CONFIG_FILE)
    return cfg


# -- 找東西、驗東西 ---------------------------------------------------------------------

def find_icloud(home: Path) -> Path | None:
    for d in (home / "iCloudDrive", home / "iCloud Drive"):
        if d.is_dir():
            return d
    return None


def find_doc2md(roots: list[Path]) -> list[Path]:
    """meeting-scribe 解壓縮的位置不固定:在常見的地方往下找兩層的 .venv\\Scripts\\doc2md.exe。"""
    found: list[Path] = []
    for r in roots:
        for pat in ("*/.venv/Scripts/doc2md.exe", "*/*/.venv/Scripts/doc2md.exe"):
            try:
                found += [p for p in r.glob(pat) if p not in found]
            except OSError:
                pass
    return found


def check_doc2md(exe: Path) -> tuple[bool, str]:
    """真的轉一個小 .txt:要印出「執行記錄:」才算(舊版不印,程式會當成 doc2md 跑不起來)。"""
    if not exe.is_file():
        return False, L("找不到這個檔")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "安裝測試.txt"
        src.write_text("wiki-feeder 安裝測試\n", encoding="utf-8")
        try:
            r = subprocess.run([str(exe), str(src), "--out-dir", str(Path(d) / "out"), "--prune-days", "0"],
                               capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, L("執行失敗:{e}", e=e)
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    if "執行記錄" not in out:
        return False, L("沒有印出「執行記錄:」——這是舊版的 meeting-scribe,請裝新版(scribe2md)")
    return True, L("可以用")


def find_claude(home: Path) -> Path | None:
    p = shutil.which("claude")
    if p:
        return Path(p)
    p = home / ".local" / "bin" / "claude.exe"
    return p if p.is_file() else None


def claude_status(exe: Path) -> dict:
    try:
        r = subprocess.run([str(exe), "auth", "status"], capture_output=True, timeout=60)
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def claude_logged_in(exe: Path) -> bool:
    return bool(claude_status(exe).get("loggedIn"))


def mail_default(status: dict) -> str:
    """寄件 Gmail 的預設值:這台 Claude Code 登入的帳號是 Gmail 就用它(使用者 2026-10-20:每題都要有預設答案)。"""
    email = str(status.get("email") or "")
    return email if email.lower().endswith("@gmail.com") else ""


# 找現成的知識庫:先找使用者本人的擺法(SOURCE5\WIKI,他在新機器上安裝才找得到),再找幾個常見的地方
WIKI_GUESSES = ("SOURCE5/WIKI", "LLMWiki/WIKI", "Documents/WIKI", "Desktop/WIKI", "WIKI")


def find_wiki(home: Path, drives: tuple[Path, ...] = ()) -> Path | None:
    """第一個有 CLAUDE.md 的候選;Windows 另找各磁碟根目錄(使用者本人是 C:\\SOURCE5\\WIKI)。"""
    for base in (home, *drives):
        for g in WIKI_GUESSES:
            p = base / g
            if (p / "CLAUDE.md").is_file():
                return p
    return None


def default_wiki(home: Path) -> Path:
    """都找不到時新建的預設:家目錄的 LLMWiki\\WIKI(兩個平台同一個),沒有就幫忙建。
    不放 SOURCE5(使用者本人的擺法)、磁碟根目錄、文件／桌面(會被 OneDrive／iCloud 同步,弄壞 .git)(§10.2)。"""
    return home / "LLMWiki" / "WIKI"


# -- 雲端同步資料夾(使用者 2026-10-27,spec §5.15) ------------------------------------------
# 「不用擋下來、只需要提醒,說明原因,建議朋友換一個位置。如果硬要安裝,則必須關閉GIT,但是要告知關閉GIT的後果」;
# 關掉的做法定案為「git 的資料移出同步資料夾」(同日)。後果這幾句與 spec §5.15 的清單一字相同
# (tests/test_docs_index.py::test_sync_folder_effects_shown_to_friends_match_the_spec_word_for_word 守著)
WIKI_SYNC_WHY = N_("  同步程式會一直動這個資料夾裡的檔:檔案可能只留在雲端(程式要等它下載,或判成原件少一份而停下來),"
                   "別台裝置同時改會冒出衝突副本,知識庫的版本紀錄(git)被同步也會壞掉。建議換到家目錄的 LLMWiki。")
RAW_SYNC_WHY = N_("  同步程式會一直動這個資料夾裡的檔:檔案可能只留在雲端(程式要等它下載,或判成原件少一份而停下來),"
                  "別台裝置同時改會冒出衝突副本。建議換到家目錄的 LLMWiki。")
GIT_OUTSIDE_EFFECTS = (
    N_("版本紀錄(git)改放在這台電腦的 wiki-feeder 資料夾,知識庫裡只留一個叫 .git 的小檔指過去:不要刪它、不要改它"),
    N_("別台電腦同步到這個知識庫,看不到版本紀錄;那邊的 git 工具會說 .git 壞了,不用理它,也不要在別台電腦對這個資料夾用 git"),
    N_("備份或換電腦時,知識庫資料夾裡沒有版本紀錄,要另外備份這台電腦的 wiki-feeder 資料夾"),
    N_("只能有一台電腦的 wiki-agent 攝入這個知識庫:兩台都裝的話,兩邊的版本紀錄對不上,攝入會停住"),
    N_("同步資料夾的另外兩個問題不會因此消失:檔案只留在雲端時,程式要等它下載,或判成原件少一份而停下來;"
       "別台裝置同時改會冒出衝突副本,程式會當成你手動改的收進版本紀錄"),
)
CONFIRM_WORD = "yes"     # 三種語言同一個字;只按 Enter 不算(使用者 2026-10-27)
_PROBE: list = []


def sync_kind_of(p: Path) -> str | None:
    """p 在哪一種雲端同步資料夾裡(路徑先 resolve,含符號連結);系統只查一次。"""
    if not _PROBE:
        _PROBE.append(syncdirs.probe(sys.platform))
    try:
        p = Path(p).expanduser().resolve()
    except (OSError, RuntimeError):
        p = Path(p).expanduser()
    return syncdirs.sync_kind(p, sys.platform, Path.home(), dict(os.environ), _PROBE[0])


def keep_synced(p: Path, kind: str, wiki: bool) -> bool:
    """提醒 p 在同步資料夾裡、問要換位置還是照樣用;回 True = 照樣用。知識庫要照樣用,先列後果、打 yes 才算。"""
    say(L("  ⚠ {path} 在 {kind} 裡。", path=p, kind=L(kind)))
    say(L(WIKI_SYNC_WHY if wiki else RAW_SYNC_WHY))
    say(L("    1 = 換一個位置(建議)"))
    say(L("    2 = 照樣用這個位置,版本紀錄(git)的資料改放在這台電腦、不放在同步資料夾") if wiki
        else L("    2 = 照樣用這個位置"))
    if input(L("  選 1 或 2(直接按 Enter = 1):")).strip() != "2":
        return False
    if not wiki:
        return True
    say(L("  照樣用的話會這樣:"))
    for e in GIT_OUTSIDE_EFFECTS:
        say(f"  - {L(e)}")
    say(L("  (版本紀錄放在 {path})", path=state_dir_for(sys.platform, Path.home(), os.environ) / "wiki-git"))
    return input(L("  確定照樣用就打 {word} 後按 Enter(其他 = 換位置):", word=CONFIRM_WORD)).strip().lower() == CONFIRM_WORD


def outside_reason(p: Path, kind: str) -> str:
    return L("{kind}:{path}({day})", kind=L(kind), path=p, day=date.today().isoformat())


def move_first(p: Path) -> None:
    """已經有的知識庫要換位置:安裝程式不自己搬檔,教他搬、重跑。"""
    say(L("  請把 {path}(連同旁邊的原件資料夾)整個搬到家目錄的 LLMWiki 裡,再重跑一次安裝、貼新的位置。", path=p))
    raise SystemExit(1)


# -- 問答 ------------------------------------------------------------------------------

def say(msg: str = "") -> None:
    print(msg, flush=True)


def ask(prompt: str, default: str = "") -> str:
    hint = L("(直接按 Enter = {default})", default=default) if default else ""
    v = input(L("{prompt}{hint}:", prompt=prompt, hint=hint)).strip().strip('"')
    return v or default


def yes(prompt: str, default: bool = True) -> bool:
    v = input(L("{prompt}({choice}):", prompt=prompt, choice="Y/n" if default else "y/N")).strip().lower()
    return default if not v else v.startswith("y")


LANG_CHOICES = ("zh-Hant", "zh-Hans", "en")


def config_lang(path: Path) -> str | None:
    """設定檔裡的 [general] language;沒有檔、讀不了、沒寫或不認得都回 None。"""
    try:
        lang = tomllib.loads(path.read_text(encoding="utf-8-sig")).get("general", {}).get("language")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return None
    return lang if lang in i18n.LANGS else None


# 入口(Install.bat、install.sh、App 的 setup.zsh)一開始就問過語言、帶進來(使用者 2026-10-27:「一開始時確認語言後,
# 就只用使用者選定的語言顯示」):裝 git、uv 那幾步才不會先用系統語言印、問答才換成選的語言
LANG_ENV = "WIKI_AGENT_LANG"


def entry_lang(env=os.environ) -> str | None:
    """入口帶進來的語言(三種之一才算);開發時直接跑本檔沒有帶,照舊在問答第一題問。"""
    lang = env.get(LANG_ENV, "")
    if lang not in LANG_CHOICES:
        return None
    i18n.set_lang(lang)
    return lang


def lang_prompt(default: str) -> str:
    """選語言那一題(還不知道語言,三種寫法並列、不經 L)。三個入口印的是同一行(tests/test_winsetup.py 對照)。"""
    choices = "  ".join(f"{i} {i18n.NAMES[x]}" for i, x in enumerate(LANG_CHOICES, 1))
    return f"語言 / 语言 / Language:{choices}(Enter = {i18n.NAMES[default]}):"


def ask_lang(default: str) -> str:
    """問答的第一題(還不知道語言,三種寫法並列、不經 L)。選完 set_lang,之後的問答照它。"""
    if default not in LANG_CHOICES:
        default = i18n.SOURCE
    v = input(lang_prompt(default)).strip()
    lang = LANG_CHOICES[int(v) - 1] if v.isdigit() and 0 < int(v) <= len(LANG_CHOICES) else default
    i18n.set_lang(lang)
    return lang


def set_config_lang(text: str, lang: str) -> str:
    """沿用舊設定檔但換了語言:改 [general] language;舊檔沒有這一節就補在第一節之前。"""
    lines = text.splitlines()
    sect = None
    for i, ln in enumerate(lines):
        t = ln.strip()
        if t.startswith("["):
            sect = t
        elif sect == "[general]" and t.split("=", 1)[0].strip() == "language":
            lines[i] = f"language = {toml_text(lang)}"
            return "\n".join(lines) + "\n"
    new = ["[general]", f"language = {toml_text(lang)}"]
    if "[general]" in (ln.strip() for ln in lines):
        at = [ln.strip() for ln in lines].index("[general]") + 1
        lines[at:at] = new[1:]
    else:
        at = next((i for i, ln in enumerate(lines) if ln.strip().startswith("[")), len(lines))
        lines[at:at] = new + [""]
    return "\n".join(lines) + "\n"


def pick(prompt: str, folder: bool, default: str = "") -> str:
    """貼上路徑;直接按 Enter 開選擇視窗(有預設值時用預設值)。"""
    say(prompt)
    v = input(L("  貼上路徑後按 Enter(直接按 Enter = {default}):", default=default) if default
              else L("  貼上路徑後按 Enter,或直接按 Enter 開選擇視窗:")).strip().strip('"')
    if v or default:
        return str(Path(v or default))
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        v = filedialog.askdirectory(title=prompt) if folder else filedialog.askopenfilename(title=prompt)
        root.destroy()
    except Exception:          # 沒有 tkinter 或開不了視窗:改回打字
        v = input(L("  開不了選擇視窗,請貼上路徑:")).strip().strip('"')
    return str(Path(v)) if v else ""


def ask_inbox(home: Path) -> str:
    icloud = find_icloud(home)
    default = str(icloud / "_WikiBox") if icloud else ""
    if not icloud:
        say(L("⚠ 找不到 iCloud 雲碟(%USERPROFILE%\\iCloudDrive)。請先裝 iCloud for Windows、打開「iCloud 雲碟」。"))
    while True:
        p = Path(pick(L("【收件匣】iPhone 丟檔進來的資料夾(iCloud 雲碟裡的 _WikiBox)"), True, default))
        if p.parent.is_dir():
            break
        say(L("  找不到 {path},請再確認", path=p.parent))
    if not p.is_dir() and yes(L("  {path} 還沒有,要建立嗎?", path=p)):
        p.mkdir()
    # 「永遠保留在此裝置上」:收件匣裡的檔才會真的下載下來(程式碰到佔位檔也會自己要求下載,這是先做好的保險)
    subprocess.run(["attrib", "+P", str(p)], capture_output=True)
    return str(p)


# 知識庫還沒建:照〈LLM Wiki 新手教學講義-桌面版〉第三步的建庫提示詞,請 claude 在 WIKI 裡搭骨架
# (使用者 2026-10-20:「給的目錄不存在也幫忙建立,包含 CLAUDE.md」)。原文是 Windows 的路徑寫法,Mac 換成 /
# 三種語言:知識庫用安裝時選的語言建(英文版另寫,簡中版整段手寫在 hans 覆寫裡)
HANDOUT_PROMPT = N_("""請根據 Andrej Karpathy 的 LLM Wiki 設計模式,在這個資料夾裡幫我建立一套個人知識庫系統。
- 原始資料在 {raw}(我放、你只讀不改),底下的 {pending}\\ 是統一入口:
  我新丟的檔案一律先進 {pending}\\;你攝入前要先判讀內容歸屬,把檔案 mv 到 {raw} 底下
  對應的主題子目錄(子目錄命名對齊 Wiki_Pages\\ 的群組)再開始編頁,頁面裡標的來源路徑寫
  搬移後的位置,攝入完 {pending}\\ 必須是空的。把這套分流流程明文寫進 CLAUDE.md
- 我的電腦裝了 doc2md 這個轉檔 Skill。{raw}{pending}\\ 裡若有 PDF、Word、PowerPoint、
  Excel、掃描件、圖片、郵件、錄音錄影或 EPUB 電子書,攝入前一律先用它轉成 Markdown 再讀,
  不要直接讀二進位檔;轉出來的 md 放這個資料夾底下的 .md_cache\\(中間產物),
  不要寫回 {raw}。這條也要寫進 CLAUDE.md
- Wiki_Pages\\ 放你編譯出來的 Markdown 筆記,含一個 index.md 目錄索引
- 根目錄寫一份 CLAUDE.md,定義你的角色(知識編譯器)、攝入/查詢/健檢的工作流程、繁體中文與 Markdown 的品質標準
- 我不使用 Obsidian。所有頁面互連(含 index.md)一律用標準 Markdown 連結 [名稱](路徑.md),
  禁止使用 Obsidian 的 wikilink 語法 [[名稱]],並把這條規則明文寫進 CLAUDE.md 的品質標準

這是安裝程式在背景替我送的,沒有人能回答問題:偏好問題一律照你的建議做,不要停下來問。
只在這個資料夾裡建檔;不要動 {raw}、不要執行 git(版本紀錄由另一支程式代管)。
建好之後,用兩三句白話說你建了什麼。""")
# 資料夾裡已經有東西(只是缺 CLAUDE.md)時多給的一句;程式另外比對、改到的一律還原
KEEP_EXISTING = N_("\n這個資料夾裡已經有一些檔:已經有的檔一個都不要改、不要刪,只補缺的。")

# 講義沒有 git 的部分:朋友的庫由 wiki-feeder 代管 git(spec §5.13),這一節由程式固定補在 CLAUDE.md 最後,
# 不交給 claude 寫——它自己 commit 一筆,下一輪攝入就因「本機有沒驗證過的 commit」STOP(§5.6)
GIT_HEADING = N_("## 版本紀錄(wiki-feeder 代管 git)")
GIT_BODY = N_("""這個資料夾的版本紀錄由 wiki-feeder 用 git 代管:第一次自動攝入時它會 `git init`,每一筆攝入一個 commit,
另外在它的執行狀態目錄留一份備份。iPhone 丟進收件匣的檔,wiki-feeder 會自動轉寫、放進原件資料夾的 `{pending}`、照本檔攝入。

- **不要自己執行 git**(init、add、commit、push、reset、checkout、stash 都不要),也不要動 `.git/`:
  wiki-feeder 只接受它自己驗證過的 commit,多出一筆別人的 commit,自動攝入會整個停下來等人處理
- 手動改的頁直接存檔就好,不必 commit:下一次自動攝入前,wiki-feeder 會先把它們存成一筆「手動修改快照」
- 自動攝入的 commit message 格式:`攝入:<原件檔名>——一句摘要`,body 列這次新增、擴充了哪些頁
- 要看某一頁的歷史、或要還原到之前的版本:告訴使用者,請他找幫他安裝 wiki-feeder 的人處理,不要自己動 git
""")


def git_section(pending: str = PENDING) -> str:
    return "\n" + L(GIT_HEADING) + "\n\n" + L(GIT_BODY, pending=pending)


def has_git_section(text: str) -> bool:
    """三種語言的標題都算(換了語言重跑安裝,不再補一次)。"""
    return any(h in text for h in i18n.variants(GIT_HEADING))


def raw_ref(wiki: Path, raw: Path, windows: bool) -> str:
    """提示詞裡的原件資料夾:與 WIKI 並排就照講義寫相對路徑,不然寫完整路徑。"""
    sep = "\\" if windows else "/"
    return f"..{sep}{raw.name}{sep}" if raw.parent == wiki.parent else f"{raw}{sep}"


def handout_prompt(wiki: Path, raw: Path, windows: bool) -> str:
    text = L(HANDOUT_PROMPT, raw=raw_ref(wiki, raw, windows), pending=folder_names(raw)[PENDING])
    return text if windows else text.replace("\\", "/")


def add_git_section(wiki: Path, pending: str = PENDING) -> bool:
    """CLAUDE.md 最後補上代管 git 的一節;已經有就不動。回傳有沒有補。"""
    p = wiki / "CLAUDE.md"
    text = p.read_text(encoding="utf-8-sig")
    if has_git_section(text):
        return False
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if text.endswith("\n") else "\n") + git_section(pending))
    return True


def add_glossary_section(wiki: Path) -> bool:
    """CLAUDE.md 最後補上名詞校正表那一節(spec §5.14;使用者 2026-10-24:對照表是平常跟 AI 說哪場會議哪裡寫錯、
    一點一點累積的,朋友開 Claude 桌面版說「這裡寫錯」時讀的是 CLAUDE.md)。已經有就不動。回傳有沒有補。"""
    from wiki_feeder import glossary
    p = wiki / "CLAUDE.md"
    text = p.read_text(encoding="utf-8-sig")
    if glossary.has_rule(text):
        return False
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if text.endswith("\n") else "\n") + glossary.rule_section(i18n.get_lang()))
    return True


def offer_glossary_section(wiki: Path) -> None:
    """設定確定之後才問(兩個平台的 main 都叫):沿用舊設定檔重跑安裝不會走 ask_wiki,放在那裡的話「當時沒補就重跑安裝」不成立。"""
    from wiki_feeder import glossary
    p = wiki / "CLAUDE.md"
    if p.is_file() and not glossary.has_rule(p.read_text(encoding="utf-8-sig", errors="replace")) and yes(
            L("  要在 CLAUDE.md 最後補上「名詞校正表」這一節嗎?(你跟 Claude 說會議頁哪裡寫錯時,它會順手記下來,"
              "手機的會議草稿就跟著改;建議要)")):
        add_glossary_section(wiki)
        say(L("  ✓ 已補上"))


def _existing(wiki: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in wiki.rglob("*") if p.is_file() and ".git" not in p.relative_to(wiki).parts}


def ignore_md_cache(wiki: Path) -> bool:
    """講義的規則把轉檔的中間產物放在 WIKI 的 .md_cache/:程式代管 git 時會被「手動修改快照」整包收進去,
    庫越長越大。.gitignore 補一行排除;已經有就不動。回傳有沒有補。"""
    p = wiki / ".gitignore"
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    if any(ln.strip() in (".md_cache", ".md_cache/", "/.md_cache/") for ln in text.splitlines()):
        return False
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + ".md_cache/\n")
    return True


def scaffold_wiki(claude: Path, wiki: Path, raw: Path, windows: bool, run=subprocess.run) -> tuple[bool, str]:
    """照講義請 claude 建 CLAUDE.md、Wiki_Pages/index.md。只給讀寫檔案的工具(不給 Bash):它只需要建檔。
    已經有的檔絕不覆蓋(使用者 2026-10-20:原本可能已經有知識庫的建置):先記下內容,建完被改到、刪掉的照原樣寫回。"""
    wiki.mkdir(parents=True, exist_ok=True)
    (raw / folder_names(raw)[PENDING]).mkdir(parents=True, exist_ok=True)
    before = _existing(wiki)
    args = [str(claude), "-p", "--output-format", "json", "--no-session-persistence", "--max-budget-usd", "3",
            "--permission-mode", "acceptEdits", "--tools", "Read,Write,Edit,Glob,Grep",
            "--allowedTools", "Read", "Glob", "Grep"]
    try:
        r = run(args, cwd=wiki, input=handout_prompt(wiki, raw, windows) + (L(KEEP_EXISTING) if before else ""),
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
    except (OSError, subprocess.TimeoutExpired) as e:
        r = None
        err = L("claude 跑不起來:{e}", e=e)
    finally:
        restored = [p for p, data in before.items() if not p.is_file() or p.read_bytes() != data]
        for p in restored:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(before[p])
    if r is None:
        return False, err
    try:
        said = str(json.loads(r.stdout).get("result") or "").strip()
    except ValueError:
        said = (r.stdout + r.stderr).strip()[-500:]
    if restored:
        said += L("\n(它改到了原本就有的 {n} 個檔,已經照原樣還原)", n=len(restored))
    missing = [n for n in ("CLAUDE.md", "Wiki_Pages/index.md") if not (wiki / n).is_file()]
    if missing:
        return False, L("沒建出 {missing}。claude 說:{said}", missing=L("、").join(missing), said=said or L("(沒有回應)"))
    # 只查頁面:CLAUDE.md 裡「禁止 [[名稱]]」那條規則本身就有這兩個字
    if any("[[" in p.read_text(encoding="utf-8", errors="replace") for p in (wiki / "Wiki_Pages").rglob("*.md")):
        said += L("\n⚠ 裡面出現了 [[…]](Obsidian 的寫法):之後請它全部改成 [名稱](路徑.md)")
    return True, said


def ask_wiki(default: str = "", claude: Path | None = None, windows: bool = True,
             out: dict | None = None) -> tuple[str, str]:
    """知識庫與原件資料夾;不存在就建,沒有 CLAUDE.md 就照講義請 claude 建(使用者 2026-10-20)。
    在雲端同步資料夾裡就提醒(§5.15):知識庫照樣用的話 out["git_outside_reason"] 記下原因。"""
    out = {} if out is None else out
    while True:
        out.pop("git_outside_reason", None)     # 換了位置:上一個的原因不算
        w = Path(pick(L("【知識庫】照講義建的 WIKI 資料夾(還沒有就直接用預設、會幫你建)"), True, default))
        kind = sync_kind_of(w)
        if kind:
            if not keep_synced(w, kind, wiki=True):
                continue
            out["git_outside_reason"] = outside_reason(w, kind)
        if not w.is_dir():
            if not yes(L("  {path} 還沒有,要建立嗎?", path=w)):
                continue
            w.mkdir(parents=True)
        break
    guess = w.parent / "Raw_Sources"
    while True:
        r = Path(pick(L("【原件資料夾】Raw_Sources(主題群組是它底下的資料夾;與 WIKI 並排)"), True, str(guess)))
        kind = sync_kind_of(r)
        if kind and not keep_synced(r, kind, wiki=False):
            continue
        if r.is_dir():
            break
        if yes(L("  {path} 還沒有,要建立嗎?", path=r)):
            r.mkdir(parents=True)
            break
    # 原件資料夾裡已經有中文舊名的系統資料夾(舊版裝的、照講義自己建的)就沿用,不另建英文的(使用者 2026-10-24)
    pending = folder_names(r)[PENDING]
    (r / pending).mkdir(exist_ok=True)
    if not (w / "CLAUDE.md").is_file():
        if claude and yes(L("  {path} 裡還沒有 CLAUDE.md:要照講義請 Claude 建好規則檔與目錄索引嗎?(約 1～3 分鐘,用你的 Claude 額度)", path=w)):
            say(L("  Claude 正在建……"))
            ok, said = scaffold_wiki(claude, w, r, windows)
            say(f"  {'✓' if ok else '✗'} {said}")
        if not (w / "CLAUDE.md").is_file():
            say(L("  ⚠ 還是沒有 CLAUDE.md:自動攝入會照不到規則。之後在 Claude 桌面版照講義第三步建好,再重跑安裝"))
            return str(w), str(r)
    finish_wiki(w, pending)
    return str(w), str(r)


def finish_wiki(w: Path, pending: str) -> None:
    """CLAUDE.md 已經在了:補代管 git 的一節(問過才補)、.gitignore 排除 .md_cache/。新建、已有的庫共用。"""
    if not has_git_section((w / "CLAUDE.md").read_text(encoding="utf-8-sig", errors="replace")) and yes(
            L("  要在 CLAUDE.md 最後補上「版本紀錄由 wiki-feeder 代管、不要自己執行 git」這一節嗎?(建議要)")):
        add_git_section(w, pending)
        say(L("  ✓ 已補上"))
    if ignore_md_cache(w):
        say(L("  ✓ .gitignore 補上 .md_cache/(轉檔的中間產物不進版本紀錄)"))


# -- 已經有知識庫:照它的 CLAUDE.md(使用者 2026-10-27) ----------------------------------------
# 「已經有 WIKI,那就應該直接讀取他的 CLAUDE.md 設定,不應該像現在問那麼多」;「用程式就可以判斷,不需要 AI,
# 程式分析不出來才改由 Claude 分析」;「寫的不同時要以 CLAUDE.md 為準……再次確認,使用者還是堅持他的,才以他的為準」。
# 路徑 token:空白、反引號、括號、中文標點隔開;含 / 或 \ 才算
_PATH_TOKEN = re.compile(r"[^\s`'\"<>()\[\]{}（）「」『』《》，、。；：！？*|]+")
# 中文緊貼在路徑前面(「原始資料在../Raw_Sources/」):切掉前面的中文也試一次——「原始資料/會議/」這種本來就是相對路徑,兩個都留
_GLUED = re.compile(r"^[^\x00-\x7f]+(?=\.\.?[/\\]|~[/\\]|[A-Za-z]:[/\\]|[/\\])")
_RAW_WORDS = ("raw", "source", "原始", "原件", "素材")
# 新檔入口的說法:原件資料夾底下名字像這些的資料夾,當成 CLAUDE.md 規定的入口
_INBOX_WORDS = ("待處理", "待处理", "pending", "inbox", "incoming", "收件", "unprocessed")
# 知識庫裡不會是原件資料夾的地方(頁面、轉檔的中間產物、版本紀錄)
_NOT_RAW = ("wiki_pages", "pages", "wiki", ".md_cache", ".git", ".claude")


def claude_md_of(p: Path) -> Path:
    """給的是資料夾就找裡面的 CLAUDE.md。"""
    return p / "CLAUDE.md" if p.is_dir() else p


def mentioned_paths(wiki: Path, text: str) -> list[Path]:
    """CLAUDE.md 提到的路徑(相對的對知識庫資料夾解析;中文緊貼在路徑前面的切掉)。不看在不在。"""
    out: list[Path] = []
    for tok in _PATH_TOKEN.findall(text):
        if "://" in tok or ("/" not in tok and "\\" not in tok):
            continue
        for t in (tok, _GLUED.sub("", tok)):
            p = Path(t.replace("\\", "/").rstrip(".,:;")).expanduser()
            try:
                p = (p if p.is_absolute() else wiki / p).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if p not in out:
                out.append(p)
    return out


def raw_candidates(wiki: Path, text: str) -> list[Path]:
    """CLAUDE.md 提到、磁碟上真的有的原件資料夾:提到的路徑往上找第一層名字像原件資料夾的(raw、Raw_Sources、原始資料…)。"""
    wiki = wiki.resolve()
    found: list[Path] = []
    for p in mentioned_paths(wiki, text):
        if p.is_relative_to(wiki) and any(x.lower() in _NOT_RAW for x in p.relative_to(wiki).parts):
            continue
        for c in (p, *p.parents):
            if c == wiki or c in wiki.parents:
                break
            if any(w in c.name.lower() for w in _RAW_WORDS):
                if c.is_dir() and c not in found:
                    found.append(c)
                break
    return found


def with_pending(names: dict[str, str], pending: str) -> dict[str, str]:
    """待處理資料夾換成 pending;捨棄、收件區撞名(不分大小寫,磁碟上是同一個)就換成另一套系統名。"""
    out = {**names, PENDING: pending}
    for k in (DISCARD, INTAKE):
        if out[k].casefold() == pending.casefold():
            out[k] = LEGACY[k] if out[k] == k else k
    return out


def claude_md_folders(raw: Path, wiki: Path, text: str) -> tuple[dict[str, str], str]:
    """新檔入口照 CLAUDE.md(使用者 2026-10-27:「已經有 WIKI,目錄本來就不應該限定」):寫的是原件資料夾底下的
    某個資料夾(raw/inbox/)就用它;寫 _待處理 就三個系統資料夾都用舊名、寫 _Pending 就英文;都沒寫照磁碟(folder_names)。
    回傳 (系統資料夾名, CLAUDE.md 寫的入口名;沒寫就空字串)。"""
    raw = raw.resolve()
    for p in mentioned_paths(wiki.resolve(), text):
        if (p.parent == raw and p.name not in SYSTEM_DIRS and custom_dir_ok(p.name)
                and any(w in p.name.lower() for w in _INBOX_WORDS)):
            return with_pending(folder_names(raw), p.name), p.name
    old, new = LEGACY_PENDING in text, PENDING in text
    if old != new:
        names = {k: LEGACY[k] for k in LEGACY} if old else {k: k for k in LEGACY}
        return names, names[PENDING]
    return folder_names(raw), ""


# 程式找不到(或找到好幾個)原件資料夾時,才請 claude 讀一次;只給讀檔的工具,回來的路徑一樣要在磁碟上才收
RAW_PROMPT = N_("""讀這個資料夾裡的 CLAUDE.md,找出它規定的原始資料(原件)資料夾在哪裡。
只回一行 JSON、不要其他字:{"raw": "原件資料夾的路徑(完整路徑,或相對於這個資料夾);CLAUDE.md 沒寫就空字串"}
不要建檔、不要改檔、不要執行任何指令。這是安裝程式在背景送的,沒有人能回答問題。""")


def claude_find_raw(claude: Path, wiki: Path, run=subprocess.run) -> Path | None:
    args = [str(claude), "-p", "--output-format", "json", "--no-session-persistence", "--max-budget-usd", "1",
            "--tools", "Read,Glob,Grep", "--allowedTools", "Read", "Glob", "Grep"]
    try:
        r = run(args, cwd=wiki, input=L(RAW_PROMPT), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
        said = str(json.loads(r.stdout).get("result") or "")
        m = re.search(r"\{.*\}", said, re.S)
        raw = str(json.loads(m.group(0)).get("raw") or "").strip() if m else ""
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return None
    if not raw:
        return None
    p = Path(raw.replace("\\", "/")).expanduser()
    p = (p if p.is_absolute() else wiki / p).resolve()
    return p if p.is_dir() and p != wiki.resolve() else None


def insist(md, mine):
    """跟 CLAUDE.md 寫的不同:再問一次,預設用 CLAUDE.md 的;回 n 才算堅持、照他的(使用者 2026-10-27)。"""
    if mine == md:
        return md
    say(L("  跟 CLAUDE.md 寫的不同:CLAUDE.md 是 {md},你選的是 {path}。自動攝入照 CLAUDE.md 的規則做,通常它是對的",
          md=md, path=mine))
    return md if yes(L("  改用 CLAUDE.md 的 {md} 嗎?(n = 堅持用 {path})", md=md, path=mine)) else mine


def ask_existing_wiki(default: str, claude: Path | None,
                      out: dict | None = None) -> tuple[str, str, dict[str, str]] | None:
    """已經有知識庫:問 CLAUDE.md 在哪,原件資料夾與新檔入口照它寫的(程式看不出來才請 claude 讀)。
    使用者改的跟 CLAUDE.md 不同時再問一次,預設用 CLAUDE.md 的;還是堅持才照他的。回 None = 改成新建。"""
    while True:
        md = claude_md_of(Path(pick(L("【CLAUDE.md】你的知識庫裡的 CLAUDE.md(或知識庫資料夾)"), False, default)))
        try:
            text = md.read_text(encoding="utf-8-sig", errors="replace")
            break
        except OSError:
            say(L("  讀不到 {path}", path=md))
            if not yes(L("  要再選一次嗎?(n = 改成新建一個知識庫)")):
                return None
    wiki = md.parent.resolve()
    found = raw_candidates(wiki, text)
    md_raw = found[0] if len(found) == 1 else None
    if md_raw is None and claude:
        say(L("  程式從 CLAUDE.md 看不出原件資料夾,請 Claude 讀一次(十幾秒,用你的 Claude 額度)…"))
        md_raw = claude_find_raw(claude, wiki)
    if md_raw is None:
        say(L("  CLAUDE.md 裡找不到存在的原件資料夾,請自己選"))
        raw = Path(pick(L("【原件資料夾】Raw_Sources(主題群組是它底下的資料夾;與 WIKI 並排)"), True,
                        str(wiki.parent / "Raw_Sources"))).resolve()
    else:
        raw = md_raw
    out = {} if out is None else out
    kind = sync_kind_of(wiki)
    if kind:
        # 已經有的知識庫:換位置要他自己搬(安裝程式不搬檔)
        if not keep_synced(wiki, kind, wiki=True):
            move_first(wiki)
        out["git_outside_reason"] = outside_reason(wiki, kind)
        if (wiki / ".git").is_dir():
            say(L("  知識庫裡原本的 .git 會在第一次攝入時整個搬過去(歷史照留)"))
    names, md_pending = claude_md_folders(raw, wiki, text)
    say(L("  知識庫:{path}", path=wiki))
    say(L("  原件資料夾:{path}", path=raw))
    say(L("  新檔入口:{path}", path=raw / names[PENDING]))
    if not yes(L("  照 CLAUDE.md 這樣設定對嗎?")):
        v = Path(pick(L("【原件資料夾】Raw_Sources(主題群組是它底下的資料夾;與 WIKI 並排)"), True, str(raw))).resolve()
        raw = insist(md_raw, v) if md_raw is not None else v
        while not custom_dir_ok(v := ask(L("【新檔入口】原件資料夾底下放新檔的資料夾"), names[PENDING])):
            say(L("  {name} 不能當資料夾名(要一層、不可以 . 開頭、不可以有 \\ / : * ? \" < > |)", name=v))
        names = with_pending(names, insist(md_pending, v) if md_pending else v)
    kind = sync_kind_of(raw)
    if kind and not keep_synced(raw, kind, wiki=False):
        move_first(raw)
    if not raw.is_dir():
        if not yes(L("  {path} 還沒有,要建立嗎?", path=raw)):
            return None
        raw.mkdir(parents=True)
    (raw / names[PENDING]).mkdir(exist_ok=True)
    finish_wiki(wiki, names[PENDING])
    return str(wiki), str(raw), names


def ask_library(default_new: str, existing: Path | None, claude: Path | None,
                windows: bool, out: dict | None = None) -> tuple[str, str, dict[str, str] | None]:
    """設定的第一題(使用者 2026-10-27):已經有知識庫就照它的 CLAUDE.md,沒有才走新建(ask_wiki)。
    回傳 (知識庫, 原件資料夾, 系統資料夾名);名字是 None 就照磁碟(render_config 用 folder_names)。"""
    if yes(L("【知識庫】你已經有 LLM Wiki(有 CLAUDE.md 的知識庫資料夾)了嗎?"), existing is not None):
        got = ask_existing_wiki(str(existing / "CLAUDE.md") if existing else "", claude, out)
        if got:
            return got
        say(L("  改成新建一個知識庫"))
    w, r = ask_wiki(default_new, claude, windows, out)
    return w, r, None


def ask_doc2md(home: Path) -> str:
    roots = [home, home / "Desktop", home / "Downloads", home / "Documents", Path("C:/")]
    found = find_doc2md([r for r in roots if r.is_dir()])
    while True:
        if found:
            say(L("【轉寫】找到這些 meeting-scribe 的 doc2md:"))
            for i, p in enumerate(found, 1):
                say(f"  {i}. {p}")
            v = input(L("  輸入編號(直接按 Enter = 1);不是這些就貼上 doc2md.exe 的路徑,輸入 0 開選擇視窗:")).strip().strip('"')
            v = v or "1"
            exe = found[int(v) - 1] if v.isdigit() and 0 < int(v) <= len(found) else None if v == "0" else Path(v)
            if exe is None:
                exe = Path(pick(L("doc2md.exe 在 meeting-scribe 資料夾的 .venv\\Scripts 底下"), False) or ".")
        else:
            say(L("【轉寫】找不到 meeting-scribe。請先照它的說明解壓縮、跑它的 Install.bat。"))
            exe = Path(pick(L("doc2md.exe(在 meeting-scribe 資料夾的 .venv\\Scripts 底下)"), False) or ".")
        say(L("  試轉一個小檔(最多幾十秒)…"))
        ok, msg = check_doc2md(exe)
        say(L("  {path}:{msg}", path=exe, msg=msg))
        if ok:
            return str(exe)


def ask_mail(default: str = "") -> tuple[str, str]:
    say(L("【摘要信】每天把處理了什麼寄給你。要用 Gmail,而且要先開「兩步驟驗證」、產生「應用程式密碼」。"))
    frm = ask(L("  寄件的 Gmail(先不設定就輸入 -)") if default else L("  寄件的 Gmail(先不設定就直接按 Enter)"), default)
    if frm == "-":
        frm = ""
    if not frm:
        say(L("  先不寄信:之後要寄,重跑 Install.bat 就好"))
        return "", ""
    to = ask(L("  收件信箱"), frm)
    return frm, to


def save_password(account: str) -> None:
    import getpass

    import keyring
    pw = getpass.getpass(L("  Gmail 的應用程式密碼(16 個字,打字時不會顯示):")).replace(" ", "")
    keyring.set_password(SMTP_SERVICE, account, pw)


def reuse_config(path: Path, state: Path, lang: str) -> Config | None:
    """已經有設定檔:給他看、問要不要沿用。沿用但剛選了別的語言,就只改 [general] language(兩支共用)。"""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig")
    say(L("\n已經有設定檔 {path}:", path=path))
    say(text)
    if not yes(L("沿用這份(不重填)?")):
        return None
    try:
        cfg = Config.from_file(path, state)
        if cfg.lang != lang:
            cfg = write_config(set_config_lang(text, lang), state)
        return cfg
    except ConfigError as e:
        say(L("✗ 這份讀不了:{e}\n  請重填", e=e))
        return None


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "wiki_feeder", *args], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


# -- 主流程 ----------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="winsetup", description=L("wiki-feeder 第一次安裝的問答"))
    ap.add_argument("--no-schedule", action="store_true", help=L("不裝排程(實測用)"))
    args = ap.parse_args(argv)
    home = Path.home()
    state = state_dir_for(sys.platform, home, os.environ)
    path = state / CONFIG_FILE

    lang = entry_lang() or ask_lang(config_lang(path) or i18n.detect())
    say(L("=== 檢查 Claude Code ==="))
    claude = find_claude(home)
    if not claude:
        say(L("✗ 找不到 claude。請先裝 Claude Code(官方安裝程式),裝好後再跑一次 Install.bat"))
        return 1
    status = claude_status(claude)
    if not status.get("loggedIn"):
        say(L("✗ Claude Code 還沒登入。請開一個新的命令視窗打 claude 登入你自己的帳號,再跑一次 Install.bat"))
        return 1
    say(L("✓ {path}(已登入)", path=claude))

    cfg = reuse_config(path, state, lang)
    while cfg is None:
        say(L("\n=== 設定(每一題都可以貼上路徑;路徑有預設值時直接按 Enter) ==="))
        a = {"lang": lang}
        a["wiki"], a["raw"], a["folders"] = ask_library(str(default_wiki(home)),
                                                        find_wiki(home, (Path("C:/"), Path("D:/"))), claude, True, a)
        a["icloud"] = ask_inbox(home)
        a["label"] = ask(L("【知識庫名稱】摘要信上顯示的名字"), L("知識庫"))
        a["doc2md"] = ask_doc2md(home)
        a["mail_from"], a["mail_to"] = ask_mail(mail_default(status))
        a["claude"] = str(claude)          # 一律寫:排程底下的 PATH 不一定跟命令視窗一樣
        try:
            text = render_config(a)
            cfg = write_config(text, state)
        except (ValueError, ConfigError) as e:
            say(L("✗ {e}\n  請重填", e=e))
            continue
        say(L("\n✓ 已寫入 {path}", path=path))
    offer_glossary_section(cfg.repo(cfg.target_repo).repo_dir)

    if cfg.mail_from:
        say(L("\n=== 寄信 ==="))
        while True:
            if yes(L("要(重新)輸入 Gmail 應用程式密碼嗎?"), True):
                save_password(cfg.mail_from)
            r = run_cli("test-mail")
            say((r.stdout + r.stderr).strip())
            if r.returncode == 0 or not yes(L("沒寄成功,要再輸入一次密碼嗎?")):
                break

    say(L("\n=== 讀得到收件匣嗎 ==="))
    r = run_cli("collect", "--list")
    say((r.stdout + r.stderr).strip() or L("(沒有任何輸出:不算通過)"))

    if args.no_schedule:
        say(L("\n(--no-schedule:不裝排程)"))
        return 0
    say(L("\n=== 裝排程(每分鐘一輪) ==="))
    import importlib.util
    spec = importlib.util.spec_from_file_location("winsched", REPO / "scripts" / "winsched.py")
    ws = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ws)
    ws.install(state)
    say(L("\n✓ 安裝完成。一分鐘後程式就開始自己跑;往 _WikiBox 丟一個檔,幾分鐘後知識庫裡會多一頁。"))
    say(L("  看紀錄:%LOCALAPPDATA%\\wiki-feeder\\logs\\feeder.log;停掉排程:Remove-Schedule.bat;更新程式:Update.bat"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
