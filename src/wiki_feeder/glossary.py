"""名詞對照表:知識庫裡的名詞校正 → 手機 App 用的 `name-corrections.json`,放進聲紋同步資料夾(spec §5.14)。

手機(scribe2md 的「送進知識庫」模式)產生會議草稿前,用它把語音辨識聽錯的人名、公司、術語換成正確寫法;
逐字稿 md 本身不動。對照表含真名:**只寫到聲紋同步資料夾**,絕不寫進收件匣、原件樹或知識庫(`unsafe_out`)。

兩種來源:
- 使用者本人的公事庫(`cfg.glossary_fwiki`):照那個庫自己的規則寫的 `memory/asr-name-corrections.md`
  (「誤譯／誤譯」＝**正確**,`- <會議系列> MMDD …` 開頭的是那個系列的分組)與各場整理頁的「## 名詞與人名校正」一節。
  2026-10-24 從 scribe2md-ios 的 `scripts/name_corrections.py` 移過來(使用者:「這樣才不會忘記改」),結果與它逐條相同
- 朋友的庫:攝入的 claude 照提示維護的 `memory/name-corrections.md`,一張表 `| 聽錯的寫法 | 正確寫法 | 分組 |`
  (使用者 2026-10-24 選:英文、簡中的朋友也能用);只看欄位位置,不看表頭的字

**通用裡兩個字的中文誤譯一律不收**(2026-10-19 實測:「基金」「政策」這類在別場是正常用語,每場都換會改壞),
分組裡的照收。每一輪攝入後看庫的 HEAD、校正檔與分組規則有沒有變(`_stamp`),沒變不解析;內容沒變不寫(不吵 iCloud)。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import subprocess
from pathlib import Path

from .config import Config
from .i18n import N_, L, variants

log = logging.getLogger(__name__)

FWIKI_MEMORY = "memory/asr-name-corrections.md"
TABLE_FILE = "memory/name-corrections.md"   # 朋友的庫;ingest._managed_commit 另外收這一個檔
OUT_NAME = "name-corrections.json"          # 手機 App 的 NameCorrections.fileName
MAX_BYTES = 2_000_000                        # 校正檔是攝入的 claude 寫的(不可信):太大就不解析,留著舊的對照表
MAX_WRONGS = 20_000
STAMP_VERSION = 1                            # 解析規則改了就加一:換版後重產一次

UNSURE = re.compile(r"疑|判讀|待確認|（音|\(音|全名")
SEP = re.compile(r"[／/、]")
TABLE_SEP = re.compile(r"[／/、,，;；]")
# 「誤譯／誤譯」＝**正確**(memory 檔);＝ 與 ** 之間不能有別的字(「＝視語境指**…**」這種不是對照)
QUOTED = re.compile(r"「([^」]{1,40})」(?:「[^」]{1,40}」)*＝\*\*([^*]{1,30})\*\*")
# 頁面的「誤譯／誤譯＝**正確**」:誤譯那段到前一個「；」「。」「：」或行首為止
INLINE = re.compile(r"(?:^|[；;。：:\n])\s*([^；;。：:\n＝*]{1,60})＝\*\*([^*]{1,30})\*\*")
# memory 檔大多數條目是「- 大中華會議 0824 逐字稿(…)判讀:「…」＝**…**」:那場說的誤譯只在那個系列換
MEETING_LINE = re.compile(r"^- (?:\*\*)?([^「：:（(*\d]{2,24}?)\s?\d{4}")
CJK2 = re.compile(r"^[㐀-鿿]{2}$")
SEPARATOR_CELL = re.compile(r"^:?-+:?$")

Table = dict[str, set[str]]


class GlossaryError(Exception):
    pass


# 朋友知識庫的 CLAUDE.md 最後由程式補上的一節(使用者 2026-10-24:對照表是「平常告訴 AI 哪場會議哪裡不正確,
# 逐步累積下來的」,不是另外維護一個檔)。朋友自己開 Claude 桌面版說「這裡寫錯了」時讀的是 CLAUDE.md、不是攝入提示,
# 沒有這一節就只改頁面、不記進表,下一場照樣錯。固定文字、不交給 claude 寫;安裝時補(scripts/winsetup.py 的
# add_glossary_section,比照「版本紀錄」那一節)
RULE_HEADING = N_("## 名詞校正表(手機的會議草稿用)")
RULE_BODY = N_("""語音辨識常把人名、公司、產品、術語聽成同音字。這個庫把確定的更正記在 `{file}`,wiki-feeder 每一輪攝入後
把它轉給手機 App,之後的會議草稿就照正確寫法。

- **使用者指出哪場會議哪裡寫錯時**(例如「10/21 業務週會那頁的『王小明』應該是『王筱明』」):改正頁面,**同時把這條記進這個表**
  (新增一列,或補進既有那一列)。是語音辨識聽錯的才記;單純筆誤、內容本身的更正不記
