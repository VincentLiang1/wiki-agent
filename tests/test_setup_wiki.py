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
