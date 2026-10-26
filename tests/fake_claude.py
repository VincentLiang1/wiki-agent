"""假的 `claude -p` 攝入:在 cwd(假 FWIKI)照 FAKE_CLAUDE_MODE 做事,模擬真的攝入會留下的痕跡。

ok        寫一頁、git commit(不 push),回報群組「會議與月報」;不碰原件(搬移由程式做)
nocommit  什麼都沒 commit
clobber   拿原件蓋掉同群組既有的原件(模擬失控的攝入)
dirty     commit 之後又留下一個沒 commit 的檔
rm        直接刪掉原件
push      自己偷偷 git push(驗證程式不靠它推)
skip      判斷不該攝入:不建頁、不 commit,回報 decision=skipped
backfill_only  只在個人 WIKI commit、沒動公事庫
backfill  正常攝入,又在個人 WIKI commit(攝入不准碰 WIKI)
apidown   連不上 API:什麼都不做,回報 is_error(真實訊息照抄 2026-10-05 斷網那次)
halfway   寫了一頁還沒 commit 就死掉(逾時、被 unstick 砍掉):不印 JSON
loggedout 沒登入:stdout 什麼都沒有、stderr 印真的 claude 的那句(2026-10-20 實測)
loggedout_json  沒登入,但照 --output-format json 回報 is_error(真的 claude 兩種都見過)
回報格式的 group 清單是空的時候,跟真的 claude 一樣一開始就報錯結束(2026-10-20 新庫實測踩到)
FAKE_CLAUDE_GROUP  回報的群組(預設「會議與月報」)
FAKE_CLAUDE_SUBPATH  回報的 raw_subpath(照本庫規則放進子資料夾、改名),頁面來源跟著寫
FAKE_CLAUDE_BREAK_REMOTE  commit 之後把 origin 指到不存在的地方(模擬攝入到一半斷網)
FAKE_CLAUDE_PAGE_EXTRA  新頁最後多寫這一段(例如失效的粗體)
FAKE_CLAUDE_DIE_ON  攝入這個檔名時 commit 完就死掉、不印 JSON(commit 之後逾時、被 unstick 砍掉)
FAKE_CLAUDE_DIRTY  不管哪種模式,最後都留下 暫存.txt(例如 backfill 又留暫存檔)
FAKE_CLAUDE_STAGE  正常攝入之外(off:什麼都不改),照公事庫規則回填到個人 WIKI 的副本(提示裡給的路徑):
                    new 新增一頁通用知識、leak 新增的頁提到 甲公司(測試設定的回填禁字)、script 改知識圖譜/ 的腳本、graph 改知識圖譜/ 的 .md、
                    nonmd 新增一個 .txt、delete 刪掉副本裡的 index.md、cut 把副本裡的 長頁.md 刪到剩 5 行、
                    bold 新增的頁有一處 CJK 粗體失效
FAKE_CLAUDE_BREAK_WIKI_REMOTE  把個人 WIKI 的 origin 指到不存在的地方(回填寫回後推不上去)
FAKE_CLAUDE_SHRINK  同一個 commit 裡順手改既有的 Wiki_Pages/大頁.md:cut 刪到剩 10 行、rewrite 整頁改寫成
                    75 行(淨刪 25 行、佔原檔 25%)、mv 原封不動改名成 搬走.md、rm 整個 git rm 掉 index.md
FAKE_CLAUDE_RECENT  照公事庫規則更新 Wiki_Pages/index.md:最近異動頂端加這一頁、擠掉最後一筆,頁面列表開頭加一筆摘要
提示說「程式驗證後代為 commit」(程式代管 git 的庫)時不 commit、回報 commit_message;
FAKE_CLAUDE_SELF_COMMIT  代管的庫卻照樣自己 commit(權限沒擋住)
FAKE_CLAUDE_GUARDED  同一個 commit 裡順手改 tools/make_handout.py(tools)或 .claude/settings.local.json(claude);
                    dirty:commit 之後才改 tools/make_handout.py、不 commit
FAKE_CLAUDE_UNVERIFIED  回報的 unverified(JSON 字串陣列;做不到的檢查)
FAKE_CLAUDE_DENIALS  回報的 permission_denials(JSON;被權限擋下的工具呼叫)
FAKE_CLAUDE_NOREPORT  照常 commit,但結束時沒有 structured_output(花完預算:subtype error_max_budget_usd)
FAKE_CLAUDE_GLOSSARY  照提示把這段寫進 memory/name-corrections.md(朋友的名詞校正表)
FAKE_CLAUDE_SCOPE  回報的 scope(回報格式有這欄才交;預設 company)。personal:公事庫什麼都不寫、不 commit,
                    只在個人 WIKI 副本建頁(FAKE_CLAUDE_STAGE 沒設就當成 new);personal_commit:回報 personal 卻照常 commit 公事庫
FAKE_CLAUDE_PERSONAL_GROUP  回報的 personal_group(預設:scope 是 personal 時「健康生活」,其餘空字串)
參數記在 FAKE_CLAUDE_ARGS。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import _lf  # noqa: F401 —— Windows 上 write_text 寫 LF(同目錄)

args = sys.argv[1:]
if os.environ.get("FAKE_CLAUDE_ARGS"):
    with open(os.environ["FAKE_CLAUDE_ARGS"], "a", encoding="utf-8") as f:
        f.write(json.dumps(args, ensure_ascii=False) + "\n")
prompt = sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
_group_schema = json.loads(args[args.index("--json-schema") + 1])["properties"]["group"]
if "enum" in _group_schema and not _group_schema["enum"]:
    print("Error: --json-schema is not a valid JSON Schema: data/properties/group/enum must NOT have fewer than 1 items",
          file=sys.stderr)
    sys.exit(1)
if mode == "loggedout":
    print("Not logged in · Please run /login", file=sys.stderr)
    sys.exit(1)
if mode == "loggedout_json":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}))
    sys.exit(0)
managed = "程式驗證後代為 commit" in prompt
repo = Path.cwd()
src = Path(re.search(r"本機位置 (.+?);", prompt).group(1))
raw_root = src.parent.parent


def git(*a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True,
                   capture_output=True)


if mode == "apidown":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "API Error: Connection refused — a firewall or proxy may be blocking it (ECONNREFUSED)"},
                     ensure_ascii=False))
    sys.exit(0)
subpath = os.environ.get("FAKE_CLAUDE_SUBPATH", "")
scope = os.environ.get("FAKE_CLAUDE_SCOPE", "company")
if mode == "halfway":
    page = repo / "Wiki_Pages" / "會議與月報" / f"{src.stem}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# 寫到一半\n", encoding="utf-8")
    sys.exit(143)
if mode in ("backfill_only", "backfill"):
    # 攝入不准碰 WIKI(程式不給 --add-dir),模擬它照 FWIKI 的回填規則硬寫進旁邊的 WIKI
    other = repo.parent / "WIKI"
    (other / "Wiki_Pages" / "回填.md").write_text("# 回填\n", encoding="utf-8")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=other, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "backfill"],
                   cwd=other, check=True)
if mode not in ("nocommit", "skip", "backfill_only") and scope != "personal":
    group = raw_root / "會議與月報"
    if mode == "rm":
        src.unlink()
    elif mode == "clobber":
        victim = next(p for p in group.iterdir() if p.is_file())
        os.replace(src, victim)
    page = repo / "Wiki_Pages" / "會議與月報" / f"{src.stem}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# {src.stem}\n\n來源:`FRaw_Sources\\會議與月報\\{subpath or src.name}`\n"
                    + os.environ.get("FAKE_CLAUDE_PAGE_EXTRA", ""), encoding="utf-8")
    shrink = os.environ.get("FAKE_CLAUDE_SHRINK")
    big = repo / "Wiki_Pages" / "大頁.md"
    if shrink == "cut":
        big.write_text("".join(big.read_text(encoding="utf-8").splitlines(keepends=True)[:10]), encoding="utf-8")
    elif shrink == "rewrite":
        big.write_text("".join(f"改寫第 {i} 行\n" for i in range(75)), encoding="utf-8")
    elif shrink == "mv":
        git("mv", "Wiki_Pages/大頁.md", "Wiki_Pages/搬走.md")
    elif shrink == "rm":
        git("rm", "-q", "Wiki_Pages/index.md")
    guarded = os.environ.get("FAKE_CLAUDE_GUARDED")
    if guarded in ("tools", "claude"):
        f = repo / ("tools/make_handout.py" if guarded == "tools" else ".claude/settings.local.json")
        f.parent.mkdir(exist_ok=True)
        f.write_text("x\n", encoding="utf-8")
    if os.environ.get("FAKE_CLAUDE_GLOSSARY"):
        (repo / "memory").mkdir(exist_ok=True)
        (repo / "memory" / "name-corrections.md").write_text(os.environ["FAKE_CLAUDE_GLOSSARY"], encoding="utf-8")
    if os.environ.get("FAKE_CLAUDE_RECENT"):
        idx = repo / "Wiki_Pages" / "index.md"
        text = idx.read_text(encoding="utf-8")
        head, rest = text.split("## 最近異動\n\n", 1)
        entries, tail = rest.split("\n\n", 1)
        lines = entries.splitlines()
        new = [f"- [會議與月報/{src.stem}](會議與月報/{src.stem}.md)"] + lines[:len(lines) - 1]
        tail = tail.replace("## 頁面列表\n\n", f"## 頁面列表\n\n- [{src.stem}](會議與月報/{src.stem}.md) — 新頁\n", 1)
        idx.write_text(head + "## 最近異動\n\n" + "\n".join(new) + "\n\n" + tail, encoding="utf-8")
    if not managed:   # 程式代管 git 的庫:claude 只改檔,程式代為 commit
        git("add", "-A")
        git("commit", "-q", "-m", f"docs(ingest): {src.stem}")
    elif os.environ.get("FAKE_CLAUDE_SELF_COMMIT"):   # 代管的庫卻自己 commit 了(權限沒擋住)
        git("add", "-A")
        git("commit", "-q", "-m", "偷偷 commit")
    if guarded == "dirty":
        (repo / "tools").mkdir(exist_ok=True)
        (repo / "tools" / "make_handout.py").write_text("x\n", encoding="utf-8")
    if os.environ.get("FAKE_CLAUDE_BREAK_REMOTE"):
        git("remote", "set-url", "origin", str(repo.parent / "斷網.git"))
    if mode == "dirty":
        (repo / "暫存.txt").write_text("x", encoding="utf-8")
    if mode == "push":
        git("push", "-q", "origin", "HEAD:master")
    if os.environ.get("FAKE_CLAUDE_DIE_ON") == src.name:
        sys.exit(143)

stage_mode = os.environ.get("FAKE_CLAUDE_STAGE", "") or ("new" if scope == "personal" else "")
stage_mode = "" if stage_mode == "off" else stage_mode   # off:副本什麼都不改
wiki_msg = ""
if stage_mode:
    stage = Path(re.search(r"個人 WIKI 的頁面副本在 (.+?)\(", prompt).group(1))
    pages = stage / "Wiki_Pages"
    body = "# 通用知識\n\n期貨市場的一般做法。\n"
    if stage_mode == "leak":
        body += "甲公司內部的做法。\n"
    if stage_mode == "bold":
        body += "前文**X（Y）**中文\n"
    if stage_mode == "script":
        (pages / "知識圖譜").mkdir(parents=True, exist_ok=True)
        (pages / "知識圖譜" / "_check.py").write_text("import os; os.system('echo pwned')\n", encoding="utf-8")
    elif stage_mode == "graph":
        (pages / "知識圖譜").mkdir(parents=True, exist_ok=True)
        (pages / "知識圖譜" / "_typed_graph.md").write_text("# 圖\n", encoding="utf-8")
    elif stage_mode == "nonmd":
        (pages / "筆記.txt").write_text("x", encoding="utf-8")
    elif stage_mode == "delete":
        (pages / "index.md").unlink()
    elif stage_mode == "cut":
        (pages / "長頁.md").write_text("".join(f"第 {i} 行\n" for i in range(5)), encoding="utf-8")
    (pages / "通用知識.md").write_text(body, encoding="utf-8")
    idx = pages / "index.md"
    if idx.exists():
        idx.write_text(idx.read_text(encoding="utf-8") + "- [通用知識](通用知識.md)\n", encoding="utf-8")
    wiki_msg = "docs(backfill): 通用知識\n\n來源:網路公開資料"
    if stage_mode == "msg":   # 頁面乾淨,commit message 卻交代了「沒有回填公事庫」(2026-10-26 實例)
        wiki_msg += "\n- 沒有回填 FWIKI:通用內容\n- 參考 甲公司 的做法\n\nCo-Authored-By: x"

if os.environ.get("FAKE_CLAUDE_BREAK_WIKI_REMOTE"):   # 攝入到一半斷網:個人庫推不上去
    subprocess.run(["git", "remote", "set-url", "origin", str(repo.parent / "斷網.git")], cwd=repo.parent / "WIKI", check=True)

if os.environ.get("FAKE_CLAUDE_DIRTY"):
    (repo / "暫存.txt").write_text("x", encoding="utf-8")

structured = {
    "pages": [{"repo": "FWIKI", "path": f"Wiki_Pages/會議與月報/{src.stem}.md", "action": "new",
               "summary": "測試頁"}],
    "decision": "skipped" if mode == "skip" else "ingested",
    "skip_reason": "看起來是私人證件照、誤收" if mode == "skip" else "",
    "group": os.environ.get("FAKE_CLAUDE_GROUP", "會議與月報"),
    "raw_subpath": subpath,
    "questions": ["要不要補查網路資料?"],
    "unverified": json.loads(os.environ.get("FAKE_CLAUDE_UNVERIFIED", "[]")),
    "summary": "攝入一筆",
    "wiki_commit_message": wiki_msg,
    "scope": "personal" if scope.startswith("personal") else scope,
    "personal_group": os.environ.get("FAKE_CLAUDE_PERSONAL_GROUP", "健康生活" if scope.startswith("personal") else ""),
}
if managed:
    structured["commit_message"] = f"攝入:{src.name}——測試頁"
schema = json.loads(args[args.index("--json-schema") + 1])
structured = {k: v for k, v in structured.items() if k in schema["properties"]}   # 照這次給的回報格式交
if os.environ.get("FAKE_CLAUDE_NOREPORT"):
    print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                      "total_cost_usd": 5.03, "num_turns": 61, "duration_ms": 497000}))
    sys.exit(0)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok",
                  "structured_output": structured, "total_cost_usd": 0.01,
                  "permission_denials": json.loads(os.environ.get("FAKE_CLAUDE_DENIALS", "[]"))},
                 ensure_ascii=False))
