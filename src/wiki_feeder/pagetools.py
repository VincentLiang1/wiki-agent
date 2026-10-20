"""攝入時 claude 能用的只讀指令:查 git 歷史(page-history、commit-detail)、頁面檢查(check-pages)、
表格加總(table-sums)。

為什麼不直接開放 git log／show／diff:它們的 `--output=<檔>` 能寫入或清空任意檔,前綴式的允許規則管不到參數
(spec §6.2)。這裡由程式組 git 參數,claude 只能給「哪一頁」「哪個 commit」「什麼關鍵字」,而且都先檢查過。

為什麼不開放「只跑約定好的那幾支 python」:那幾支若在公事庫的 tools/ 裡,claude 能先改寫它再執行,
等於能跑任意程式;所以檢查寫在這裡,跑的是發佈副本(claude 改不到)。

公事庫要查的兩項(公事庫 CLAUDE.md〈Python 改寫的反斜線毀損〉〈CJK 粗體／斜體 flanking〉):
控制字元(Cc／Cf／Co／Cs,`\\n`、`\\t` 除外)一律是毀損;粗體失效一律用 CommonMark 渲染器判定——
逐行渲染、輸出還留著字面 `**` 就是失效。不自己實作 flanking 條文(2026-07-29 那樣做誤報 99 筆)。
另外照公事庫 CLAUDE.md 列的 grep 健檢查 Wiki_Pages/ 的頁面(wikilink、H2 禁用字元、錨點大寫、跨群組連結的
顯示文字、相關連結的 type label、來源路徑的磁碟前綴、index.md 摘要長度):那幾條要 grep -P 或 python 才查得了,
攝入時不開放,2026-10-06～07 的攝入 commit 一再寫成「目測」「未驗」。

check-pages 另外收個人 WIKI 的副本(攝入回填寫的那份)與真的個人 WIKI,照個人 WIKI 自己的規則查:兩庫規則幾乎一樣,
差在 H2 禁用字元少了頓號、全形減號,原件樹叫 Raw_Sources。只讀,所以真的個人 WIKI 也可以給;2026-10-08 以前只收
公事庫,回填的頁每筆都寫成「CJK 粗體渲染判定未能以渲染器執行」未驗。

表格加總:公事庫的請款統計頁每批要「用腳本 assert 重算」四張表(公事庫 memory/expense-approval-ledger.md),
python 不開放之後改成 awk、bc 或人工算。這裡只加總頁面上已經寫好的表、比對合計列,不算任何算式。
"""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from markdown_it import MarkdownIt

GIT_TIMEOUT = 60
HISTORY_LIMIT = 50
_REV = re.compile(r"[0-9a-f]{4,40}")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_CODE = re.compile(r"<code>.*?</code>", re.S)
_MD = MarkdownIt("commonmark")
_INLINE_CODE = re.compile(r"`[^`]*`")
# 公事庫 CLAUDE.md 的 grep 健檢(〈H2 命名規則〉〈連結路徑〉〈交叉引用〉〈wikilink〉〈來源路徑不帶磁碟前綴〉);
# H2 的字元類照該節「禁用」那一行(比它的 grep 多了頓號、全形減號);個人 WIKI 照它自己 CLAUDE.md 的 grep
_WIKILINK = (re.compile(r"\[\["), "wikilink [[…]](本庫只用標準 Markdown 連結)")
_ANCHOR = (re.compile(r"\]\(#[^)]*[A-Z]"), "錨點含大寫字母")
_WIKI_RULES = [_WIKILINK, (re.compile(r"^## .*[：（）「」《》、－ .(),⁺]"), "H2 含禁用字元"), _ANCHOR]
_PERSONAL_RULES = [_WIKILINK, (re.compile(r"^## .*[：（）「」《》 .(),⁺]"), "H2 含禁用字元"), _ANCHOR]
DRIVE_KIND = "來源路徑帶磁碟前綴"
_CROSS = re.compile(r"^\s*[-*+]\s+\[([^]]+)\]\(\.\./([^)]+)\.md\)")
_UNTYPED = re.compile(r"^\s*[-*+]\s+\[[^]]+\]\((?!https?://)[^)]+\.md\) — (?!基礎|進階|對比|對立)")
_INDEX_LINE = re.compile(r"^- \[[^]]+\]\([^)]+\.md\) — (.*)$")
INDEX_SUMMARY_MAX = 400


