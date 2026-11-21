"""常駐身分下的冒煙檢查(`wiki-feeder selfcheck`;scripts/launchd.py check 在 launchd 底下叫它)。

只驗「真的憑證、真的遠端」:測試、deploy、突變全用假 claude 與假 remote,看門狗也不呼叫 claude(花錢),
所以憑證失效只有攝入、寄信真的失敗時才看得到——而寄信密碼跟 Claude 的登入在同一個鑰匙圈,一起失效時
連「Claude 沒登入」的摘要信都寄不出去(2026-11-11 鑰匙圈換成隨機密碼、2026-11-12 鑰匙圈被換新,兩次都整晚停擺)。
觸發方式是事件:動過憑證、鑰匙圈、ssh、gh,macOS 更新重開機、uv 升 Python 之後跑(docs/dev/常駐與發佈.md)。

每一項印一行「名稱<TAB>可用|不可用<TAB>原因」;名稱與「可用／不可用」不翻譯(launchd.py 照它判斷)。
不寄信、不改憑證、不動鑰匙圈內容。
"""
from __future__ import annotations

import json
import os
import subprocess

from . import doc2md
from .config import Config
from .i18n import L, N_
from .ingest import _API_DOWN, _NOT_LOGGED_IN, SETTING_SOURCES
from .notify import MailError, smtp_password
from .proc import TIMED_OUT, run_net

OK, BAD = "可用", "不可用"
ITEMS = ("claude", "mail", "git", "doc2md")   # launchd.py 要看到這四項都「可用」才算過
CLAUDE_TIMEOUT = 120
GIT_TIMEOUT = 60
VERSION_TIMEOUT = 30
VERSION_FILE = "claude-version.txt"
# 最便宜的模型、最短的提示、不給任何工具;cwd 放執行狀態目錄(沒有專案的 CLAUDE.md 要讀)。2026-11-14 實測一次約 US$0.002。
# 提示走 stdin:`--tools` 收好幾個值,提示放在它後面會被當成工具名吃掉(實測報「Input must be provided」)
PROMPT = "Reply with OK."
VERSION_CHANGED = N_("Claude Code 版本變了({old} → {new}):攝入權限實測要重跑(docs/dev/攝入權限實測.md)")


def check_claude(cfg: Config) -> tuple[bool, str]:
    """`claude -p` 回得來;不行時分得出「沒登入」與「連不上」(兩者的修法不同:重新登入／等網路)。"""
    args = [*cfg.claude_cmd, "-p", *SETTING_SOURCES, "--model", "haiku", "--output-format", "json",
            "--no-session-persistence", "--tools", ""]
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = run_net(args, CLAUDE_TIMEOUT, input=PROMPT, cwd=cfg.state_dir, text=True)
    except OSError as e:
        return False, L("找不到 claude:{e}", e=e)
    if r.returncode == TIMED_OUT:
        return False, L("連不上:{seconds} 秒沒有回應", seconds=CLAUDE_TIMEOUT)
    said = ((r.stdout or "") + (r.stderr or "")).strip()
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = None
    if isinstance(out, dict) and not out.get("is_error") and r.returncode == 0:
        return True, L("回得來")
    if isinstance(out, dict):
        said = str(out.get("result", "")) or said
    if _NOT_LOGGED_IN.search(said):
        return False, L("沒登入或登入過期:{said}", said=said[-200:])
    if _API_DOWN.search(said):
        return False, L("連不上:{said}", said=said[-200:])
    return False, L("沒有正常回應:{said}", said=said[-200:] or r.returncode)


def claude_version(cfg: Config) -> tuple[str, str]:
    """回傳(這次的版本, 上次記的版本);問不到版本回空字串、不寫檔。"""
    path = cfg.state_dir / VERSION_FILE
    old = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    try:
        r = subprocess.run([*cfg.claude_cmd, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return "", old
    new = (r.stdout or "").strip().splitlines()[0].strip() if r.returncode == 0 and (r.stdout or "").strip() else ""
    if new and new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new + "\n", encoding="utf-8")
    return new, old


def check_mail(cfg: Config) -> tuple[bool, str]:
    """寄信密碼從鑰匙圈讀得到(不連 Gmail、不寄信)。"""
    if not cfg.mail_from or not cfg.mail_to:
        return False, L("設定裡沒有寄件或收件地址")
    try:
        smtp_password(cfg)
    except MailError as e:
        return False, str(e)
    return True, L("鑰匙圈讀得到(service={service})", service=cfg.smtp_keychain_service)


def check_git(cfg: Config) -> tuple[bool, str]:
    """公事庫的 `git ls-remote` 通:推送用的憑證(gh 權杖、ssh 金鑰)還在。"""
    target = cfg.repo(cfg.target_repo)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}   # 憑證不見時 git 會問帳密,常駐身分下沒人回答
    try:
        r = run_net(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{target.branch}"], GIT_TIMEOUT,
                    cwd=target.repo_dir, env=env, text=True)
    except OSError as e:
        return False, str(e)
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or "")).strip()[-200:]
        return False, L("{repo} 的 ls-remote 失敗:{tail}", repo=target.repo_dir.name, tail=tail or r.returncode)
    return True, L("{repo} 連得到 origin", repo=target.repo_dir.name)


def check_doc2md(cfg: Config) -> tuple[bool, str]:
    """Scribe2MD 固定入口的 `doc2md --version --json` 有回應(spec §4.9)。"""
    if cfg.doc2md_root is None:
        return False, L("設定裡沒有 Scribe2MD 的固定入口")
    exe = doc2md.entry_exe(cfg.doc2md_root)
    info = doc2md.probe(exe, cfg.doc2md_probe_timeout)
    if info is None:
        return False, L("{exe} 問不出版本", exe=exe)
    return True, f"{exe} {info.get('version', '')}".strip()


CHECKS = {"claude": check_claude, "mail": check_mail, "git": check_git, "doc2md": check_doc2md}


def run(cfg: Config) -> tuple[bool, list[str]]:
    lines, ok = [], True
    for name in ITEMS:
        good, why = CHECKS[name](cfg)
        ok = ok and good
        lines.append(f"{name}\t{OK if good else BAD}\t{why}")
    new, old = claude_version(cfg)
    if new:
        lines.append(L("Claude Code 版本:{v}", v=new))
        if old and new != old:
            lines.append(L(VERSION_CHANGED, old=old, new=new))
    return ok, lines


def passed(text: str) -> bool:
    """launchd.py 判斷用:ITEMS 每一項都明確印了「可用」才算過,缺一項(沒跑到、當掉)也不算。"""
    seen = {}
    for ln in text.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2 and parts[0] in ITEMS:
            seen[parts[0]] = parts[1]
    return all(seen.get(n) == OK for n in ITEMS)
