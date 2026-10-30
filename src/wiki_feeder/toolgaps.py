"""攝入工具缺口:claude 被權限擋下的指令、自己回報做不到的檢查,整理成摘要信裡的提醒(一天一次)。

使用者 2026-10-07 要求:「以後每天要幫忙查一下,是否有可以增加的指令,給我 email 時給我提醒」。
只做整理、不做判斷:要不要補指令(放行什麼都是權限的事,spec §6.2)由人在 Claude Code 裡決定。
確定不做的(例如同名 docx 重產)用 `wiki-feeder tool-gaps --ignore <關鍵字>` 從提醒拿掉;
已經補好的用 `--resolved <關鍵字>`:那之前的紀錄不再提醒,之後又出現的照樣列、標「修好後又出現」
(使用者 2026-10-19:「如果程式已改好,可以不要繼續寫在信裡面,只要寫還需要改良的」)。
"""
from __future__ import annotations

import json
import logging
import re
import shlex
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config
from .i18n import L

log = logging.getLogger(__name__)

WINDOW_DAYS = 7      # 整理最近幾天
MAX_ITEMS = 8        # 信裡最多列幾項(依筆數排);其他的寫總數
_WORD = re.compile(r"[A-Za-z][\w.-]*")


def forbidden() -> list[list[str]]:
    """攝入刻意禁止的 Bash 指令開頭(ingest.DISALLOWED_TOOLS 的 `Bash(git -C:*)` → ["git", "-C"])。"""
    from .ingest import DISALLOWED_TOOLS   # ingest 也 import 本模組,放這裡避免循環
    return [t[len("Bash("):-len(":*)")].split() for t in DISALLOWED_TOOLS if t.startswith("Bash(") and t.endswith(":*)")]


def allowed() -> list[list[str]]:
    """攝入放行的 Bash 指令開頭(ingest.ALLOWED_TOOLS 的 `Bash(git add:*)` → ["git", "add"])。"""
    from .ingest import ALLOWED_TOOLS
    return [t[len("Bash("):-len(":*)")].split() for t in ALLOWED_TOOLS if t.startswith("Bash(") and t.endswith(":*)")]


def _segments(cmd: str) -> list[list[str]]:
    """把 `a && b; c | d` 拆成一段一段的字詞。heredoc(`<<`)之後是內容、不再拆。"""
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        segs, cur = [], []
        for tok in lx:
            if tok.startswith("<<"):
                break
            if tok and set(tok) <= set(";&|"):
                segs.append(cur)
                cur = []
            else:
                cur.append(tok)
        segs.append(cur)
    except ValueError:   # 引號沒配對(被截短的指令)
        segs = [s.split() for s in re.split(r"&&|\|\||[;|]", cmd)]
    return [w for w in ([x for x in s if not re.fullmatch(r"\w+=.*", x)] for s in segs) if w]   # 去掉開頭的 VAR=值


def key_of(kind: str, text: str) -> str:
    """同一種缺口歸成同一個鍵。被擋下的指令取指令名(加上腳本名或子命令),碰到刻意禁止的取禁止的那一條
    (`git -C` 不跟日後真的想要的 git 只讀指令混成一項);未驗取冒號前的「哪一項」。
    串接的指令(`git add x && git diff --stat`)只要有一段沒放行就整條被擋:取擋下它的那一段,
    不是第一段——2026-10-15 兩筆被 `git diff` 擋下,提醒卻寫成「被擋下 git add／git status」,看起來像放行的指令不能用。"""
    if kind == "denied":
        tool, _, cmd = text.partition(": ")
        if tool != "Bash":
            return tool
        segs = _segments(cmd)
        if not segs:
            return "Bash"
        for words in segs:
            for f in forbidden():
                if words[:len(f)] == f:
                    return "Bash: " + " ".join(f)
        ok = allowed()
        words = next((w for w in segs if not any(w[:len(a)] == a for a in ok)), segs[0])
        head = [Path(words[0]).name]
        if len(words) > 1 and _WORD.fullmatch(Path(words[1]).name) and not words[1].startswith("-"):
            head.append(Path(words[1]).name)
        return "Bash: " + " ".join(head)
    return re.split(r"[:：]", text, maxsplit=1)[0].strip()[:40]


def record(cfg: Config, name: str, kind: str, items: list[str], when: datetime | None = None) -> None:
    """記一筆攝入的缺口(kind:denied=被權限擋下、unverified=claude 回報做不到)。寫不進去只記 log。"""
    if not items:
        return
    when = when or datetime.now()
    try:
        cfg.tool_gaps_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg.tool_gaps_path, "a", encoding="utf-8") as f:
            for t in items:
                f.write(json.dumps({"time": when.isoformat(timespec="seconds"), "file": name, "kind": kind,
                                    "text": t}, ensure_ascii=False) + "\n")
    except OSError as e:
        log.error(L("攝入工具缺口寫不進去:%s"), e)