class PageToolError(Exception):
    pass


@dataclass(frozen=True)
class PageRoot:
    """check-pages 收的一個庫:name 印在結果前面,personal 決定照哪個庫的規則查。"""
    name: str
    path: Path
    personal: bool = False
    raw: Path | None = None     # 這個庫的原件樹:查「來源路徑帶磁碟前綴」用
    basic: bool = False         # 只查通用的幾項(程式代管的庫:朋友的庫沒有公事庫那套 grep 健檢)


def git_text(repo: Path, *args: str) -> str:
    try:
        # quotePath=false:中文檔名不跳脫成 \351\240…,claude 才看得懂
        r = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=repo, capture_output=True,
                           timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise PageToolError(f"git 執行失敗:{e}") from e
    if r.returncode != 0:
        raise PageToolError(r.stderr.decode("utf-8", "replace").strip() or f"git 結束碼 {r.returncode}")
    return r.stdout.decode("utf-8", "replace")


def page_path(repo: Path, path: str) -> str:
    """庫裡的相對路徑(/ 分隔)。不在庫裡、在 .git 裡都擋下:這些指令只看公事庫。"""
    root = repo.resolve()
    p = Path(path)
    p = (p if p.is_absolute() else root / p).resolve()
    if not p.is_relative_to(root) or p == root or ".git" in p.relative_to(root).parts:
        raise PageToolError(f"{path} 不在 {repo.name} 裡")
    return p.relative_to(root).as_posix()


def page_history(repo: Path, page: str | None = None, grep: str | None = None) -> str:
    """單頁的 commit 歷史(跟著改名),或 commit message 含某個關鍵字的 commit;最近的在前、最多 50 筆。

    每個 commit 一行(雜湊、日期、標題):公事庫的 commit message 很長,印全文的話一頁的歷史就 70 KB
    (2026-10-06 實測)。全文用 commit_detail 看;--grep 照樣比對全文。"""
    if not page and not grep:
        raise PageToolError("給一個頁面路徑,或用 --grep 給關鍵字")
    args = ["log", f"-n{HISTORY_LIMIT}", "--date=short", "--format=%h %ad %s"]
    if grep:
        args += ["--fixed-strings", "--regexp-ignore-case", f"--grep={grep}"]
    if page:
        args += ["--follow", "--", page_path(repo, page)]
    return git_text(repo, *args).strip() or "(沒有符合的 commit)"


def commit_detail(repo: Path, rev: str) -> str:
    """某個 commit 的完整訊息與動到哪些檔(--stat)。只收 16 進位雜湊與 HEAD 這個字:其他字串可能是 git 的選項。
    HEAD:claude commit 完要確認自己 commit 了什麼(2026-10-08、10-14 兩次改打 git show --stat HEAD 被擋)。"""
    rev = rev.strip()
    if rev != "HEAD" and not _REV.fullmatch(rev):
        raise PageToolError(f"{rev!r} 不是 commit 雜湊(只收 4～40 位 16 進位,或 HEAD)")
    return git_text(repo, "show", "--stat", "--no-ext-diff", "--no-textconv", "--date=short",
                "--format=%H %ad%n%s%n%n%b", f"{rev}^{{commit}}", "--").strip()


def _drive(raw: Path | None) -> re.Pattern | None:
    """來源路徑該寫成相對的 `<原件樹>\\群組\\檔名`;前面多了原件樹上一層的資料夾名(例如 C:\\…\\<上一層>\\<原件樹>)
    就是帶了磁碟前綴。照該庫的原件樹位置組,不寫死使用者的資料夾名。"""
    if raw is None or not raw.parent.name:
        return None
    return re.compile(re.escape(raw.parent.name) + r"[\\/]+" + re.escape(raw.name))