- 攝入逐字稿前先讀這個表,頁面照它寫正確寫法;攝入時自己確定是聽錯的,也記進來
- 格式:第一行 `# 名詞校正`,接著一張表 `| 聽錯的寫法 | 正確寫法 | 分組 |`;一個正確寫法一列,聽錯的寫法有好幾種用「、」隔開
- 分組:只在某個會議系列會聽錯、換到別場會改壞的,填那個系列的名字(手機對名稱含這幾個字的會議套用);每場都適用就空白。
  **兩個字的中文詞只有填了分組才會套用**
- 沒把握的不要記;正確寫法還不確定就在後面加 `?`(不會被套用)。使用者說換錯了才刪那一列
""")


def has_rule(text: str) -> bool:
    """三種語言的標題都算(換了語言不再補一次)。"""
    return any(h in text for h in variants(RULE_HEADING))


def rule_section(lang: str) -> str:
    return "\n" + L(RULE_HEADING, lang) + "\n\n" + L(RULE_BODY, lang, file=TABLE_FILE)


def clean_right(s: str) -> str:
    return s.strip().strip("「」")


def split_wrong(s: str, sep: re.Pattern = SEP) -> list[str]:
    out = []
    for w in sep.split(s):
        w = w.strip().strip("「」*`").strip()
        if len(w) >= 2:
            out.append(w)
    return out


def add(table: Table, wrongs: list[str], right: str, skipped: list[str]) -> None:
    right = clean_right(right)
    if not right or UNSURE.search(right):
        skipped.append(f"{'/'.join(wrongs)} → {right}(未確定)")
        return
    ws = [w for w in wrongs if w != right and not UNSURE.search(w)]
    if ws:
        table.setdefault(right, set()).update(ws)


def series(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _drop_short(wrongs: list[str], right: str, skipped: list[str], why: str) -> list[str]:
    short = [w for w in wrongs if CJK2.match(w)]
    if short:
        skipped.append(f"{'/'.join(short)} → {right}({why})")
    return [w for w in wrongs if not CJK2.match(w)]


# -- 公事庫的寫法 ----------------------------------------------------------------------

def parse_memory(text: str, skipped: list[str]) -> tuple[Table, dict[str, Table]]:
    """→(通用, 各系列)。沒寫是哪一場的條目才算通用。"""
    common: Table = {}
    groups: dict[str, Table] = {}
    for line in text.splitlines():
        mm = MEETING_LINE.match(line)
        target = groups.setdefault(series(mm.group(1)), {}) if mm else common
        for m in QUOTED.finditer(line):
            # 同一個 match 前面可能還有幾個「…」:全部當誤譯
            head = m.group(0).split("＝")[0]
            wrongs = [w for q in re.findall(r"「([^」]+)」", head) for w in split_wrong(q)]
            if target is common:
                wrongs = _drop_short(wrongs, m.group(2), skipped, "通用不收兩字")
            add(target, wrongs, m.group(2), skipped)
    return common, {k: v for k, v in groups.items() if v}


def parse_page_section(text: str, skipped: list[str]) -> Table:
    table: Table = {}
    for line in text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and "**" in cells[1] and not set(cells[0]) <= set("-: "):
                right = re.search(r"\*\*([^*]+)\*\*", cells[1]).group(1)
                if UNSURE.search(cells[1].replace(f"**{right}**", "")) and "判讀" in cells[1]:
                    skipped.append(f"{cells[0]} → {cells[1]}(未確定)")
                    continue
                add(table, split_wrong(cells[0]), right, skipped)
            continue
        for m in INLINE.finditer(line):
            seg = re.sub(r"^\**[^*]*\**[：:]", "", m.group(1))   # 「**沿用既有對照**：」這類開頭
            add(table, split_wrong(seg), m.group(2), skipped)
    return table


def section(md: str, heading_re: str) -> str | None:
    m = re.search(rf"^## {heading_re}\s*$(.*?)(?=^## |\Z)", md, re.M | re.S)
    return m.group(1) if m else None


def apply_rules(rules: dict, common: Table, groups: dict[str, Table], skipped: list[str]) -> tuple[dict[str, Table], list[str]]:
    """merge:併成一組;toCommon:一次性的會議併進通用(兩個字的中文不收,同通用的規則);keep 與其他照原樣。
    回傳(整理後的分組, 規則沒提到的組名)"""
    merged_from = {g: k for k, gs in rules.get("merge", {}).items() for g in gs}
    to_common = set(rules.get("toCommon", []))
    known = set(merged_from) | to_common | set(rules.get("keep", []))
    out: dict[str, Table] = {}
    for name, table in groups.items():
        if name in to_common:
            for r, ws in table.items():
                add(common, _drop_short(list(ws), r, skipped, "併進通用、不收兩字"), r, skipped)
            continue
        target = out.setdefault(merged_from.get(name, name), {})
        for r, ws in table.items():
            target.setdefault(r, set()).update(ws)
    return out, sorted(n for n in groups if n not in known)


def _read(p: Path) -> str:
    if p.stat().st_size > MAX_BYTES:
        raise GlossaryError(L("{path} 超過 {n} bytes,不解析", path=p, n=MAX_BYTES))
    return p.read_text(encoding="utf-8-sig")


def parse_fwiki(repo: Path, skipped: list[str], before: str | None = None) -> tuple[Table, dict[str, Table]]:
    common, groups = parse_memory(_read(repo / FWIKI_MEMORY), skipped)
    for p in sorted((repo / "Wiki_Pages").rglob("*.md")):
        d = re.search(r"(\d{4}-\d{2}-\d{2})$", p.stem)
        if before and d and d.group(1) >= before:
            continue
        sec = section(_read(p), r"名詞(?:與人名)?校正")
        if sec is None:
            continue
        name = series(re.sub(r"[-_ ]?\d{4}-?\d{2}-?\d{2}$", "", p.stem))
        g = groups.setdefault(name, {})
        for r, ws in parse_page_section(sec, skipped).items():
            g.setdefault(r, set()).update(ws)
    return common, groups


# -- 朋友的表格 ------------------------------------------------------------------------

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and all(SEPARATOR_CELL.match(c) for c in _cells(s))


def parse_table(text: str, skipped: list[str]) -> tuple[Table, dict[str, Table]]:
    """`| 聽錯的寫法 | 正確寫法 | 分組 |`:表頭(下一行是分隔列的那一行)與分隔列跳過,表頭寫什麼語言都可以。
    聽錯的寫法可以有好幾個(、／,; 隔開);分組空白 = 通用;正確寫法帶問號的不收(還沒確定)。"""
    common: Table = {}
    groups: dict[str, Table] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("|") or _is_separator(line):
            continue
        if i + 1 < len(lines) and _is_separator(lines[i + 1]):
            continue
        cells = _cells(line)
        if len(cells) < 2:
            continue
        right = cells[1].strip("*` ").strip()
        group = series(cells[2].strip("*` ")) if len(cells) >= 3 else ""
        wrongs = split_wrong(cells[0], TABLE_SEP)
        if not right or len(right) > 40 or len(group) > 40 or "?" in right or "？" in right:
            skipped.append(f"{cells[0]} → {cells[1]}(未確定)")
            continue
        if not group:
            wrongs = _drop_short(wrongs, right, skipped, "通用不收兩字")
        ws = [w for w in wrongs if w != right and len(w) <= 40]
        if ws:
            (groups.setdefault(group, {}) if group else common).setdefault(right, set()).update(ws)
    return common, {k: v for k, v in groups.items() if v}


# -- 產生與寫出 ------------------------------------------------------------------------

def to_entries(table: Table) -> list[dict]:
    return [{"wrong": sorted(ws), "right": r} for r, ws in sorted(table.items())]


def build(repo: Path, fwiki: bool, rules: Path | None = None,
          before: str | None = None) -> tuple[dict, list[str], list[str]]:
    """→(對照表, 略過的條目, 規則沒列到的分組)。規則只用在公事庫的寫法(朋友的表格自己寫了分組)。"""
    skipped: list[str] = []
    if fwiki:
        common, groups = parse_fwiki(repo, skipped, before)
    else:
        common, groups = parse_table(_read(repo / TABLE_FILE), skipped)
    unruled: list[str] = []
    if fwiki and rules is not None and rules.exists():
        groups, unruled = apply_rules(json.loads(rules.read_text(encoding="utf-8")), common, groups, skipped)
    doc = {"common": to_entries(common), "groups": {k: to_entries(v) for k, v in sorted(groups.items()) if v}}
    n = sum(len(e["wrong"]) for es in (doc["common"], *doc["groups"].values()) for e in es)
    if n > MAX_WRONGS:
        raise GlossaryError(L("名詞對照表有 {n} 個誤譯,超過上限 {max},不寫", n=n, max=MAX_WRONGS))
    return doc, skipped, unruled


def render(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True)


def write(out_dir: Path, doc: dict) -> bool:
    """內容(不算 generatedAt)沒變就不寫。回傳有沒有寫。"""
    out = out_dir / OUT_NAME
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
        old.pop("generatedAt", None)
    except (OSError, ValueError, AttributeError):
        old = None
    if old == json.loads(render(doc)):
        return False
    doc = dict(doc, generatedAt=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    tmp = out.with_name("." + out.name)   # 「.」開頭:iCloud 不同步寫到一半的檔
    tmp.write_text(render(doc), encoding="utf-8")
    os.replace(tmp, out)
    return True


def counts(doc: dict) -> str:
    n_common = sum(len(e["wrong"]) for e in doc["common"])
    n_groups = {k: sum(len(e["wrong"]) for e in v) for k, v in doc["groups"].items()}
    return L("通用 {n} 個誤譯、分組 {groups}", n=n_common,
             groups=L("、").join(f"{k} {v}" for k, v in n_groups.items()) or L("(沒有)"))


def unsafe_out(cfg: Config, out: Path) -> Path | None:
    """輸出資料夾在收件匣、原件樹、知識庫裡(或包著它們)就回傳撞到的那一個:對照表含真名,
    放進收件匣會被收走、攝入(scribe2md-ios 的安裝腳本原本就擋 _WikiBox)。"""
    o = out.resolve()
    guarded = [cfg.icloud_inbox, cfg.onedrive_inbox, cfg.pending_dir, *cfg.raw_roots,
               *(rc.repo_dir for rc in cfg.repos), *(rc.raw_root for rc in cfg.repos)]
    for p in (p for p in guarded if p is not None):
        r = p.resolve()
        if o == r or r in o.parents or o in r.parents:
            return p
    return None


# -- 每一輪 ----------------------------------------------------------------------------

def _source(cfg: Config) -> Path:
    return cfg.repo(cfg.target_repo).repo_dir / (FWIKI_MEMORY if cfg.glossary_fwiki else TABLE_FILE)


def _stat(p: Path | None) -> list:
    try:
        st = p.stat() if p is not None else None
    except OSError:
        st = None
    return [st.st_mtime_ns, st.st_size] if st else []


def _stamp(cfg: Config) -> list:
    repo = cfg.repo(cfg.target_repo).repo_dir
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    head = r.stdout.strip() if r.returncode == 0 else ""
    return [STAMP_VERSION, head, _stat(_source(cfg)), _stat(cfg.glossary_rules),
            (cfg.glossary_dir / OUT_NAME).exists()]


def _state(cfg: Config) -> dict:
    try:
        return json.loads(cfg.glossary_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(cfg: Config, state: dict) -> None:
    cfg.glossary_state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def refresh(cfg: Config) -> list[str]:
    """攝入那一輪結束時呼叫(STOP 中不叫:沒驗證過的內容不送到手機)。回傳警示。
    沒有聲紋同步資料夾(朋友沒做安裝說明第 7 節)、還沒有校正檔就什麼都不做。"""
    out = cfg.glossary_dir
    if out is None:
        return []
    if (hit := unsafe_out(cfg, out)) is not None:
        return [L("名詞對照表不寫:輸出資料夾 {out} 跟 {hit} 重疊(對照表含真名,會被收件或攝入);"
                  "聲紋同步資料夾要另外建在雲碟最上層", out=out, hit=hit)]
    if not out.is_dir() or not _source(cfg).is_file():
        return []
    state = _state(cfg)
    stamp = _stamp(cfg)
    if state.get("stamp") == stamp:
        return []
    try:
        doc, skipped, unruled = build(cfg.repo(cfg.target_repo).repo_dir, cfg.glossary_fwiki, cfg.glossary_rules)
        if write(out, doc):
            log.info(L("名詞對照表已更新(%s):%s、略過 %d 條未確定"), out / OUT_NAME, counts(doc), len(skipped))
    except (OSError, ValueError, GlossaryError) as e:
        # 留著舊的對照表;記下這次的戳記,同一份內容不每分鐘重試、洗 log
        log.warning(L("名詞對照表沒更新:%s"), e)
        unruled = state.get("unruled", [])
    state.update(stamp=_stamp(cfg), unruled=unruled)
    _save(cfg, state)
    return []


def new_groups(cfg: Config) -> list[str]:
    """分組規則沒列到、還沒在摘要信提過的分組(使用者 2026-10-24 選:列進當日摘要信、同一組只提一次、不算警示)。
    只有設了分組規則才有(朋友的表格自己寫分組,沒有規則可列)。"""
    if cfg.glossary_rules is None:
        return []
    state = _state(cfg)
    told = set(state.get("notified", []))
    return [g for g in state.get("unruled", []) if g not in told]


def mark_notified(cfg: Config, groups: list[str]) -> None:
    state = _state(cfg)
    state["notified"] = sorted(set(state.get("notified", [])) | set(groups))
    _save(cfg, state)


def summary_lines(cfg: Config, groups: list[str]) -> list[str]:
    return [L("### 名詞對照表"),
            L("- 分組規則沒列到的新分組(先照原樣自成一組,手機照常能用):{groups}。要合併、獨立或併進通用,"
              "跟 Claude 說,改 `{rules}`", groups=L("、").join(groups), rules=cfg.glossary_rules)]
