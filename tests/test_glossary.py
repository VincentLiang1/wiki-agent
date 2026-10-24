"""名詞對照表(glossary.py,spec §5.14):知識庫的名詞校正 → 手機用的 name-corrections.json。

全部在 tmp_path:假的庫、假的聲紋同步資料夾,絕不碰真的 iCloud 雲碟。
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from conftest import git
from test_single_repo import _feed, single  # noqa: F401 —— 朋友版的 fixture

from wiki_feeder import glossary
from wiki_feeder.config import GLOSSARY_SYNC_DIR, Config, RepoConfig
from wiki_feeder.ingest import IngestReport, _prompt, ingest, post_summary

TABLE = """# 名詞校正

| 聽錯的寫法 | 正確寫法 | 分組 |
| --- | --- | --- |
| 王曉名、王小明 | 王筱明 | |
| 林大 | 林達 | |
| 林大 | 林達 | 業務週會 |
| Jon Smyth, John Smith | Jon Smith | |
| 張三丰 | 張珊? | |
"""


def _entries(doc: dict, group: str | None = None) -> dict[str, list[str]]:
    es = doc["common"] if group is None else doc["groups"][group]
    return {e["right"]: e["wrong"] for e in es}


def test_table_skips_header_and_unsure_rows_and_two_char_common():
    """朋友的表格:表頭(下一行是分隔列)與分隔列不算;正確寫法帶問號的不收;兩個字的中文只在分組裡收。"""
    skipped: list[str] = []
    common, groups = glossary.parse_table(TABLE, skipped)
    doc = {"common": glossary.to_entries(common), "groups": {k: glossary.to_entries(v) for k, v in groups.items()}}
    assert _entries(doc) == {"王筱明": ["王小明", "王曉名"], "Jon Smith": ["John Smith", "Jon Smyth"]}
    assert _entries(doc, "業務週會") == {"林達": ["林大"]}
    assert "聽錯的寫法" not in json.dumps(doc, ensure_ascii=False)
    assert any("張珊?" in s for s in skipped) and any("林大" in s for s in skipped)


def test_table_header_in_any_language():
    """表頭寫英文也一樣(只看欄位位置)。"""
    text = "| Misheard | Correct | Group |\n|:--|:--:|--:|\n| Acme Corp | Akme Corp | |\n"
    common, groups = glossary.parse_table(text, [])
    assert common == {"Akme Corp": {"Acme Corp"}} and groups == {}


def _fwiki(tmp_path: Path) -> Path:
    repo = tmp_path / "公事庫"
    (repo / "memory").mkdir(parents=True)
    (repo / glossary.FWIKI_MEMORY).write_text(
        "# 語音辨識誤譯\n\n"
        "- 人名:「王曉名」「王小明」＝**王筱明**;「林大」＝**林達**\n"
        "- 業務週會 0824 逐字稿判讀:「林大」＝**林達**;「陳某」＝**陳茂（疑）**\n", encoding="utf-8")
    pages = repo / "Wiki_Pages" / "會議"
    pages.mkdir(parents=True)
    (pages / "研發例會-2026-10-01.md").write_text(
        "# 研發例會\n\n## 名詞與人名校正\n\n| 逐字稿音 | 判讀 | 依據 |\n| --- | --- | --- |\n| 黃小 | **黃筱** | 名單 |\n\n"
        "## 其他\n\n「亂寫」＝**不該收**\n", encoding="utf-8")
    (pages / "面談-2026-10-02.md").write_text(
        "# 面談\n\n## 名詞校正\n\n周杰倫／周傑倫＝**周潔倫**;趙一＝**趙依**\n", encoding="utf-8")
    return repo


def test_fwiki_memory_pages_and_rules(tmp_path):
    """公事庫的寫法:memory 檔(通用不收兩字)、`- 系列 MMDD` 開頭的分組、整理頁「名詞與人名校正」一節;
    分組規則 merge／toCommon,沒列到的新分組回報出來。"""
    repo = _fwiki(tmp_path)
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"merge": {"例會": ["研發例會"]}, "toCommon": ["面談"]}, ensure_ascii=False),
                     encoding="utf-8")
    doc, skipped, unruled = glossary.build(repo, True, rules)
    assert _entries(doc) == {"王筱明": ["王小明", "王曉名"], "周潔倫": ["周傑倫", "周杰倫"]}
    assert sorted(doc["groups"]) == ["例會", "業務週會"]
    assert _entries(doc, "例會") == {"黃筱": ["黃小"]}
    assert _entries(doc, "業務週會") == {"林達": ["林大"]}
    assert unruled == ["業務週會"]
    assert "不該收" not in json.dumps(doc, ensure_ascii=False)
    assert any("陳茂" in s for s in skipped)   # 帶「疑」的不收


def test_fwiki_before_drops_later_pages(tmp_path):
    """評測用的 --before:那天以後的整理頁不算(會前不可能有的對照)。"""
    doc, _, _ = glossary.build(_fwiki(tmp_path), True, None, before="2026-10-01")
    assert "研發例會" not in doc["groups"]


def test_write_keeps_shape_and_skips_unchanged(tmp_path):
    """手機的 NameCorrections 解得開的形狀;內容沒變不重寫(不吵 iCloud),寫的時候先寫「.」開頭的暫存名。"""
    doc = {"common": [{"wrong": ["王小明"], "right": "王筱明"}], "groups": {}}
    assert glossary.write(tmp_path, doc)
    out = tmp_path / glossary.OUT_NAME
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"common", "groups", "generatedAt"}
    os.utime(out, (1, 1))
    assert not glossary.write(tmp_path, doc)
    assert out.stat().st_mtime == 1
    assert not (tmp_path / ("." + glossary.OUT_NAME)).exists()


def _cfg(tmp_path: Path, out: Path) -> Config:
    repo = tmp_path / "wiki"
    (repo / "memory").mkdir(parents=True)
    (repo / glossary.TABLE_FILE).write_text(TABLE, encoding="utf-8")
    git("init", "-q", cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "x", cwd=repo)
    inbox = tmp_path / "iCloud" / "_WikiBox"
    inbox.mkdir(parents=True)
    return Config(pending_dir=tmp_path / "raw" / "_Inbox", state_dir=tmp_path / "state", icloud_inbox=inbox,
                  onedrive_inbox=None, futures=None, raw_roots=(tmp_path / "raw",),
                  repos=(RepoConfig("main", "庫", repo, tmp_path / "raw", ""),), target_repo="main",
                  glossary_dir=out)


def test_refresh_refuses_output_inside_inbox(tmp_path):
    """輸出資料夾在收件匣裡:不寫、發警示——對照表含真名,寫進去會被收走、攝入。"""
    out = tmp_path / "iCloud" / "_WikiBox" / "sync"
    c = _cfg(tmp_path, out)
    out.mkdir()
    (c.state_dir).mkdir()
    alerts = glossary.refresh(c)
    assert alerts and "重疊" in alerts[0]
    assert not (out / glossary.OUT_NAME).exists()
    assert glossary.unsafe_out(c, c.repos[0].repo_dir / "x") is not None   # 知識庫裡也不行
    assert glossary.unsafe_out(c, tmp_path / "iCloud") is not None        # 包著收件匣也不行
    assert glossary.unsafe_out(c, tmp_path / "iCloud" / GLOSSARY_SYNC_DIR) is None


def test_refresh_only_reparses_when_something_changed(tmp_path, monkeypatch):
    """每輪都叫:庫的 HEAD、校正檔、規則都沒變就不解析;沒有聲紋同步資料夾就什麼都不做。"""
    out = tmp_path / "iCloud" / GLOSSARY_SYNC_DIR
    c = _cfg(tmp_path, out)
    c.state_dir.mkdir()
    assert glossary.refresh(c) == [] and not out.exists()       # 朋友沒做第 7 節
    out.mkdir()
    calls = []
    real = glossary.build
    monkeypatch.setattr(glossary, "build", lambda *a, **k: calls.append(a) or real(*a, **k))
    glossary.refresh(c)
    glossary.refresh(c)
    assert len(calls) == 1
    assert "王筱明" in (out / glossary.OUT_NAME).read_text(encoding="utf-8")
    src = c.repos[0].repo_dir / glossary.TABLE_FILE
    src.write_text(TABLE + "| 李四 | 李肆 | 業務週會 |\n", encoding="utf-8")
    glossary.refresh(c)
    assert len(calls) == 2
    assert "李肆" in (out / glossary.OUT_NAME).read_text(encoding="utf-8")


def test_friend_ingest_commits_table_and_updates_phone_file(single, monkeypatch):  # noqa: F811
    """朋友版:攝入的 claude 照提示寫 memory/name-corrections.md → 程式連同頁面一起 commit(不 STOP)、
    這輪結束就更新聲紋同步資料夾裡的對照表。"""
    c = single["cfg"]
    sync = single["tmp"] / "iCloudDrive" / GLOSSARY_SYNC_DIR
    sync.mkdir()
    assert c.glossary_dir == sync
    monkeypatch.setenv("FAKE_CLAUDE_GLOSSARY", TABLE)
    _feed(single, "會議紀錄.txt", "王曉名說".encode())
    r = ingest(c)
    assert r.ok, r.alerts
    wiki = single["wiki"]
    assert not git("status", "--porcelain", cwd=wiki)
    assert glossary.TABLE_FILE in git("show", "--name-only", "--format=", "HEAD", cwd=wiki)
    assert "王筱明" in (sync / glossary.OUT_NAME).read_text(encoding="utf-8")


def test_stop_keeps_unverified_table_off_the_phone(single):  # noqa: F811
    """STOP 中不更新:沒驗證過的內容不送到手機。"""
    c = single["cfg"]
    sync = single["tmp"] / "iCloudDrive" / GLOSSARY_SYNC_DIR
    sync.mkdir()
    (single["wiki"] / "memory").mkdir()
    (single["wiki"] / glossary.TABLE_FILE).write_text(TABLE, encoding="utf-8")
    c.ingest_stop_path.write_text("STOP", encoding="utf-8")
    ingest(c)
    assert not (sync / glossary.OUT_NAME).exists()


def test_prompt_rule_only_for_managed_repos(tmp_path):
    """名詞校正表的那條規則只給程式代管的庫(朋友);使用者本人的公事庫照它自己的規則,提示一字不差。"""
    raw = tmp_path / "raw"
    (raw / "_待處理").mkdir(parents=True)
    f = raw / "_待處理" / "a.txt"
    f.write_text("x", encoding="utf-8")
    args = ({"轉寫": {"類型": "文字"}}, "", ["會議"], ("py", "-m", "wiki_feeder"), None)
    own = _prompt(RepoConfig("company", "公事庫", tmp_path / "w", raw, ""), f, *args)
    friend = _prompt(RepoConfig("main", "庫", tmp_path / "w", raw, "", managed=True), f, *args)
    assert glossary.TABLE_FILE not in own
    assert glossary.TABLE_FILE in friend and "兩個字的中文詞只有填了分組才會套用" in friend


def test_new_groups_go_into_the_summary_once(tmp_path):
    """分組規則沒列到的新分組:附在摘要信、同一組只提一次、不算警示(主旨不加「需要處理」)。"""
    c = replace(_cfg(tmp_path, tmp_path / "out"), glossary_rules=tmp_path / "rules.json")
    c.state_dir.mkdir()
    c.glossary_state_path.write_text(json.dumps({"unruled": ["業務週會"]}, ensure_ascii=False), encoding="utf-8")
    post_summary(c, IngestReport())
    post_summary(c, IngestReport())
    text = next(c.summaries_dir.iterdir()).read_text(encoding="utf-8")
    assert text.count("業務週會") == 1
    assert glossary.new_groups(c) == []
    # 沒設分組規則(朋友版)不提
    c2 = replace(c, glossary_rules=None)
    c2.glossary_state_path.write_text(json.dumps({"unruled": ["X"]}), encoding="utf-8")
    assert glossary.new_groups(c2) == []


def test_friend_config_derives_sync_folder(tmp_path):
    """朋友的設定檔:收件匣在 iCloud 雲碟就用同一層的 _聲紋同步(安裝說明第 7 節);只有 OneDrive 就沒有。"""
    state = tmp_path / "s"
    state.mkdir()
    p = state / "config.toml"
    p.write_text(f"[inbox]\nicloud = '{tmp_path / 'D' / '_WikiBox'}'\n[wiki]\ndir = '{tmp_path}/w'\nraw = '{tmp_path}/r'\n"
                 "[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    assert Config.from_file(p, state).glossary_dir == tmp_path / "D" / GLOSSARY_SYNC_DIR
    p.write_text(f"[inbox]\nonedrive = '{tmp_path / 'O'}'\n[wiki]\ndir = '{tmp_path}/w'\nraw = '{tmp_path}/r'\n"
                 "[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    assert Config.from_file(p, state).glossary_dir is None
