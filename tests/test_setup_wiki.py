"""安裝問答的知識庫那一題(scripts/winsetup.py,Mac 的 macsetup.py 共用):預設值、照講義建庫、補上代管 git 的規則。

claude 一律換成假的(只建檔、不連網)。使用者 2026-10-20:每題都要有預設答案;目錄不存在就建、沒有 CLAUDE.md
照〈LLM Wiki 新手教學講義-桌面版〉建;已經有 CLAUDE.md 不覆蓋,頂多補上 git 那一節。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ws = _mod("winsetup")


def _fake_claude(writes: dict[str, str], seen: list):
    def run(args, cwd, input, **k):
        seen.append((args, input))
        for rel, text in writes.items():
            p = Path(cwd) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": "建好了"}), "")
    return run


def test_defaults_follow_the_owners_layout_and_claude_login(tmp_path):
    """預設值:找得到有 CLAUDE.md 的 WIKI 就用它,找不到就是使用者本人的擺法;寄件信箱用 claude 登入的 Gmail。"""
    assert ws.find_wiki(tmp_path) is None
    assert ws.default_wiki(tmp_path, False) == tmp_path / "SOURCE5" / "WIKI"
    assert ws.default_wiki(tmp_path, True) == Path("C:/SOURCE5/WIKI")
    (tmp_path / "LLMWIKI" / "WIKI").mkdir(parents=True)
    (tmp_path / "LLMWIKI" / "WIKI" / "CLAUDE.md").write_text("# 規則\n", encoding="utf-8")
    assert ws.find_wiki(tmp_path) == tmp_path / "LLMWIKI" / "WIKI"
    assert ws.mail_default({"email": "Amy@Gmail.com"}) == "Amy@Gmail.com"
    assert ws.mail_default({"email": "amy@example.com"}) == ""      # 不是 Gmail:寄不出去,不當預設
    assert ws.mail_default({}) == ""


def test_new_wiki_is_built_from_the_handout_prompt_with_file_tools_only(tmp_path):
    wiki, raw = tmp_path / "LLMWIKI" / "WIKI", tmp_path / "LLMWIKI" / "Raw_Sources"
    seen = []
    ok, said = ws.scaffold_wiki(Path("/x/claude"), wiki, raw, False,
                                run=_fake_claude({"CLAUDE.md": "# 規則\n", "Wiki_Pages/index.md": "# 索引\n"}, seen))
    assert ok and "建好了" in said
    assert (raw / "_Pending").is_dir() and not (raw / "_待處理").exists()   # 新安裝一律英文(使用者 2026-10-24)
    ((args, prompt),) = seen
    assert "Bash" not in " ".join(args) and "--dangerously-skip-permissions" not in args
    assert "../Raw_Sources/" in prompt and "\\" not in prompt              # Mac 的路徑寫法
    assert "_Pending/" in prompt and "_待處理" not in prompt                # 講義寫實際建的資料夾
    assert "[[名稱]]" in prompt and "不要停下來問" in prompt and "不要執行 git" in prompt
    assert "已經有的檔" not in prompt                                       # 空資料夾不必多講
    assert "..\\Raw_Sources\\" in ws.handout_prompt(wiki, raw, True)       # Windows 照講義原文


def test_scaffold_never_overwrites_what_was_already_there(tmp_path):
    """資料夾裡已經有頁(只是缺 CLAUDE.md):claude 改到、刪掉的照原樣寫回;提示也明講不要動。"""
    wiki, raw = tmp_path / "WIKI", tmp_path / "Raw_Sources"
    (wiki / "Wiki_Pages").mkdir(parents=True)
    (wiki / "Wiki_Pages" / "index.md").write_text("# 我原本的索引\n", encoding="utf-8")
    seen = []
    ok, said = ws.scaffold_wiki(Path("/x/claude"), wiki, raw, False,
                                run=_fake_claude({"CLAUDE.md": "# 規則\n", "Wiki_Pages/index.md": "# 被蓋掉\n"}, seen))
    assert ok and "還原" in said
    assert (wiki / "Wiki_Pages" / "index.md").read_text(encoding="utf-8") == "# 我原本的索引\n"
    assert (wiki / "CLAUDE.md").is_file()
    assert "已經有的檔一個都不要改" in seen[0][1]


def test_scaffold_that_builds_nothing_is_reported(tmp_path):
    ok, said = ws.scaffold_wiki(Path("/x/claude"), tmp_path / "WIKI", tmp_path / "Raw_Sources", False,
                                run=_fake_claude({}, []))
    assert not ok and "CLAUDE.md" in said


def test_git_section_is_appended_once_and_keeps_the_existing_rules(tmp_path):
    """已經有 CLAUDE.md 就用原本的:只在最後補上代管 git 的一節(朋友在桌面版自己 commit,攝入就會 STOP)。"""
    (tmp_path / "CLAUDE.md").write_text("# 原本的規則\n\n照我的分類。", encoding="utf-8")
    assert ws.add_git_section(tmp_path)
    assert not ws.add_git_section(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 原本的規則\n\n照我的分類。\n") and text.count(ws.GIT_HEADING) == 1
    assert "不要自己執行 git" in text and "攝入:<原件檔名>——一句摘要" in text


def test_ask_wiki_builds_missing_folders_and_never_rebuilds_an_existing_claude_md(tmp_path, monkeypatch):
    """全部直接按 Enter:預設的資料夾不存在就建、照講義建 CLAUDE.md、補 git 那一節。已經有 CLAUDE.md 的不再叫 claude。"""
    monkeypatch.setattr("builtins.input", lambda *_: "")
    calls = []
    monkeypatch.setattr(ws, "scaffold_wiki", lambda claude, w, r, windows: (
        calls.append(w), (w / "CLAUDE.md").write_text("# 新規則\n", encoding="utf-8"), (True, "ok"))[-1])
    wiki = tmp_path / "SOURCE5" / "WIKI"
    w, r = ws.ask_wiki(str(wiki), Path("/x/claude"), False)
    assert (w, r) == (str(wiki), str(tmp_path / "SOURCE5" / "Raw_Sources"))
    assert (Path(r) / "_Pending").is_dir() and calls == [wiki]
    assert ws.GIT_HEADING in (wiki / "CLAUDE.md").read_text(encoding="utf-8")

    (wiki / "CLAUDE.md").write_text("# 原本的\n", encoding="utf-8")
    ws.ask_wiki(str(wiki), Path("/x/claude"), False)
    assert calls == [wiki]                                                   # 沒有再叫 claude
    assert (wiki / "CLAUDE.md").read_text(encoding="utf-8").startswith("# 原本的\n")


def test_md_cache_is_kept_out_of_the_version_history(tmp_path):
    """講義的 .md_cache/ 在 WIKI 裡:不排除的話,程式代管 git 的「手動修改快照」會把轉檔產物整包收進去。"""
    (tmp_path / ".gitignore").write_text("*.tmp", encoding="utf-8")
    assert ws.ignore_md_cache(tmp_path) and not ws.ignore_md_cache(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n.md_cache/\n"


def test_wikilink_check_looks_at_pages_not_the_rule_that_forbids_it(tmp_path):
    """CLAUDE.md 寫著「禁止 [[名稱]]」不算;頁面裡出現才提醒。"""
    pages = {"CLAUDE.md": "禁止 [[名稱]]\n", "Wiki_Pages/index.md": "# 索引\n"}
    ok, said = ws.scaffold_wiki(Path("/x/claude"), tmp_path / "W", tmp_path / "R", False, run=_fake_claude(pages, []))
    assert ok and "[[" not in said
    pages["Wiki_Pages/index.md"] = "見 [[某頁]]\n"
    ok, said = ws.scaffold_wiki(Path("/x/claude"), tmp_path / "W2", tmp_path / "R", False, run=_fake_claude(pages, []))
    assert ok and "[[" in said


# -- 三種語言:知識庫用安裝時選的語言建;代管 git 那一節認得三種寫法的標題 ------------------------------

def test_english_handout_prompt_asks_for_an_english_wiki(tmp_path):
    """資料夾名(_Pending、Wiki_Pages、index.md、.md_cache)是程式寫死的,照原樣。"""
    from wiki_feeder import i18n
    i18n.set_lang("en")
    wiki, raw = tmp_path / "LLMWIKI" / "WIKI", tmp_path / "LLMWIKI" / "Raw_Sources"
    prompt = ws.handout_prompt(wiki, raw, False)
    assert "English" in prompt and "Markdown" in prompt and "繁體中文" not in prompt
    assert "../Raw_Sources/" in prompt and "../Raw_Sources/_Pending/" in prompt and "\\" not in prompt
    for kept in ("Wiki_Pages/", "index.md", ".md_cache/", "CLAUDE.md", "[[", "git"):
        assert kept in prompt
    assert "..\\Raw_Sources\\" in ws.handout_prompt(wiki, raw, True)
    assert not any("一" <= ch <= "鿿" for ch in prompt)
    keep = ws.L(ws.KEEP_EXISTING)                                            # 已經有的檔不要動:也是英文
    assert keep.startswith("\n") and keep.strip() and not any("一" <= ch <= "鿿" for ch in keep)


def test_english_git_section_uses_the_english_commit_format(tmp_path):
    """要等主代理合併 locales/en.json 才會過。"""
    from wiki_feeder import i18n
    i18n.set_lang("en")
    (tmp_path / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
    assert ws.add_git_section(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Ingest: <original file name> — one-line summary" in text and ws.L(ws.GIT_HEADING) in text
    assert not any("一" <= ch <= "鿿" for ch in text) and "`_Pending`" in text


def test_git_section_heading_in_any_language_counts_as_present(tmp_path, monkeypatch):
    """用英文裝過、改用繁中重跑安裝:CLAUDE.md 已經有英文標題,不可再補一節中文的。"""
    from wiki_feeder import i18n
    en_heading = "## Version history (git managed by wiki-feeder)"
    monkeypatch.setitem(i18n._catalogs, "en", {**i18n.catalog("en"), ws.GIT_HEADING: en_heading})
    wiki = tmp_path / "WIKI"
    wiki.mkdir()
    (wiki / "CLAUDE.md").write_text(f"# Rules\n\n{en_heading}\n\nDon't run git.\n", encoding="utf-8")
    assert i18n.get_lang() == "zh-Hant" and not ws.add_git_section(wiki)
    assert ws.GIT_HEADING not in (wiki / "CLAUDE.md").read_text(encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_: "")                     # ask_wiki 也不再問要不要補
    ws.ask_wiki(str(wiki), None, False)
    assert ws.GIT_HEADING not in (wiki / "CLAUDE.md").read_text(encoding="utf-8")


def test_glossary_section_is_appended_once_in_the_install_language(tmp_path):
    """名詞校正表那一節(spec §5.14):朋友開 Claude 桌面版說「這場會議的某某寫錯了」時讀的是 CLAUDE.md,
    沒有這一節就只改頁面、不記進表。補一次就好,換了語言重跑安裝也不再補;照安裝時的語言寫。"""
    from wiki_feeder import glossary, i18n
    (tmp_path / "CLAUDE.md").write_text("# 原本的規則\n\n照我的分類。", encoding="utf-8")
    assert ws.add_glossary_section(tmp_path)
    assert not ws.add_glossary_section(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 原本的規則\n\n照我的分類。\n") and text.count(glossary.RULE_HEADING) == 1
    assert glossary.TABLE_FILE in text and "使用者指出哪場會議哪裡寫錯時" in text
    i18n.set_lang("en")
    assert not ws.add_glossary_section(tmp_path)        # 已經有繁中那一節
    en = tmp_path / "en"
    en.mkdir()
    (en / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
    assert ws.add_glossary_section(en)
    text = (en / "CLAUDE.md").read_text(encoding="utf-8")
    assert i18n.L(glossary.RULE_HEADING) in text and glossary.RULE_HEADING not in text


def test_glossary_section_is_offered_even_when_the_old_config_is_kept(tmp_path, monkeypatch):
    """沿用舊設定檔重跑安裝也會問(安裝說明叫「當時沒補的話重跑一次安裝」);已經有就不問。"""
    from wiki_feeder import glossary
    (tmp_path / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")
    asked = []
    monkeypatch.setattr("builtins.input", lambda *a: asked.append(a) or "")
    ws.offer_glossary_section(tmp_path)
    ws.offer_glossary_section(tmp_path)
    assert len(asked) == 1 and glossary.has_rule((tmp_path / "CLAUDE.md").read_text(encoding="utf-8"))
    for name in ("winsetup", "macsetup"):
        assert "offer_glossary_section(cfg.repo(cfg.target_repo).repo_dir)" in (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")


# -- 已經有知識庫:照它的 CLAUDE.md(使用者 2026-10-27) ----------------------------------------

def _library(root: Path, rules: str, raw: str = "Raw_Sources", wiki: str = "WIKI") -> tuple[Path, Path]:
    w, r = root / wiki, root / raw
    (w / "Wiki_Pages").mkdir(parents=True)
    r.mkdir(parents=True, exist_ok=True)
    (w / "CLAUDE.md").write_text(rules, encoding="utf-8")
    return w, r


def _answers(monkeypatch, *answers: str) -> list:
    """依序回答;問完了還在問就是多問了(測試失敗)。"""
    it, asked = iter(answers), []
    monkeypatch.setattr("builtins.input", lambda *a: (asked.append(a[0] if a else ""), next(it))[1])
    return asked


def _no_claude(*a, **k):
    raise AssertionError("程式看得出來就不該叫 claude")


def test_handout_claude_md_is_read_by_the_program(tmp_path):
    """講義建的 CLAUDE.md:原件在 ../Raw_Sources/,入口寫 _待處理/——照它(三個都用舊名),不看磁碟猜英文。"""
    w, r = _library(tmp_path, "# 規則\n原始資料在 ../Raw_Sources/(我放、你只讀不改),底下的 _待處理/ 是統一入口。\n"
                              "頁面放 Wiki_Pages/,來源寫 Raw_Sources/會議/x.pdf\n")
    assert ws.raw_candidates(w, (w / "CLAUDE.md").read_text(encoding="utf-8")) == [r.resolve()]
    names, md = ws.claude_md_folders(r, w, (w / "CLAUDE.md").read_text(encoding="utf-8"))
    assert names[ws.PENDING] == "_待處理" and names[ws.DISCARD] == "_捨棄候選" and md == "_待處理"


def test_raw_inside_the_wiki_absolute_paths_and_glued_cjk_are_understood(tmp_path):
    w, r = _library(tmp_path, "", raw="Wiki/raw", wiki="Wiki")
    (w / "Wiki_Pages" / "sources").mkdir()                   # 頁面底下的群組,名字像原件也不算
    text = "Sources live in `raw/` and new files go to `raw/_Pending/`. Pages: `Wiki_Pages/sources/`.\n"
    assert ws.raw_candidates(w, text) == [r.resolve()]
    assert ws.claude_md_folders(r, w, text)[0][ws.PENDING] == "_Pending"
    assert ws.raw_candidates(w, f"原件放在{r}/裡面") == [r.resolve()]       # 中文緊貼在絕對路徑前後
    assert ws.raw_candidates(w, "原始資料在../raw/裡") == []                # 寫了但不存在的不算
    assert ws.raw_candidates(w, "原始資料在 raw/會議/裡") == [r.resolve()]   # 往上找到存在的那層


def test_inbox_named_in_claude_md_is_used_even_without_underscore(tmp_path):
    """已經有知識庫的,入口不限定系統名(使用者 2026-10-27:「目錄本來就不應該限定」);捨棄、收件區照系統名。
    寫的入口跟收件區只差大小寫(磁碟上是同一個):收件區換成另一套名字。"""
    w, r = _library(tmp_path, "")
    (r / "inbox").mkdir()
    names, md = ws.claude_md_folders(r, w, "新檔先放 ../Raw_Sources/inbox/ 再分類")
    assert md == "inbox" and names == {ws.PENDING: "inbox", ws.DISCARD: "_Discarded", ws.INTAKE: "_Inbox"}
    (r / "_inbox").mkdir()
    names, md = ws.claude_md_folders(r, w, "新檔先放 ../Raw_Sources/_inbox/")
    assert names == {ws.PENDING: "_inbox", ws.DISCARD: "_Discarded", ws.INTAKE: "_收件區"}
    cfg = ws.write_config(ws.render_config({"icloud": str(tmp_path / "i"), "wiki": str(w), "raw": str(r),
                                            "doc2md": "/x/doc2md", "folders": names}), tmp_path / "state")
    assert cfg.pending_name == "_inbox" and cfg.pending_dir == r / "_收件區"


def test_existing_wiki_takes_everything_from_claude_md_with_one_confirmation(tmp_path, monkeypatch):
    w, r = _library(tmp_path, "原始資料在 ../Raw_Sources/,入口 ../Raw_Sources/_待處理/\n")
    monkeypatch.setattr(ws, "claude_find_raw", _no_claude)
    asked = _answers(monkeypatch, "", "", "", "")            # 有知識庫、CLAUDE.md 用預設、對、補 git 那一節
    got = ws.ask_library(str(tmp_path / "new"), w, Path("/x/claude"), False)
    assert got == (str(w.resolve()), str(r.resolve()), {k: v for k, v in ws.LEGACY.items()})
    assert (r / "_待處理").is_dir() and not (r / "_Pending").exists()
    assert len(asked) == 4 and ws.GIT_HEADING in (w / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (tmp_path / "new").exists()


def test_a_different_answer_is_asked_again_and_claude_md_wins_by_default(tmp_path, monkeypatch):
    w, r = _library(tmp_path, "原始資料在 ../Raw_Sources/\n")
    mine = tmp_path / "Mine"
    mine.mkdir()
    monkeypatch.setattr(ws, "claude_find_raw", _no_claude)
    # 不對 → 選別的 → 改用 CLAUDE.md 的?Enter → 入口照預設 → 不補 git 一節
    _answers(monkeypatch, "", "", "n", str(mine), "", "", "n")
    assert ws.ask_library("", w, None, False)[1] == str(r.resolve())
    _answers(monkeypatch, "", "", "n", str(mine), "n", "", "n")    # 堅持用自己的
    assert ws.ask_library("", w, None, False)[1] == str(mine.resolve())
    asked = _answers(monkeypatch, "", "", "n", str(r), "", "n")    # 改來改去還是選回 CLAUDE.md 的:不必再確認
    assert ws.ask_library("", w, None, False)[1] == str(r.resolve()) and len(asked) == 6


def test_a_different_inbox_is_asked_again_and_claude_md_wins_by_default(tmp_path, monkeypatch):
    w, r = _library(tmp_path, "原始資料在 ../Raw_Sources/,新檔放 ../Raw_Sources/inbox/\n")
    monkeypatch.setattr(ws, "claude_find_raw", _no_claude)
    # 不對 → 原件資料夾照舊 → 入口打 new → 改用 CLAUDE.md 的 inbox?Enter → 不補 git
    _answers(monkeypatch, "", "", "n", "", "new", "", "n")
    assert ws.ask_library("", w, None, False)[2][ws.PENDING] == "inbox"
    assert (r / "inbox").is_dir() and not (r / "new").exists()
    _answers(monkeypatch, "", "", "n", "", "../x", "new", "n", "n")   # 打錯再問;堅持用 new
    assert ws.ask_library("", w, None, False)[2][ws.PENDING] == "new" and (r / "new").is_dir()


def test_claude_reads_claude_md_only_when_the_program_cannot(tmp_path, monkeypatch):
    w, r = _library(tmp_path, "原始資料請看 README", raw="Docs/Inputs")
    seen = []

    def fake(args, cwd, input, **k):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": f'好的 {{"raw": "../Docs/Inputs"}}'}), "")
    assert ws.claude_find_raw(Path("/x/claude"), w, run=fake) == r.resolve()
    (args,) = seen
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep" and "--permission-mode" not in args
    gone = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps({"result": '{"raw": "../Nope"}'}), "")
    assert ws.claude_find_raw(Path("/x/claude"), w, run=gone) is None         # 不存在的不收
    junk = lambda *a, **k: subprocess.CompletedProcess(a, 1, "壞掉", "")
    assert ws.claude_find_raw(Path("/x/claude"), w, run=junk) is None

    monkeypatch.setattr(ws, "claude_find_raw", lambda claude, wiki: r.resolve())
    _answers(monkeypatch, "", "", "", "")
    assert ws.ask_library("", w, Path("/x/claude"), False)[1] == str(r.resolve())


def test_no_wiki_yet_goes_to_the_new_wiki_questions(tmp_path, monkeypatch):
    """找不到現成的知識庫:第一題預設「沒有」,直接走新建(照講義請 claude 建)。"""
    monkeypatch.setattr(ws, "scaffold_wiki", lambda claude, w, r, windows: (
        (w / "CLAUDE.md").write_text("# 新規則\n", encoding="utf-8"), (True, "ok"))[-1])
    monkeypatch.setattr("builtins.input", lambda *_: "")
    w, r, names = ws.ask_library(str(tmp_path / "SOURCE5" / "WIKI"), None, Path("/x/claude"), False)
    assert (w, names) == (str(tmp_path / "SOURCE5" / "WIKI"), None) and (Path(r) / "_Pending").is_dir()


def test_two_possible_originals_folders_are_left_to_claude(tmp_path, monkeypatch):
    """CLAUDE.md 提到兩個都存在的原件資料夾:程式不猜,請 claude 讀;claude 也說不出來就請他自己選。"""
    w, r = _library(tmp_path, "原始資料在 ../Raw_Sources/,舊的在 ../Old_Sources/\n")
    (tmp_path / "Old_Sources").mkdir()
    asked_claude = []
    monkeypatch.setattr(ws, "claude_find_raw", lambda claude, wiki: asked_claude.append(wiki))
    _answers(monkeypatch, "", "", str(r), "", "")             # 有知識庫、CLAUDE.md 預設、自己選原件資料夾、對、補 git
    assert ws.ask_library("", w, Path("/x/claude"), False)[1] == str(r.resolve()) and asked_claude