def scan_text(text: str, rel: str = "", personal: bool = False, raw: Path | None = None,
              basic: bool = False) -> list[tuple[int, str, str]]:
    """(行號, 種類, 那一行)。種類:控制字元 U+XXXX、粗體失效,Wiki_Pages/ 底下另查該庫的 grep 健檢
    (personal=True 照個人 WIKI 的規則)。
    程式碼區塊裡的只查控制字元(Mermaid 的 [["…"]] 不是 wikilink);行內程式碼不查 wikilink(教學頁的反例)。"""
    # basic:朋友照講義建的庫只約定不用 [[…]];H2 禁用字元、跨群組顯示文字、type label、index 摘要字數是公事庫自己的規則,
    # 照樣查的話每筆摘要都是不相干的提醒,claude 還可能照著改朋友的頁(2026-10-20 Mac 朋友版實測)
    rules = [_WIKILINK] if basic else _PERSONAL_RULES if personal else _WIKI_RULES
    drive = _drive(raw)
    wiki = rel.startswith("Wiki_Pages/")
    index = rel == "Wiki_Pages/index.md"
    problems = []
    fenced = False
    for n, line in enumerate(text.split("\n"), 1):
        bad = sorted({f"U+{ord(ch):04X}" for ch in line
                      if ch != "\t" and unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs")})
        if bad:
            problems.append((n, f"控制字元 {'、'.join(bad)}", line))
        if drive and drive.search(line):
            problems.append((n, DRIVE_KIND, line))
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if "**" in line and "**" in _CODE.sub("", _MD.render(line)):
            problems.append((n, "粗體失效(渲染後還留著 **)", line))
        if not wiki:
            continue
        bare = _INLINE_CODE.sub("", line)
        problems += [(n, kind, line) for rx, kind in rules if rx.search(bare)]
        if basic:
            continue
        m = _CROSS.match(line)
        if m and m[1] != m[2]:
            problems.append((n, f"跨群組清單項的顯示文字要寫成路徑 {m[2]}", line))
        if not index and _UNTYPED.match(line):
            problems.append((n, "相關連結的 type label 不是 基礎／進階／對比／對立", line))
        m = _INDEX_LINE.match(line) if index else None
        if m and len(m[1]) > INDEX_SUMMARY_MAX:
            problems.append((n, f"index 摘要 {len(m[1])} 字(上限 {INDEX_SUMMARY_MAX})", line))
    return problems


def new_problems(before: str, after: str, rel: str = "", personal: bool = False,
                 raw: Path | None = None, basic: bool = False) -> list[tuple[int, str, str]]:
    """改後才有的問題:同一種問題、同一行內容在改前就有的不算(那不是這次攝入造成的)。"""
    old = {(kind, line) for _, kind, line in scan_text(before, rel, personal, raw, basic)}
    return [p for p in scan_text(after, rel, personal, raw, basic) if (p[1], p[2]) not in old]


def locate(roots: list[PageRoot], path: str) -> tuple[PageRoot, str]:
    """(哪個庫, 庫裡的相對路徑)。相對路徑以第一個庫(公事庫)為準;不在任何一個庫裡、在 .git 裡都擋下。"""
    p = Path(path)
    p = p if p.is_absolute() else roots[0].path / p
    for root in roots:
        try:
            return root, page_path(root.path, str(p))
        except PageToolError:
            continue
    raise PageToolError(f"{path} 不在 {'、'.join(r.name for r in roots)} 裡")


def check_pages(roots: list[PageRoot], pages: list[str]) -> str:
    out = []
    for page in pages:
        root, rel = locate(roots, page)
        name = rel if root is roots[0] else f"{root.name} {rel}"
        f = root.path / rel
        if not f.is_file():
            out.append(f"{name}:找不到")
            continue
        problems = scan_text(f.read_bytes().decode("utf-8", "replace"), rel, root.personal, root.raw, root.basic)
        out += [f"{name}:第 {n} 行 {kind}:{line.strip()[:80]}" for n, kind, line in problems]
        if not problems:
            out.append(f"{name}:沒有問題")
    return "\n".join(out)


_TOTAL_ROW = re.compile(r"合計|總計|total", re.I)
_SUBTOTAL_ROW = re.compile(r"小計|subtotal", re.I)
_NUMBER = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _cells(line: str) -> list[str]:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def _number(cell: str) -> tuple[Decimal, bool] | None:
    """(數值, 是不是百分比)。只認整格就是一個數字的(千分位、小數、%、「元」可有可無;粗體記號不算)。"""
    s = cell.replace("**", "").replace("−", "-").strip()
    s = s.removesuffix("元").strip()
    pct = s.endswith("%")
    s = s.removesuffix("%").strip()
    if not _NUMBER.fullmatch(s):
        return None
    try:
        return Decimal(s.replace(",", "")), pct
    except InvalidOperation:
        return None


def _fmt(d: Decimal, pct: bool) -> str:
    return f"{d:,}{'%' if pct else ''}"


def _tables(text: str):
    """(起始行號, 標題路徑, 表前那一行, 表頭, 資料列)。程式碼區塊裡的不算。"""
    lines = text.split("\n")
    heads: list[str] = []
    fenced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and (h := _HEADING.match(line)):
            heads = heads[:len(h[1]) - 1] + [""] * (len(h[1]) - 1 - len(heads)) + [h[2]]
        elif (not fenced and line.lstrip().startswith("|") and i + 1 < len(lines)
              and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*", lines[i + 1])):
            prev = next((lines[j].strip() for j in range(i - 1, -1, -1) if lines[j].strip()), "")
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            yield i + 1, [h for h in heads if h], prev, _cells(line), rows
            i = j
            continue
        i += 1


def _percent_checks(header: list[str], data: list[list[str]], totals: list[list[str]]) -> list[str]:
    """佔比欄逐列驗算:每列的百分比應該等於某個數字欄 ÷ 分母。不知道是哪一欄的佔比,每個數字欄都試;
    差在一個末位以內算相符(各列四捨五入過,也常為了湊 100% 調過一格)。
    2026-10-08、10-15 攝入照本庫規則要「用腳本重算佔比」,權限不能跑 python,只能人工逐格算、寫成未驗。
    分母依序試:(1) 那一欄的合計列、各列加總;(2) 表上沒有的分母(「佔期貨負擔」以表外的 29,763,678 為分母):
    各列反推的分母範圍有交集就算一致;(3) 都不成立時,大部分列對得上才報 ⚠️——約定的分攤比例(26%、44%)
    本來就不是算出來的,報 ⚠️ 的話 claude 會去「改正」對的表。"""
    out = []
    for k, name in enumerate(header):
        col = [_number(r[k]) if k < len(r) else None for r in data]
        n = sum(1 for v in col if v)
        if n < 2 or not all(v[1] for v in col if v):
            continue
        exp = min(v[0].as_tuple().exponent for v in col if v)
        unit = Decimal(1).scaleb(exp)   # 一個末位
        bases = []
        for b, base_name in enumerate(header):
            base = [_number(r[b]) if b < len(r) else None for r in data]
            if b != k and any(x and not x[1] for x in base):
                # 金額是 0 的列(零稅率、沒攤到)怎麼除都對,不算進「對得上幾列」
                pairs = [(r, p[0], x[0]) for r, p, x in zip(data, col, base) if p and x and not x[1] and x[0]]
                bases.append((base_name or f"第 {b + 1} 欄", b, base, pairs))
        # (1) 合計列、各列加總
        best = None
        for base_name, b, base, pairs in bases:
            t = _number(totals[0][b]) if len(totals) == 1 and b < len(totals[0]) else None
            listed = t[0] if t and not t[1] else None
            for total in dict.fromkeys((listed, sum((x[0] for x in base if x and not x[1]), Decimal(0)))):
                if not total:
                    continue
                bad = [f"{r[0].replace('**', '')} 寫 {_fmt(p, True)}、算出 {_fmt((x / total * 100).quantize(unit), True)}"
                       for r, p, x in pairs if abs(p - x / total * 100) > unit]
                if best is None or len(bad) < len(best[2]):
                    best = (base_name, total, bad, len(pairs))
        if best and best[3] and not best[2]:
            out.append(f"  佔比欄 {name}:= {best[0]} ÷ {_fmt(best[1], False)},{best[3]} 列全部相符")
            continue
        # (2) 表外的分母:每列給出分母的範圍 x×100÷(p±一個末位),全部有交集就一致
        found = None
        for base_name, b, base, pairs in bases:
            use = [(p, x) for _, p, x in pairs if p > 0 and x > 0]
            if len(use) < 2:   # 扣回、短計這種負數列不算
                continue
            lo = max(x * 100 / (p + unit) for p, x in use)
            hi = min((x * 100 / (p - unit) for p, x in use if p > unit), default=None)
            if hi is not None and lo <= hi:
                found = (base_name, lo, hi, len(use))
                break
        if found:
            out.append(f"  佔比欄 {name}:= {found[0]} ÷ 表上沒有的分母(各列反推約 {_fmt(found[1].quantize(1), False)}"
                       f"～{_fmt(found[2].quantize(1), False)}),{found[3]} 列一致——請確認頁面寫的分母在這個範圍內")
        elif best and best[3] >= 3 and len(best[2]) * 2 <= best[3]:
            out.append(f"  ⚠️ 佔比欄 {name}:最接近 {best[0]} ÷ {_fmt(best[1], False)},{len(best[2])} 列不符:"
                       + ";".join(best[2][:5]) + (f"…另 {len(best[2]) - 5} 列" if len(best[2]) > 5 else ""))
        else:
            out.append(f"  佔比欄 {name}:對不上表上任何一欄(可能是約定的比例、不是算出來的),沒有驗")
    return out


def table_sums(repo: Path, page: str, heading: str | None = None) -> str:
    """頁面上每張表各數字欄的加總;有一列合計(第一格含「合計」「總計」)的話,比對它與其他列的加總。
    小計列不算進加總;有小計列時合計列另外跟小計列的加總比(分攤總表的「臺北小計」「臺中小計」只有一邊列明細)。"""
    rel = page_path(repo, page)
    f = repo / rel
    if not f.is_file():
        raise PageToolError(f"找不到 {rel}")
    out = []
    for start, heads, prev, header, rows in _tables(f.read_bytes().decode("utf-8", "replace")):
        # 公事庫的統計表多半用表前一行粗體標示(**依負擔單位**:),不是標題:兩個都比
        if heading and not any(heading in h for h in heads) and heading not in prev:
            continue
        first = [r[0].replace("**", "") if r else "" for r in rows]
        subs = [r for r, c in zip(rows, first) if _SUBTOTAL_ROW.search(c)]
        totals = [r for r, c in zip(rows, first) if _TOTAL_ROW.search(c) and not _SUBTOTAL_ROW.search(c)]
        data = [r for r in rows if r not in totals and r not in subs]
        where = "〈" + " > ".join(heads) + "〉" if heads else ""
        label = prev[:40] if prev and not prev.startswith("#") else ""
        out.append(f"第 {start} 行{where}{label}:{len(data)} 列" + (f"、另有 {len(subs)} 列小計" if subs else "")
                   + (f"、{len(totals)} 列合計" if totals else ""))
        for k, name in enumerate(header):
            vals = [_number(r[k]) if k < len(r) else None for r in data]
            nums = [v for v in vals if v]
            if not nums:
                continue
            pct = all(p for _, p in nums)
            total = sum((v for v, _ in nums), Decimal(0))
            other = sum(1 for r, v in zip(data, vals) if v is None and k < len(r) and r[k])
            line = f"  {name or f'第 {k + 1} 欄'}:加總 {_fmt(total, pct)}"
            if other:
                line += f"(另有 {other} 格不是數字、沒算進去)"
            if len(totals) == 1 and k < len(totals[0]) and (t := _number(totals[0][k])):
                sub = sum((v[0] for r in subs if k < len(r) and (v := _number(r[k]))), Decimal(0))
                # 百分比各列四捨五入過:加總差在「每列最多差半個末位」以內是正常的
                tol = Decimal(0) if not pct else len(nums) * Decimal(5).scaleb(
                    min(v.as_tuple().exponent for v, _ in nums) - 1)
                if t[0] == total:
                    line += ",合計列相符"
                elif abs(t[0] - total) <= tol:
                    line += f",合計列寫 {_fmt(*t)}、差 {_fmt(t[0] - total, pct)}(在四捨五入誤差內)"
                elif subs and t[0] == sub:
                    line += ",合計列與小計列的加總相符"
                else:
                    line += f",⚠️ 合計列寫 {_fmt(*t)}、差 {_fmt(t[0] - total, pct)}"
                    line += f"(小計列加總 {_fmt(sub, pct)})" if subs else ""
            out.append(line)
        out += _percent_checks(header, data, totals)
    if not out:
        return f"{rel}:沒有表格" + (f"(標題含「{heading}」的段落裡)" if heading else "")
    return "\n".join(out)