def ignored(cfg: Config) -> list[str]:
    try:
        return [w.strip() for w in cfg.tool_gaps_ignore_path.read_text(encoding="utf-8").splitlines() if w.strip()]
    except OSError:
        return []


def ignore(cfg: Config, word: str) -> None:
    cfg.tool_gaps_ignore_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.tool_gaps_ignore_path, "a", encoding="utf-8") as f:
        f.write(word.strip() + "\n")


def resolved(cfg: Config) -> list[tuple[str, datetime]]:
    """標成已補好的(關鍵字, 標記時間)。壞掉的列跳過。"""
    out = []
    try:
        rows = cfg.tool_gaps_resolved_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for row in rows:
        try:
            r = json.loads(row)
            out.append((str(r["word"]), datetime.fromisoformat(r["time"])))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def resolve(cfg: Config, word: str, when: datetime | None = None) -> None:
    when = when or datetime.now()
    cfg.tool_gaps_resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.tool_gaps_resolved_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"word": word.strip(), "time": when.isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")


def digest(cfg: Config, now: datetime | None = None, days: int = WINDOW_DAYS,
           limit: int | None = MAX_ITEMS) -> list[str]:
    """最近幾天的缺口,同一個鍵併成一項、依涉及幾筆攝入排序;兩筆以上的標 🔁。沒有就回空串列。
    limit:列幾項(摘要信 MAX_ITEMS;`tool-gaps` 指令給 None 列全部——信上寫「看全部」,指令卻也只列 8 項,2026-10-30)。"""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    skip = ignored(cfg)
    fixed = resolved(cfg)
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"files": set(), "days": set(), "example": ""})
    try:
        rows = cfg.tool_gaps_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for row in rows:
        try:
            r = json.loads(row)
            t = datetime.fromisoformat(r["time"])
        except (ValueError, KeyError, TypeError):
            continue
        if t < since:
            continue
        k = key_of(r["kind"], r["text"])
        if any(w in k for w in skip):
            continue
        hits = [ft for w, ft in fixed if w in k]
        if any(t <= ft for ft in hits):   # 補好之前的紀錄
            continue
        g = groups[(r["kind"], k)]
        if hits:
            g["again"] = max(hits).strftime("%m/%d")
        g["files"].add(r["file"])
        g["days"].add(t.strftime("%m/%d"))
        g["example"] = r["text"]
    if not groups:
        return []
    banned = {"Bash: " + " ".join(f) for f in forbidden()}
    # 刻意禁止的排最後:那不是可以補的指令
    order = sorted(groups.items(), key=lambda kv: (kv[0][1] in banned, -len(kv[1]["files"]), kv[0]))
    lines = [L("### 🧰 攝入工具缺口(近 {days} 天,可以考慮補只讀指令的)", days=days)]
    for (kind, k), g in order[:limit]:
        d = sorted(g["days"])
        when = d[0] if len(d) == 1 else f"{d[0]}～{d[-1]}"
        label = L("刻意禁止") if k in banned else L("被擋下") if kind == "denied" else L("未驗")
        mark = "🔁 " if len(g["files"]) > 1 else ""
        again = L("{date} 修好後又出現,", date=g["again"]) if g.get("again") else ""
        lines.append(L("- {mark}{label}「{key}」:{again}{n} 筆攝入({when}),例:{example}", mark=mark, label=label,
                       key=k, again=again, n=len(g["files"]), when=when, example=g["example"][:120]))
    if limit is not None and len(order) > limit:
        lines.append(L("- 另有 {n} 項,`wiki-feeder tool-gaps` 看全部", n=len(order) - limit))
    if any(k in banned for _, k in groups):
        lines.append(L("「刻意禁止」的是權限故意擋的(會清檔、會動到別的庫、有替代指令),不會放行;"
                       "反覆出現表示攝入提示沒講清楚,要改的是提示。"))
    lines.append(L("要不要補指令,在 Claude Code 裡說「看一下攝入工具缺口」;確定不做的用 "
                   "`wiki-feeder tool-gaps --ignore <關鍵字>` 從提醒拿掉。已經補好的不再列出,只列還要改良的。"))
    return lines


def reported_today(cfg: Config, now: datetime) -> bool:
    try:
        return cfg.tool_gaps_reported_path.read_text(encoding="utf-8").strip() == f"{now:%Y-%m-%d}"
    except OSError:
        return False


def mark_reported(cfg: Config, now: datetime) -> None:
    try:
        cfg.tool_gaps_reported_path.write_text(f"{now:%Y-%m-%d}\n", encoding="utf-8")
    except OSError as e:
        log.error(L("攝入工具缺口的提醒日期寫不進去:%s"), e)
