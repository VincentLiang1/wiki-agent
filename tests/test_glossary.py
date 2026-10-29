"""名詞對照表(glossary.py,spec §5.14):知識庫的名詞校正 → 手機用的 name-corrections.json。

全部在 tmp_path:假的庫、假的同步資料夾,絕不碰真的 iCloud 雲碟。
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git
from test_single_repo import _feed, single  # noqa: F401 —— 朋友版的 fixture

from wiki_feeder import glossary
from wiki_feeder.config import Config, ConfigError, RepoConfig
from wiki_feeder.ingest import IngestReport, _prompt, ingest, post_summary

SYNC_DIR = "_ScribeSync"   # 安裝程式建議的 scribe2md 同步資料夾名;朋友自己選、寫進設定檔

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
    assert glossary.unsafe_out(c, tmp_path / "iCloud" / SYNC_DIR) is None


def test_refresh_only_reparses_when_something_changed(tmp_path, monkeypatch):
    """每輪都叫:庫的 HEAD、校正檔、規則都沒變就不解析;沒有聲紋同步資料夾就什麼都不做。"""
    out = tmp_path / "iCloud" / SYNC_DIR
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


def _out_file(d: Path) -> Path:
    return d / glossary.OUT_NAME


def test_extra_dirs_get_the_same_bytes(tmp_path):
    """電腦版 meeting-scribe 從 OneDrive 的聲紋同步資料夾讀(2026-10-29):iCloud 那份與 OneDrive 那份都寫、逐位元相同;
    內容沒變兩份都不重寫;寫法同主輸出(不留「.」開頭的暫存檔)。"""
    icloud = tmp_path / "iCloud" / SYNC_DIR
    onedrive = tmp_path / "OneDrive" / SYNC_DIR
    icloud.mkdir(parents=True)
    onedrive.mkdir(parents=True)
    c = replace(_cfg(tmp_path, icloud), glossary_extra_dirs=(onedrive,))
    c.state_dir.mkdir()
    assert glossary.refresh(c) == []
    a, b = _out_file(icloud), _out_file(onedrive)
    assert a.read_bytes() == b.read_bytes()
    assert "王筱明" in b.read_text(encoding="utf-8")
    assert not (onedrive / ("." + glossary.OUT_NAME)).exists()
    os.utime(a, (1, 1))
    os.utime(b, (1, 1))
    assert glossary.refresh(c) == []                      # 戳記沒變:不解析
    (c.state_dir / "glossary.json").write_text("{}", encoding="utf-8")
    assert glossary.refresh(c) == []                      # 解析了但內容沒變:兩份都不重寫
    assert a.stat().st_mtime == 1 and b.stat().st_mtime == 1


def test_missing_extra_dir_is_skipped_quietly(tmp_path):
    """沒裝 OneDrive、沒建 _聲紋同步 是正常狀況:iCloud 那份照寫,沒警示、不建資料夾。"""
    icloud = tmp_path / "iCloud" / SYNC_DIR
    icloud.mkdir(parents=True)
    onedrive = tmp_path / "OneDrive" / SYNC_DIR
    c = replace(_cfg(tmp_path, icloud), glossary_extra_dirs=(onedrive,))
    c.state_dir.mkdir()
    assert glossary.refresh(c) == []
    assert _out_file(icloud).exists() and not onedrive.exists()


def test_extra_dir_inside_inbox_is_refused_but_main_still_written(tmp_path):
    """額外那份在收件匣底下:那一份不寫、回警示;iCloud 那份照寫(一份沒寫成不影響別份)。"""
    icloud = tmp_path / "iCloud" / SYNC_DIR
    bad = tmp_path / "iCloud" / "_WikiBox" / "sync"
    c = replace(_cfg(tmp_path, icloud), glossary_extra_dirs=(bad,))
    icloud.mkdir()
    bad.mkdir()
    c.state_dir.mkdir()
    alerts = glossary.refresh(c)
    assert len(alerts) == 1 and "重疊" in alerts[0] and str(bad) in alerts[0]
    assert _out_file(icloud).exists() and not _out_file(bad).exists()


def test_extra_dir_written_even_when_main_dir_is_missing(tmp_path):
    """主輸出(iCloud 那個資料夾)不存在時,額外那份仍照自己的條件寫。"""
    icloud = tmp_path / "iCloud" / SYNC_DIR          # 不建
    onedrive = tmp_path / "OneDrive" / SYNC_DIR
    onedrive.mkdir(parents=True)
    c = replace(_cfg(tmp_path, icloud), glossary_extra_dirs=(onedrive,))
    c.state_dir.mkdir()
    assert glossary.refresh(c) == []
    assert _out_file(onedrive).exists() and not icloud.exists()


def test_extra_copy_is_restored_after_deletion_and_on_first_rollout(tmp_path):
    """第一次上線時 iCloud 那份已是最新的、戳記也記過了:OneDrive 那份還不存在要觸發一次寫入,而且照抄 iCloud 那份
    (不重寫 iCloud、兩份逐位元相同)。之後 OneDrive 那份被刪掉,下一輪補回來。"""
    icloud = tmp_path / "iCloud" / SYNC_DIR
    icloud.mkdir(parents=True)
    c0 = _cfg(tmp_path, icloud)
    c0.state_dir.mkdir()
    glossary.refresh(c0)                                   # 只有 iCloud 那份的舊版上線過
    a = _out_file(icloud)
    data = json.loads(a.read_text(encoding="utf-8"))
    data["generatedAt"] = "2000-01-01T00:00:00+08:00"      # 舊的產生時間:新產生一份一定不同,只有照抄才會相同
    a.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    before = a.read_bytes()
    os.utime(a, (1, 1))
    onedrive = tmp_path / "OneDrive" / SYNC_DIR
    onedrive.mkdir(parents=True)
    c = replace(c0, glossary_extra_dirs=(onedrive,))
    assert glossary.refresh(c) == []
    b = _out_file(onedrive)
    assert b.read_bytes() == before and a.stat().st_mtime == 1
    b.unlink()
    assert glossary.refresh(c) == []
    assert b.read_bytes() == before


def test_cli_glossary_writes_every_configured_dir(tmp_path, capsys):
    """`wiki-feeder glossary`(沒帶 --out)跟每輪攝入後一樣寫到設定的每一份;--out 只寫那一份。"""
    from wiki_feeder import cli

    icloud = tmp_path / "iCloud" / SYNC_DIR
    onedrive = tmp_path / "OneDrive" / SYNC_DIR
    icloud.mkdir(parents=True)
    onedrive.mkdir(parents=True)
    c = replace(_cfg(tmp_path, icloud), glossary_extra_dirs=(onedrive,))
    c.state_dir.mkdir()
    assert cli.main(["glossary"], cfg=c) == 0
    out = capsys.readouterr().out
    assert str(_out_file(icloud)) in out and str(_out_file(onedrive)) in out
    assert _out_file(icloud).read_bytes() == _out_file(onedrive).read_bytes()
    assert cli.main(["glossary"], cfg=c) == 0
    assert "沒寫" in capsys.readouterr().out
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert cli.main(["glossary", "--out", str(other)], cfg=c) == 0
    assert _out_file(other).exists()


def test_friend_ingest_commits_table_and_updates_phone_file(single, monkeypatch):  # noqa: F811
    """朋友版:攝入的 claude 照提示寫 memory/name-corrections.md → 程式連同頁面一起 commit(不 STOP)、
    這輪結束就更新聲紋同步資料夾裡的對照表。"""
    c = single["cfg"]
    sync = single["tmp"] / "iCloudDrive" / SYNC_DIR
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
    sync = single["tmp"] / "iCloudDrive" / SYNC_DIR
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


def test_friend_config_reads_the_sync_folder_from_its_own_key(tmp_path):
    """朋友的設定檔:scribe2md 同步資料夾是安裝時自己選的 [scribe2md] sync_dir(使用者 2026-10-29:預設目錄不可以是中文、
    讓客戶自己選);沒填就沒有——即使收件匣旁邊有舊名的 _聲紋同步 也不推。"""
    state = tmp_path / "s"
    state.mkdir()
    p = state / "config.toml"
    base = f"[inbox]\nicloud = '{tmp_path / 'D' / '_WikiBox'}'\n[wiki]\ndir = '{tmp_path}/w'\nraw = '{tmp_path}/r'\n[tools]\ndoc2md = 'x'\n"
    p.write_text(base + f"[scribe2md]\nsync_dir = '{tmp_path / 'D' / SYNC_DIR}'\n", encoding="utf-8")
    assert Config.from_file(p, state).glossary_dir == tmp_path / "D" / SYNC_DIR
    (tmp_path / "D" / "_聲紋同步").mkdir(parents=True)
    p.write_text(base, encoding="utf-8")
    assert Config.from_file(p, state).glossary_dir is None
    p.write_text(base + "[scribe2md]\nsync_dir = 3\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.from_file(p, state)
    p.write_text(f"[inbox]\nonedrive = '{tmp_path / 'O'}'\n[wiki]\ndir = '{tmp_path}/w'\nraw = '{tmp_path}/r'\n"
                 "[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    assert Config.from_file(p, state).glossary_dir is None
