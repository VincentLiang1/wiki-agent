"""第一次安裝的問答(Mac 朋友版):問收件匣、知識庫、doc2md、寄信,寫 config.toml、存寄信密碼(鑰匙圈)、
跑一輪只列收件匣、裝排程、教怎麼加「完整磁碟取用權限」。由 install.sh 在 `uv sync` 之後叫
(雙擊 App 安裝的由 App 的 setup.zsh 叫,不必加權限:背景第一次讀的時候系統跳視窗,按「允許」):

    uv run python scripts/macsetup.py [--no-schedule] [--prefix 標籤開頭]

設定檔寫在 ~/Library/Application Support/wiki-feeder/config.toml。寫檔、驗 doc2md、查 claude 登入的純函式與
Windows 版(winsetup.py)共用,這裡只放 Mac 才有的:iCloud 雲碟的位置、scribe2md 的安裝位置、鑰匙圈、
選擇視窗(AppleScript)、launchd。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wiki_feeder import i18n  # noqa: E402
from wiki_feeder.config import CONFIG_FILE, ConfigError, state_dir_for  # noqa: E402
from wiki_feeder.i18n import L, N_  # noqa: E402


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ws = _script("winsetup")          # 共用:toml_path、render_config、write_config、check_doc2md、claude_logged_in、問答
say, ask, yes = ws.say, ws.ask, ws.yes
SCRIBE2MD = "https://github.com/VincentLiang1/scribe2md/releases/latest"
HEADER = N_("# wiki-feeder 設定檔(install.sh 問答產生;要改就用「文字編輯」改,改完下一分鐘生效)")


def icloud_drive(home: Path) -> Path:
    return home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"


def scribe2md_doc2md(home: Path) -> Path:
    """scribe2md 的 Mac 版(.app)第一次打開時把程式裝到這裡;與使用者本人那台同一個位置。"""
    return home / "Library" / "Application Support" / "meeting-scribe" / "app" / ".venv" / "bin" / "doc2md"


def render_config(a: dict) -> str:
    text = ws.render_config(a)
    return L(HEADER) + text[text.index("\n"):]


def find_claude(home: Path) -> Path | None:
    p = shutil.which("claude")
    for c in ([Path(p)] if p else []) + [home / ".local" / "bin" / "claude", Path("/opt/homebrew/bin/claude"),
                                          Path("/usr/local/bin/claude")]:
        if c.is_file():
            return c
    return None


def save_password(account: str, password: str, run=subprocess.run) -> bool:
    """存進登入鑰匙圈(service 與程式讀的同一個;-U 已有就更新)。用 /usr/bin/security 建的項目,
    launchd 底下讀不會跳授權視窗。"""
    r = run(["/usr/bin/security", "add-generic-password", "-U", "-s", ws.SMTP_SERVICE, "-a", account, "-w", password],
            capture_output=True)
    return r.returncode == 0


def pick(prompt: str, folder: bool, default: str = "") -> str:
    """貼上路徑(可以把資料夾從 Finder 拖進終端機視窗);直接按 Enter 開選擇視窗(有預設值時用預設值)。"""
    say(prompt)
    v = input(L("  貼上路徑(或把資料夾拖進這個視窗)後按 Enter(直接按 Enter = {default}):", default=default) if default
              else L("  貼上路徑(或把資料夾拖進這個視窗)後按 Enter,或直接按 Enter 開選擇視窗:")).strip().strip("'\"")
    v = v.replace("\\ ", " ")                  # 拖進終端機的路徑,空白前面會加反斜線
    if v or default:
        return str(Path(v or default).expanduser())
    kind = "folder" if folder else "file"
    title = prompt[:60].replace('"', "'")
    r = subprocess.run(["osascript", "-e", f'POSIX path of (choose {kind} with prompt "{title}")'],
                       capture_output=True, text=True)
    v = r.stdout.strip()
    if not v:
        v = input(L("  沒有選,請貼上路徑:")).strip().strip("'\"").replace("\\ ", " ")
    return str(Path(v).expanduser()) if v else ""


def ask_inbox(home: Path) -> str:
    drive = icloud_drive(home)
    if not drive.is_dir():
        say(L("⚠ 找不到 iCloud 雲碟。請到「系統設定 → 你的名字 → iCloud → iCloud 雲碟」打開,再重跑安裝。"))
    default = str(drive / "_WikiBox")
    while True:
        p = Path(pick(L("【收件匣】iPhone 丟檔進來的資料夾(iCloud 雲碟裡的 _WikiBox)"), True, default))
        if p.parent.is_dir():
            break
        say(L("  找不到 {path},請再確認", path=p.parent))
    if not p.is_dir() and yes(L("  {path} 還沒有,要建立嗎?", path=p)):
        p.mkdir()
    return str(p)


def ask_doc2md(home: Path) -> str:
    """【轉寫】scribe2md 選裝(§4.8):App 沒裝就問有沒有裝,沒裝回空字串;路徑問答裡打 - 也是先不裝。"""
    exe = scribe2md_doc2md(home)
    if not exe.is_file() and not yes(L(ws.SCRIBE2MD_QUESTION), default=False):
        return ""
    while True:
        if not exe.is_file():
            say(L("【轉寫】找不到 scribe2md 的 doc2md({path})。", path=exe))
            say(L("  請先到 {url} 下載 scribe2md-mac.zip、解壓縮,把 App 拖進「應用程式」、打開一次", url=SCRIBE2MD))
            say(L("  (第一次打開會自己裝好),關掉它再回到這裡。"))
            v = input(L("  裝好了按 Enter;doc2md 在別的地方就貼上路徑;打 - 先不裝 scribe2md:")).strip().strip("'\"").replace("\\ ", " ")
            if v == "-":
                return ""
            if v:
                exe = Path(v).expanduser()
            continue
        say(L("  試轉一個小檔(最多幾十秒)…"))
        ok, msg = ws.check_doc2md(exe)
        say(L("  {path}:{msg}", path=exe, msg=msg))
        if ok:
            return str(exe)
        v = input(L("  換一個路徑(直接按 Enter 再試一次;打 - 先不裝 scribe2md):")).strip().strip("'\"").replace("\\ ", " ")
        if v == "-":
            return ""
        if v:
            exe = Path(v).expanduser()




def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "wiki_feeder", *args], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="macsetup", description=L("wiki-feeder 第一次安裝的問答(Mac)"))
    ap.add_argument("--no-schedule", action="store_true", help=L("不裝排程(實測用)"))
    ap.add_argument("--prefix", default=None, help=L("launchd 標籤的開頭(實測用)"))
    args = ap.parse_args(argv)
    home = Path.home()
    state = state_dir_for("darwin", home, os.environ)
    path = state / CONFIG_FILE

    lang = ws.entry_lang() or ws.ask_lang(ws.config_lang(path) or i18n.detect())
    say(L("=== 檢查 Claude Code ==="))
    claude = find_claude(home)
    if not claude:
        say(L("✗ 找不到 claude。請先裝 Claude Code(https://claude.com/claude-code 的 Mac 安裝指令),裝好後再跑一次安裝"))
        return 1
    status = ws.claude_status(claude)
    if not status.get("loggedIn"):
        say(L("✗ Claude Code 還沒登入。請在終端機打 claude、登入你自己的帳號,再跑一次安裝"))
        return 1
    say(L("✓ {path}(已登入)", path=claude))

    # 沿用舊檔又換了語言時,ws 改語言那一行;第一行註解照原樣留著(寫的是 Mac 的)
    cfg = ws.reuse_config(path, state, lang)
    while cfg is None:
        say(L("\n=== 設定(每一題都可以貼上路徑;有預設值時直接按 Enter) ==="))
        a = {"lang": lang}
        a["wiki"], a["raw"], a["folders"] = ask_library(home, claude, a)
        a["icloud"] = ask_inbox(home)
        a["scribe_sync"] = ws.ask_scribe_sync(a)
        a["label"] = ask(L("【知識庫名稱】摘要信上顯示的名字"), L("知識庫"))
        a["doc2md"] = ask_doc2md(home)
        a["mail_from"], a["mail_to"] = ask_mail(ws.mail_default(status))
        a["claude"] = str(claude)          # 一律寫:launchd 底下的 PATH 不一定跟終端機一樣
        try:
            cfg = ws.write_config(render_config(a), state)
        except (ValueError, ConfigError) as e:
            say(L("✗ {e}\n  請重填", e=e))
            continue
        say(L("\n✓ 已寫入 {path}", path=path))
    ws.offer_glossary_section(cfg.repo(cfg.target_repo).repo_dir)

    if cfg.mail_from:
        say(L("\n=== 寄信 ==="))
        while True:
            if yes(L("要(重新)輸入 Gmail 應用程式密碼嗎?"), True):
                import getpass
                pw = getpass.getpass(L("  Gmail 的應用程式密碼(16 個字,打字時不會顯示):")).replace(" ", "")
                if not save_password(cfg.mail_from, pw):
                    say(L("  ✗ 存不進鑰匙圈"))
            r = run_cli("test-mail")
            say((r.stdout + r.stderr).strip())
            if r.returncode == 0 or not yes(L("沒寄成功,要再輸入一次密碼嗎?")):
                break

    say(L("\n=== 讀得到收件匣嗎(在終端機裡) ==="))
    r = run_cli("collect", "--list")
    say((r.stdout + r.stderr).strip() or L("(沒有任何輸出:不算通過)"))

    if args.no_schedule:
        say(L("\n(--no-schedule:不裝排程)"))
        return 0
    ms = _script("macsched")
    prefix = args.prefix or ms.PREFIX
    app = ms.app_bundle()
    say(L("\n=== 裝排程(每分鐘一輪) ==="))
    if not ms.install(home, prefix, app):
        return 1
    if app:
        return _app_permission(home, prefix, app, state)
    say(L("\n=== 完整磁碟取用權限 ==="))
    say(L("排程在背景跑,要另外允許它讀 iCloud 雲碟。請照安裝說明第 5 步:"))
    say(L("  系統設定 → 隱私權與安全性 → 完整磁碟取用權限 → 左下角「+」→ 按 ⌘⇧G、貼上下面這一行 → 打開 → 確認開關是開的"))
    say(f"  {ms.fda_path()}")
    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"],
                   capture_output=True)
    while True:
        input(L("  加好之後按 Enter,我在背景試讀一次收件匣…"))
        if ms.check(home, prefix) == 0:
            break
        if not yes(L("  還是讀不到,要再試一次嗎?")):
            say(L("  先不管:排程照樣在跑,只是收件匣讀不到;之後加好權限就會自己恢復"))
            break
    say(L("\n✓ 安裝完成。一分鐘後程式就開始自己跑;往 _WikiBox 丟一個檔,幾分鐘後知識庫裡會多一頁。"))
    say(L("  看紀錄:{log};停掉排程:雙擊 Remove-Schedule.command;更新程式:雙擊 Update.command", log=state / "logs" / "feeder.log"))
    return 0


def _app_permission(home: Path, prefix: str, app: Path, state: Path) -> int:
    """App 版:在背景試讀一次,讓系統趁現在跳視窗問權限(收件匣在 iCloud 雲碟,知識庫可能在「文件」「桌面」)。"""
    ms = _script("macsched")
    say(L("\n=== 讀取權限 ==="))
    say(L("等一下系統會跳出「“wiki-agent”想要取用……的檔案」的視窗(iCloud 雲碟;知識庫放在「文件」「桌面」的話,"
          "那邊也會再問一次),每一個都按「允許」。"))
    while True:
        input(L("  準備好了按 Enter,我在背景試讀一次(最多等 5 分鐘)…"))
        if ms.check(home, prefix, app) == 0:
            break
        if not yes(L("  還是讀不到,要再試一次嗎?")):
            say(L("  先不管:排程照樣在跑,只是讀不到;之後打開權限就會自己恢復"))
            break
    say(L("\n✓ 安裝完成。一分鐘後程式就開始自己跑;往 _WikiBox 丟一個檔,幾分鐘後知識庫裡會多一頁。"))
    say(L("  看紀錄:{log};停掉排程:雙擊 ~/wiki-agent 裡的 Remove-Schedule.command;"
          "更新程式:下載新版 wiki-agent 取代舊的,再雙擊一次", log=state / "logs" / "feeder.log"))
    return 0


def ask_library(home: Path, claude: Path, out: dict | None = None) -> tuple[str, str, dict[str, str] | None]:
    """與 Windows 版同一套問法(先問有沒有知識庫:有就照它的 CLAUDE.md,沒有就新建),但選擇視窗用 Mac 的。
    雲端同步資料夾的提醒也在裡面(§5.15),照樣用的話 out 記下原因。"""
    ws.pick = pick
    return ws.ask_library(str(ws.default_wiki(home)), ws.find_wiki(home), claude, windows=False, out=out)


def ask_mail(default: str) -> tuple[str, str]:
    frm, to = ws.ask_mail(default)
    if not frm:
        say(L("  (Mac:之後要寄,重跑 install.sh 那一行就好)"))
    return frm, to


if __name__ == "__main__":
    sys.exit(main())
