"""單庫、程式代管 git(朋友的 Windows 版):庫照桌面版講義建、本來不是 git 庫。

設定照 config.toml 讀(Config.from_file),假 claude、假 doc2md;全部在 tmp_path,絕不碰真的庫。
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder.collect import collect
from wiki_feeder.config import CONFIG_FILE, Config
from wiki_feeder.convert import convert
from wiki_feeder.ingest import SNAPSHOT_MESSAGE, STOP_LEFTOVER, ingest

HERE = Path(__file__).parent


@pytest.fixture
def single(tmp_path, monkeypatch):
    root = tmp_path / "LLMWIKI"
    wiki, raw = root / "WIKI", root / "Raw_Sources"
    (wiki / "Wiki_Pages").mkdir(parents=True)
    (wiki / "CLAUDE.md").write_text("# 規則\n", encoding="utf-8")
    (wiki / "Wiki_Pages" / "index.md").write_text("# 索引\n\n- [舊頁](會議與月報/舊頁.md)\n", encoding="utf-8")
    (raw / "會議與月報").mkdir(parents=True)
    (raw / "_待處理").mkdir()
    (raw / "會議與月報" / "舊月報.pdf").write_bytes(b"old")
    icloud = tmp_path / "iCloudDrive" / "_WikiBox"
    icloud.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    (state / CONFIG_FILE).write_text(
        f"[inbox]\nicloud = '{icloud}'\n[scribe2md]\nsync_dir = '{icloud.parent / '_ScribeSync'}'\n"
        f"[wiki]\ndir = '{wiki}'\nraw = '{raw}'\n"
        f"[mail]\nfrom = ''\nto = ''\n[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    for k, v in {"FAKE_CLAUDE_ARGS": tmp_path / "claude.jsonl", "FAKE_DOC2MD_ARGS": tmp_path / "doc2md.jsonl"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    c = replace(Config.from_file(state / CONFIG_FILE, state), stable_wait=0, trigger_icloud_download=False,
                claude_cmd=(sys.executable, str(HERE / "fake_claude.py")),
                doc2md_cmd=(sys.executable, str(HERE / "fake_doc2md.py")),
                ingest_tools_cmd=("/x/python", "-P", "-m", "wiki_feeder"))
    return {"cfg": c, "wiki": wiki, "raw": raw, "tmp": tmp_path}


def _feed(s, name: str, data: bytes) -> None:
    c = s["cfg"]
    (c.icloud_inbox / name).write_bytes(data)
    assert collect(c).ok
    assert convert(c).ok


def _log(repo: Path) -> list[str]:
    return git("log", "--format=%s", cwd=repo).splitlines()


def _claude_calls(s) -> list[tuple[list[str], str]]:
    p = s["tmp"] / "claude.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_first_ingest_sets_up_git_and_the_program_commits(single):
    """不是 git 庫的 WIKI:程式自己 git init、遠端是本機 bare repo;claude 不 commit,程式驗證後代為 commit 並推上去。"""
    c = single["cfg"]
    _feed(single, "會議紀錄.txt", "今天討論".encode())

    r = ingest(c)

    assert r.ok, r.alerts
    (o,) = r.outcomes
    assert o.status == "done"
    wiki = single["wiki"]
    assert _log(wiki) == ["攝入:會議紀錄.txt——測試頁", "wiki-feeder 開始代管前的內容"]
    assert not git("status", "--porcelain", cwd=wiki)
    assert _log(c.local_origin)[0] == "攝入:會議紀錄.txt——測試頁"            # 推到本機的遠端了
    assert (single["raw"] / "會議與月報" / "會議紀錄.txt").exists()
    assert not any((single["raw"] / "_收件區").iterdir())
    # 權限:代管的庫拿不到 git add／commit;沒有個人庫副本;摘要沒有 GitHub 連結
    (args,) = _claude_calls(single)
    allowed = args[args.index("--allowedTools"):args.index("--disallowedTools")]
    assert "Bash(git commit:*)" not in allowed and "Bash(git commit:*)" in args[args.index("--disallowedTools"):]
    assert "--add-dir" not in args
    summary = "".join(p.read_text(encoding="utf-8") for p in c.summaries_dir.glob("*.md"))
    assert "github.com" not in summary
    assert "個人庫" not in summary and "要 revert 或改成什麼" in summary   # 沒有個人庫可搬


def test_brand_new_library_gets_its_first_group(single, monkeypatch):
    """照講義新建的庫,原件樹一個群組都還沒有:回報格式不可帶空的群組清單(真的 claude 會拒絕),
    claude 取的新群組名程式檢查過才建資料夾(2026-10-20 Mac 朋友版實測)。"""
    import shutil

    shutil.rmtree(single["raw"] / "會議與月報")
    monkeypatch.setenv("FAKE_CLAUDE_GROUP", "知識管理")
    _feed(single, "a.txt", b"aaa")

    (o,) = ingest(single["cfg"]).outcomes

    assert o.status == "done", o.error
    assert (single["raw"] / "知識管理" / "a.txt").is_file() and any("新群組" in n for n in o.notes)


@pytest.mark.parametrize("group", ["_待處理", "../外面", "a/b", ".git", "x:y"])
def test_unsafe_new_group_names_are_not_created(single, monkeypatch, group):
    monkeypatch.setenv("FAKE_CLAUDE_GROUP", group)
    _feed(single, "a.txt", b"aaa")
    (o,) = ingest(single["cfg"]).outcomes
    assert (single["raw"] / "_待處理" / "a.txt").is_file() and any("待人搬" in n for n in o.notes)
    assert sorted(p.name for p in single["raw"].iterdir()) == ["_待處理", "_收件區", "會議與月報"]


def test_pages_get_only_the_general_checks(single, monkeypatch):
    """公事庫的 grep 健檢(H2 禁用字元、跨群組顯示文字、type label)不是朋友的庫的規則:只查通用的。"""
    from wiki_feeder.cli import main

    page = single["wiki"] / "Wiki_Pages" / "頁.md"
    page.write_text("## 第一章：概論\n- [名稱](../別組/某頁.md) — 延伸\n見 [[某頁]]\n", encoding="utf-8")
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["check-pages", "Wiki_Pages/頁.md"], single["cfg"])
    out = buf.getvalue()
    assert "wikilink" in out and "H2" not in out and "跨群組" not in out and "type label" not in out


def test_prompt_has_no_personal_wiki_company_words_or_handouts(single, monkeypatch):
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(single, "a.txt", b"aaa")
    ingest(single["cfg"])

    (prompt,) = seen
    for word in ("個人 WIKI", "不得提到", "FRaw_Sources", "make-handout", "wiki_commit_message", "{", "scope", "歸屬"):
        assert word not in prompt, word
    assert "程式驗證後代為 commit" in prompt and "commit_message" in prompt
    # 歸屬判斷只在有個人庫時才有(使用者 2026-10-26):朋友的回報格式一個欄位都不多
    (args,) = [json.loads(x) for x in (single["tmp"] / "claude.jsonl").read_text(encoding="utf-8").splitlines()]
    props = json.loads(args[args.index("--json-schema") + 1])["properties"]
    assert "scope" not in props and "personal_group" not in props


def test_pdf_without_scribe2md_is_ingested_by_reading_the_original(single, monkeypatch):
    """沒裝 scribe2md(§4.8):PDF 不轉,攝入提示叫 claude 直接讀原件、不要去找轉檔工具(不是「轉寫快取已清除」),這筆照常攝入。"""
    c = replace(single["cfg"], doc2md_cmd=())
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    (c.icloud_inbox / "scan.pdf").write_bytes(b"%PDF-1.4 x")
    assert collect(c).ok and convert(c).ok
    r = ingest(c)
    assert r.ok, r.alerts
    (prompt,) = seen
    assert "沒有裝 scribe2md" in prompt and "不要去找或執行任何轉檔工具" in prompt and "轉寫快取已清除" not in prompt


def test_office_file_without_scribe2md_is_read_with_office_dump(single, monkeypatch):
    """沒裝 scribe2md 的 Word 檔:攝入提示叫 claude 用 office-dump 傾印來讀(不是直接讀二進位檔),這筆照常攝入。"""
    c = replace(single["cfg"], doc2md_cmd=())
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    (c.icloud_inbox / "memo.docx").write_bytes(b"PK")
    assert collect(c).ok and convert(c).ok
    r = ingest(c)
    assert r.ok, r.alerts
    (prompt,) = seen
    assert "沒有裝 scribe2md" in prompt and "office-dump" in prompt and "memo.docx" in prompt
    assert "doc2md 的轉寫會繁化人名" not in prompt


def test_manual_edits_are_snapshotted_before_the_next_ingest(single):
    """朋友用桌面版手動改了頁:攝入前另存一筆快照,不混進攝入的 commit,也不因「庫不乾淨」每輪略過。"""
    c = single["cfg"]
    _feed(single, "a.txt", b"aaa")
    assert ingest(c).ok
    page = single["wiki"] / "Wiki_Pages" / "手動.md"
    page.write_text("# 自己寫的\n", encoding="utf-8")
    _feed(single, "b.txt", b"bbb")

    r = ingest(c)

    assert r.ok, r.alerts
    log = _log(single["wiki"])
    assert log[:2] == ["攝入:b.txt——測試頁", SNAPSHOT_MESSAGE]
    shown = git("show", "--name-only", "--format=", "HEAD~1", cwd=single["wiki"]).split()
    assert shown == ["Wiki_Pages/手動.md"]
    assert _log(c.local_origin)[:2] == log[:2]
    assert not c.ingest_stop_path.exists()


def test_changes_outside_wiki_pages_are_not_committed_and_stop(single, monkeypatch):
    """claude 在 Wiki_Pages/ 以外留了檔(暫存檔、檢查腳本):程式只 commit Wiki_Pages/ 的,那個檔留著、STOP、不推送——
    與 Mac 上「commit 了又留暫存檔」同一種,quarantine → finish-stopped → resume 照用。"""
    c = single["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_DIRTY", "1")
    _feed(single, "a.txt", b"aaa")

    r = ingest(c)

    assert c.ingest_stop_path.exists() and r.outcomes[0].status == "failed"
    assert json.loads(c.ingest_stop_path.read_text(encoding="utf-8"))["種類"] == STOP_LEFTOVER
    wiki = single["wiki"]
    assert "暫存.txt" in git("status", "--porcelain", cwd=wiki)
    assert "暫存.txt" not in git("log", "--name-only", "--format=", cwd=wiki)
    assert _log(c.local_origin) == ["wiki-feeder 開始代管前的內容"]          # 沒推上去


def test_resume_refuses_while_managed_repo_has_leftovers(single, monkeypatch):
    """STOP 之後直接 resume:下一輪的「手動修改快照」會把攝入留下的暫存檔記成驗證過、收進庫裡。要先 quarantine。"""
    from wiki_feeder.ingest import resume

    c = single["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_DIRTY", "1")
    _feed(single, "a.txt", b"aaa")
    ingest(c)
    monkeypatch.delenv("FAKE_CLAUDE_DIRTY")

    msg = resume(c)

    assert "還不能解除" in msg and "quarantine" in msg and c.ingest_stop_path.exists()
    _feed(single, "b.txt", b"bbb")
    ingest(c)
    assert "暫存.txt" not in git("log", "--name-only", "--format=", cwd=single["wiki"])


def test_claude_ending_in_error_is_not_committed_for_it(single, monkeypatch):
    """花完預算、API 錯誤、沒交回報:頁面可能寫到一半。程式不代為 commit(否則寫到一半的頁記成完成、推上去),
    照「留有沒 commit 的修改」STOP。"""
    c = single["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_NOREPORT", "1")
    _feed(single, "a.txt", b"aaa")

    ingest(c)

    assert c.ingest_stop_path.exists()
    assert _log(single["wiki"]) == ["wiki-feeder 開始代管前的內容"]


def test_tools_command_on_windows_uses_console_python_in_utf8_mode():
    """Windows 排程跑 pythonw.exe:照抄給 claude 的話它讀不到輸出,也沒有 UTF-8 模式(CLI 會拒絕執行)。"""
    from wiki_feeder.config import tools_cmd

    assert tools_cmd(r"C:\wf\.venv\Scripts\pythonw.exe", True) == (
        r"C:\wf\.venv\Scripts\python.exe", "-P", "-X", "utf8", "-m", "wiki_feeder")
    assert tools_cmd(r"C:\wf\.venv\Scripts\python.exe", True)[0].endswith("python.exe")
    assert tools_cmd("/app/.venv/bin/python", False) == ("/app/.venv/bin/python", "-P", "-m", "wiki_feeder")


def test_managed_repo_that_commits_by_itself_stops(single, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SELF_COMMIT", "1")
    _feed(single, "a.txt", b"aaa")

    r = ingest(single["cfg"])

    assert single["cfg"].ingest_stop_path.exists() and "自己 commit" in r.outcomes[0].error
    assert _log(single["cfg"].local_origin) == ["wiki-feeder 開始代管前的內容"]   # 沒推上去


def test_lost_git_with_existing_origin_waits_for_a_person(single):
    """庫的 .git 不見了、代管的遠端還在:不另起一段接不上的歷史,整輪不攝入、說明怎麼接回。"""
    import os
    import shutil
    import stat

    c = single["cfg"]
    _feed(single, "a.txt", b"aaa")
    assert ingest(c).ok
    # Windows 上 git 的 object 檔是唯讀的,rmtree 要先拿掉唯讀才刪得掉
    shutil.rmtree(single["wiki"] / ".git", onexc=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))
    _feed(single, "b.txt", b"bbb")

    r = ingest(c)

    assert not r.outcomes and any("git clone" in a for a in r.alerts)
    assert not (single["wiki"] / ".git").exists()


# -- 知識庫在雲端同步資料夾裡:git 的資料放執行狀態目錄(使用者 2026-10-27,spec §5.15) --------------------------

@pytest.fixture
def outside(single):
    c = single["cfg"]
    rc = replace(c.repos[0], git_outside=True)
    single["cfg"] = replace(c, repos=(rc,))
    return single


def test_synced_wiki_keeps_git_data_outside_and_ingests_as_usual(outside):
    """庫裡只有 .git 指標檔、git 的資料在 outside_git_dir;攝入、代為 commit、推送照舊。"""
    c, wiki = outside["cfg"], outside["wiki"]
    _feed(outside, "會議紀錄.txt", "今天討論".encode())

    r = ingest(c)

    assert r.ok, r.alerts
    assert (wiki / ".git").is_file() and (c.outside_git_dir / "HEAD").is_file()
    assert (wiki / ".git").read_text(encoding="utf-8").startswith("gitdir:")
    assert _log(wiki) == ["攝入:會議紀錄.txt——測試頁", "wiki-feeder 開始代管前的內容"]
    assert _log(c.local_origin)[0] == "攝入:會議紀錄.txt——測試頁"


def test_existing_git_folder_in_a_synced_wiki_is_moved_out_with_its_history(outside):
    c, wiki = outside["cfg"], outside["wiki"]
    git("init", "-q", "-b", "master", cwd=wiki)
    git("add", "-A", cwd=wiki)
    git("-c", "user.name=a", "-c", "user.email=friend", "commit", "-q", "-m", "朋友自己的歷史", cwd=wiki)
    _feed(outside, "a.txt", b"aaa")

    ingest(c)

    assert (wiki / ".git").is_file() and (c.outside_git_dir / "HEAD").is_file()
    assert "朋友自己的歷史" in _log(wiki)


def test_pointer_deleted_by_the_sync_app_is_put_back(outside):
    c, wiki = outside["cfg"], outside["wiki"]
    _feed(outside, "a.txt", b"aaa")
    assert ingest(c).ok
    (wiki / ".git").unlink()
    _feed(outside, "b.txt", b"bbb")

    r = ingest(c)

    assert r.ok, r.alerts
    assert (wiki / ".git").is_file() and _log(wiki)[0].startswith("攝入:b.txt")


def test_pointer_to_another_repo_stops_the_round_without_counting_as_failure(outside, tmp_path):
    """別台電腦的指標檔同步過來(指到別的地方):整輪不攝入、說明怎麼處理,不另起一段歷史。"""
    c, wiki = outside["cfg"], outside["wiki"]
    _feed(outside, "a.txt", b"aaa")
    assert ingest(c).ok
    (wiki / ".git").unlink()     # 先刪再寫:Windows 上 .git 是隱藏檔,不准用 "w" 覆寫
    (wiki / ".git").write_text(f"gitdir: {tmp_path / 'other.git'}\n", encoding="utf-8")
    _feed(outside, "b.txt", b"bbb")

    r = ingest(c)

    assert not r.outcomes and any(".git" in a and "改名" in a for a in r.alerts)
    assert not c.ingest_stop_path.exists()


def test_ingest_that_repoints_the_git_pointer_stops(outside, monkeypatch, tmp_path):
    """攝入的 claude 用 Write 把 .git 改指別的庫:之後的 git 全看那個庫,驗證不算數 → STOP、不代為 commit。"""
    c, wiki = outside["cfg"], outside["wiki"]
    other = tmp_path / "other"
    git("init", "-q", str(other), cwd=tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_POINT_GIT", str(other / ".git"))
    _feed(outside, "a.txt", b"aaa")

    r = ingest(c)

    assert c.ingest_stop_path.exists() and ".git 指標檔" in r.outcomes[0].error
    assert _log(c.local_origin) == ["wiki-feeder 開始代管前的內容"]
