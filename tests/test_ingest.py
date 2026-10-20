"""M3 攝入:假 claude、tmp_path 裡的假 FWIKI／WIKI 與假 remote,絕不碰真的庫。"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder.collect import collect
from wiki_feeder.config import RepoConfig
from wiki_feeder.convert import convert
from wiki_feeder.ingest import (FINISHABLE, STOP_GUARDED, STOP_SHRANK, IngestReport, diff_lines, ingest,
                                render_summary)
from wiki_feeder.ledger import Ledger
from wiki_feeder.proc import run_net

HERE = Path(__file__).parent


def _repo(root: Path, name: str) -> RepoConfig:
    remote = root / f"{name}.git"
    work = root / name
    git("init", "--bare", "-q", "-b", "master", str(remote), cwd=root)
    git("init", "-q", "-b", "master", str(work), cwd=root)
    (work / "Wiki_Pages").mkdir()
    (work / "Wiki_Pages" / "index.md").write_text("# index\n", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "init", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    git("push", "-q", "-u", "origin", "master", cwd=work)
    return remote, work


@pytest.fixture
def env(cfg, tmp_path, monkeypatch):
    llm = tmp_path / "SOURCE5"
    llm.mkdir()
    f_remote, fwiki = _repo(llm, "FWIKI")
    w_remote, wiki = _repo(llm, "WIKI")
    fraw, raw = llm / "FRaw_Sources", llm / "Raw_Sources"
    (fraw / "會議與月報").mkdir(parents=True)
    (fraw / "會議與月報" / "舊月報.pdf").write_bytes(b"old-report")
    (fraw / "戰略與治理").mkdir()
    (raw / "健康生活").mkdir(parents=True)
    for k, v in {"FAKE_CLAUDE_ARGS": tmp_path / "claude.jsonl", "FAKE_DOC2MD_ARGS": tmp_path / "doc2md.jsonl"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    c = replace(
        cfg, onedrive_inbox=None, pending_dir=raw / "_待處理", raw_roots=(raw, fraw),
        repos=(RepoConfig("company", "公事庫", fwiki, fraw, "me/FWIKI"),
               RepoConfig("personal", "個人庫", wiki, raw, "me/WIKI")),
        backfill_forbidden=("甲公司", "FWIKI", "FRaw_Sources"),   # 真的字串只在使用者自己的設定(owner_mac.py)
        claude_cmd=(sys.executable, str(HERE / "fake_claude.py")),
        doc2md_cmd=(sys.executable, str(HERE / "fake_doc2md.py")),
        ingest_tools_cmd=("/x/python", "-P", "-m", "wiki_feeder"),
    )
    return {"cfg": c, "fwiki": fwiki, "f_remote": f_remote, "fraw": fraw, "tmp": tmp_path}


def _feed(e, name: str, data: bytes) -> None:
    c = e["cfg"]
    (c.icloud_inbox / name).write_bytes(data)
    assert collect(c).ok
    assert convert(c).ok


def _remote_log(remote: Path) -> list[str]:
    return git("log", "--format=%s", "master", cwd=remote).splitlines()


def _calls(e, name: str) -> list[list[str]]:
    p = e["tmp"] / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _summary(e) -> str:
    """本機留底的當日摘要(summaries/ 底下全部接起來)。"""
    d = e["cfg"].summaries_dir
    return "".join(p.read_text(encoding="utf-8") for p in sorted(d.glob("*.md"))) if d.is_dir() else ""


def test_ingests_into_fwiki_pushes_and_posts_summary(env):
    c = env["cfg"]
    _feed(env, "會議紀錄.txt", "今天討論機房搬遷".encode())

    r = ingest(c)

    assert r.ok, r.alerts
    (o,) = r.outcomes
    assert o.status == "done"
    assert (env["fraw"] / "會議與月報" / "會議紀錄.txt").read_text(encoding="utf-8") == "今天討論機房搬遷"
    assert not any(c.pending_dir.iterdir()) and not any((env["fraw"] / "_待處理").iterdir())
    assert "docs(ingest): 會議紀錄" in _remote_log(env["f_remote"])          # 程式推上去了
    # 攝入用的權限:不准 push、不准繞過權限
    (args,) = _calls(env, "claude.jsonl")
    assert "--dangerously-skip-permissions" not in args
    assert "Bash(git push:*)" in args[args.index("--disallowedTools"):]
    # 當日摘要(本機留底)
    body = _summary(env)
    assert "會議紀錄.txt" in body and "https://github.com/me/FWIKI/commit/" in body and "要不要補查" in body


def test_original_moved_by_program_with_tree_unique_name(env):
    """群組裡已有同名檔:進 _待處理/ 時就改成全樹唯一的名字,搬進群組不覆蓋、頁面來源對得上。"""
    c = env["cfg"]
    _feed(env, "舊月報.pdf", b"new-report")

    r = ingest(c)

    assert r.outcomes[0].status == "done", r.alerts
    g = env["fraw"] / "會議與月報"
    assert (g / "舊月報.pdf").read_bytes() == b"old-report"
    assert (g / "舊月報_2.pdf").read_bytes() == b"new-report"
    assert not r.outcomes[0].notes or "改名" not in "".join(r.outcomes[0].notes)


def test_claude_gets_no_write_access_to_originals(env):
    _feed(env, "j.txt", b"jjj")
    ingest(env["cfg"])
    (args,) = _calls(env, "claude.jsonl")
    added = args[args.index("--add-dir") + 1:args.index("--json-schema")] if "--add-dir" in args else []
    assert str(env["fraw"]) not in added
    assert "Bash(mv:*)" in args[args.index("--disallowedTools"):]


def test_claude_gets_no_git_command_that_can_write_files(env):
    """git diff／log／show 的 `--output=<檔>` 能清空任意檔:不放行,而且明列在禁止清單。"""
    _feed(env, "k.txt", b"kkk")
    ingest(env["cfg"])
    (args,) = _calls(env, "claude.jsonl")
    allowed = args[args.index("--allowedTools"):args.index("--disallowedTools")]
    denied = args[args.index("--disallowedTools"):]
    for sub in ("diff", "log", "show"):
        assert not any(a.startswith(f"Bash(git {sub}") for a in allowed), sub
        assert f"Bash(git {sub}:*)" in denied, sub


def test_office_original_can_be_read_with_only_the_dump_command(env, monkeypatch):
    """Office 原件:提示裡給 office-dump 指令、白名單一個子命令一條(不開放任意 python)。"""
    c = replace(env["cfg"], ingest_tools_cmd=("/x/uv", "run", "--directory", "/x/wf", "wiki-feeder"))
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append((cmd, k.get("input", "")))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(env, "名單.xlsx", b"PK-fake-xlsx")
    ingest(c)

    cmd, prompt = seen[0]
    assert "/x/uv run --directory /x/wf wiki-feeder office-dump" in prompt
    allowed = cmd[cmd.index("--allowedTools"):cmd.index("--disallowedTools")]
    assert "Bash(/x/uv run --directory /x/wf wiki-feeder office-dump:*)" in allowed
    assert not any(a.startswith(("Bash(python", "Bash(uv run:")) for a in allowed)


def test_office_attachments_of_a_mail_get_the_dump_command_too(env, tmp_path):
    """2026-10-15 分機表 .msg:xlsx 附件就在轉寫快取的 .assets/ 裡,提示沒講,claude 回報「無法開原檔核對人名」。"""
    from wiki_feeder.ingest import _prompt
    target = env["cfg"].repo(env["cfg"].target_repo)
    raw = target.raw_root / "_待處理" / "分機表.msg"
    md = tmp_path / "分機表-1234.md"
    md.write_text("轉好的文字", encoding="utf-8")
    (md.with_name(md.stem + ".assets") / "sub").mkdir(parents=True)
    (md.with_name(md.stem + ".assets") / "sub" / "11510 分機表.xlsx").write_bytes(b"PK")
    (md.with_name(md.stem + ".assets") / "image1.png").write_bytes(b"png")
    tools = ("/x/uv", "run", "wiki-feeder")

    prompt = _prompt(target, raw, {"轉寫": {"md": str(md)}}, "", ["群組"], tools, tmp_path)

    xlsx = md.with_name(md.stem + ".assets") / "sub" / "11510 分機表.xlsx"   # Windows 的分隔字元是 \
    assert f"/x/uv run wiki-feeder office-dump '{xlsx}'" in prompt
    assert "image1.png" not in prompt
    assert "office-dump" not in _prompt(target, raw, {"轉寫": {}}, "", ["群組"], tools, tmp_path)


def test_backfill_prompt_names_the_forbidden_words_from_the_config(env, monkeypatch):
    """回填禁字只在使用者自己的設定裡(公開 repo 沒有):提示照設定列給 claude,不寫死在程式裡。"""
    seen = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(env, "a.txt", b"aaa")
    ingest(env["cfg"])

    (prompt,) = seen
    assert "不得提到本庫、甲公司、FWIKI、FRaw_Sources**" in prompt


def test_prompt_says_one_bash_command_at_a_time():
    """串接裡有一段沒放行(git diff)整條就被擋:2026-10-15 兩筆 `git add … && git diff --cached --stat` 被擋。"""
    from wiki_feeder.ingest import _PROMPT
    assert "不要用 `&&`、`;`、`|` 串接" in _PROMPT


def test_no_commit_is_retried_then_alerts(env, monkeypatch):
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nocommit")
    _feed(env, "a.txt", b"aaa")

    for _ in range(c.ingest_max_attempts):
        r = ingest(c)
        assert r.outcomes[0].status == "failed"
    assert any("已停止重試" in a for a in r.alerts)
    assert (env["fraw"] / "_待處理" / "a.txt").exists()   # 原件安全留在 _待處理/
    assert ingest(c).outcomes == []                        # 達上限後不再呼叫



def test_stuck_ingest_is_reminded_every_round_until_reingested(env, monkeypatch):
    """停止重試只在當輪報一次的話,漏看那封信原件就一直卡著:之後每輪都列(去重後一天一封信)。"""
    from wiki_feeder.ingest import reingest

    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nocommit")
    _feed(env, "a.txt", b"aaa")
    for _ in range(c.ingest_max_attempts):
        ingest(c)

    r = ingest(c)
    assert r.outcomes == [] and any("攝入已停止重試" in a and "a.txt" in a for a in r.alerts)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    reingest(c, "a.txt", "補充背景")
    r = ingest(c)
    assert [o.status for o in r.outcomes] == ["done"] and not any("停止重試" in a for a in r.alerts)

def test_overwritten_original_stops_everything(env, monkeypatch):
    """mv 沒加 -n 把既有原件蓋掉:原件樹裡少了一份內容 → 停止、大聲警示、不推送。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "clobber")
    _feed(env, "b.txt", b"bbb")
    _feed(env, "c.txt", b"ccc")

    r = ingest(c)

    assert any("內容消失" in a and "舊月報.pdf" in a for a in r.alerts)   # 說得出是哪一份
    assert len(r.outcomes) == 1                             # 第二筆沒有接著跑
    assert _remote_log(env["f_remote"]) == ["init"]


def test_stop_holds_until_resume(env, monkeypatch):
    """實測踩過(2026-10-05 審查):STOP 只擋一輪——下一輪開頭的補推把沒驗證過的 commit 推上主線,
    同一筆又攝入一次。STOP 要停住等人:之後每輪不補推、不攝入,resume 之後才恢復。"""
    from wiki_feeder.ingest import resume

    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "clobber")
    _feed(env, "b.txt", b"bbb")
    _feed(env, "c.txt", b"ccc")
    ingest(c)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")

    for _ in range(2):
        r = ingest(c)
        assert r.outcomes == [] and any("resume" in a for a in r.alerts)
    assert _remote_log(env["f_remote"]) == ["init"]          # 沒驗證過的 commit 沒被補推
    assert len(_calls(env, "claude.jsonl")) == 1             # 沒有再攝入

    assert "git revert" in resume(c)
    r = ingest(c)
    assert [o.name for o in r.outcomes] == ["c.txt"]         # STOP 那筆不自動重攝入
    assert len(_calls(env, "claude.jsonl")) == 2


def test_file_removed_by_hand_from_intake_is_skipped_not_stop(env):
    """實際踩過:使用者清掉收件區的測試檔,紀錄還在 → 曾被當成「原件消失」整輪停止、後面的檔都沒攝入。"""
    c = env["cfg"]
    _feed(env, "測試檔.txt", b"test")
    (c.pending_dir / "測試檔.txt").unlink()
    (c.pending_dir / "測試檔.txt.feeder.json").unlink()
    _feed(env, "真的.txt", b"real")

    r = ingest(c)

    assert [o.status for o in r.outcomes] == ["gone", "done"]
    assert r.ok, r.alerts
    assert ingest(c).outcomes == []          # 不會每輪重報


def test_removed_by_hand_after_an_earlier_stop_is_still_skipped(env, monkeypatch):
    """實際踩過:舊版先把手動移走的檔判成 STOP、記了一次失敗;修好後它仍要被認成「手動移走」。"""
    c = env["cfg"]
    _feed(env, "舊測試.txt", b"old")
    (c.pending_dir / "舊測試.txt").unlink()
    with Ledger(c.ledger_path) as led:
        (sha,) = [r[0] for r in led._db.execute("SELECT sha256 FROM items")]
        led.ingest_failed(sha, "STOP:找不到原件")
    r = ingest(c)
    assert [o.status for o in r.outcomes] == ["gone"]


def test_removed_from_intake_is_not_matched_to_an_older_ingested_copy(env):
    """實際踩過:收件區刪掉的測試照片,跟原件樹裡早已攝入的同一張被雜湊配對,又攝入一次。"""
    c = env["cfg"]
    (env["fraw"] / "法遵稽核與主管機關").mkdir()
    (env["fraw"] / "法遵稽核與主管機關" / "早就攝入過.jpg").write_bytes(b"same-photo")
    (c.icloud_inbox / "IMG_1.jpg").write_bytes(b"same-photo")
    collect(replace(c, raw_roots=()))                    # 模擬當時還沒有原件索引
    convert(c)
    (c.pending_dir / "IMG_1.jpg").unlink()

    r = ingest(c)

    assert [o.status for o in r.outcomes] == ["gone"]
    assert _calls(env, "claude.jsonl") == []


def test_claude_can_decline_and_file_is_parked(env, monkeypatch):
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "skip")
    _feed(env, "IMG_證件.jpg", b"id-card")

    r = ingest(c)

    (o,) = r.outcomes
    assert o.status == "discarded" and r.ok
    assert (env["fraw"] / "_捨棄候選" / "IMG_證件.jpg").exists()
    assert "私人證件" in o.notes[0]
    assert ingest(c).outcomes == []                      # 不會每輪重試、重花錢


def test_original_lost_after_moved_into_tree_stops(env, monkeypatch):
    """已經搬進 FRaw_Sources 之後才不見,不是「手動移走」:必須停止並警示。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nocommit")
    _feed(env, "k.txt", b"kkk")
    ingest(c)                                            # 第一輪失敗,原件已在 FRaw_Sources/_待處理/
    (env["fraw"] / "_待處理" / "k.txt").unlink()

    r = ingest(c)

    assert r.outcomes[0].status == "failed"
    assert any("找不到原件" in a for a in r.alerts)


def test_deleted_original_stops(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "rm")
    _feed(env, "d.txt", b"ddd")
    r = ingest(env["cfg"])
    assert any("找不到原件" in a for a in r.alerts)
    assert _remote_log(env["f_remote"]) == ["init"]


def test_leftover_uncommitted_changes_stop(env, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "dirty")
    _feed(env, "e.txt", b"eee")
    r = ingest(env["cfg"])
    assert any("沒 commit 的修改" in a for a in r.alerts)
    assert _remote_log(env["f_remote"]) == ["init"]


def _big_page(env) -> None:
    (env["fwiki"] / "Wiki_Pages" / "大頁.md").write_text("".join(f"第 {i} 行\n" for i in range(100)), encoding="utf-8")
    git("add", "-A", cwd=env["fwiki"])
    git("commit", "-q", "-m", "大頁", cwd=env["fwiki"])
    git("push", "-q", "origin", "master", cwd=env["fwiki"])


@pytest.mark.parametrize(("how", "shown"), [("cut", "大頁.md(原 100 行,淨刪 90 行)"),
                                           ("rm", "index.md(原 1 行,整個刪掉)"),
                                           ("mv", "大頁.md(原 100 行,整個刪掉)")])   # 改名也要看:連到舊頁的連結全斷
def test_ingest_that_deletes_existing_content_stops_before_push(env, monkeypatch, how, shown):
    """攝入的 claude 沒有 git diff 可用(--output= 能清空任意檔),誤刪頁面內容改由程式查:推上去之前停住等人看。"""
    _big_page(env)
    monkeypatch.setenv("FAKE_CLAUDE_SHRINK", how)
    _feed(env, "刪減.txt", b"shrink")
    r = ingest(env["cfg"])
    assert any(STOP_SHRANK in a for a in r.alerts), r.alerts
    assert any(shown in a for a in r.alerts), r.alerts
    assert _remote_log(env["f_remote"]) == ["大頁", "init"]          # 沒推上去
    assert env["cfg"].ingest_stop_path.exists()


def test_rewriting_a_page_is_not_mass_deletion_and_line_counts_go_to_summary(env, monkeypatch):
    """改寫段落是有刪有增:淨刪 25 行、佔原檔 25%,不到三成不算大量刪減,照常推送;
    增刪行數寫進摘要的標題行(取代 claude 自己報的「git diff 行數正常」);不當 ⚠️ 備註,每筆都標 ⚠️ 就沒人看了。"""
    _big_page(env)
    monkeypatch.setenv("FAKE_CLAUDE_SHRINK", "rewrite")
    _feed(env, "改寫.txt", b"rewrite")
    (o,) = ingest(env["cfg"]).outcomes
    assert o.status == "done", o.error
    assert o.lines == "+78／−100" and not any("行數" in n for n in o.notes)
    text = render_summary(env["cfg"], IngestReport([o]), datetime(2026, 10, 6))
    assert "｜行數 +78／−100" in text
    assert text.endswith("(要 revert 或搬到個人庫)。")                    # 有個人庫才提「搬」


def test_mass_deletion_with_a_leftover_file_is_recorded_as_mass_deletion(env, monkeypatch):
    """大量刪減又留下暫存檔:種類記最嚴的那一種(大量刪減),不是「留有沒 commit 的修改」——後者自動修理隔離
    暫存檔、補完就能自己解除,刪減沒人看過就推上主線(2026-10-06 審查實測)。"""
    _big_page(env)
    monkeypatch.setenv("FAKE_CLAUDE_SHRINK", "cut")
    monkeypatch.setenv("FAKE_CLAUDE_DIRTY", "1")
    _feed(env, "刪減.txt", b"shrink")
    ingest(env["cfg"])
    info = json.loads(env["cfg"].ingest_stop_path.read_text(encoding="utf-8"))
    assert info["種類"] == STOP_SHRANK
    assert "大頁.md(原 100 行,淨刪 90 行)" in info["原因"] and "還留著沒 commit 的檔" in info["原因"]
    assert _remote_log(env["f_remote"]) == ["大頁", "init"]


def test_mass_deletion_reason_says_how_many_files(env, monkeypatch):
    """原因只列前 5 個:總數要寫出來,不然看的人以為就這幾頁。"""
    monkeypatch.setattr("wiki_feeder.ingest.diff_lines",
                        lambda rc, before: (0, 7, [f"Wiki_Pages/頁{i}.md(原 1 行,清成空檔)" for i in range(7)]))
    _feed(env, "七頁.txt", b"seven")
    ingest(env["cfg"])
    reason = json.loads(env["cfg"].ingest_stop_path.read_text(encoding="utf-8"))["原因"]
    assert f"{STOP_SHRANK} 7 個檔" in reason and "只列前 5 個" in reason and "頁5.md" not in reason


@pytest.mark.parametrize("what", ["tools", "claude", "dirty"])
def test_ingest_that_touches_scripts_or_settings_stops_before_push(env, monkeypatch, what):
    """tools/ 是 make-handout 跑的腳本(跑 origin 那一版)、.claude/ 是攝入的 claude 讀的設定:攝入改了它們又推上去,
    之後每一次攝入都照它執行、照它放寬權限。推上去之前停住等人看,種類不是自動修理能補完的那一種。"""
    monkeypatch.setenv("FAKE_CLAUDE_GUARDED", what)
    _feed(env, "腳本.txt", b"script")
    r = ingest(env["cfg"])
    info = json.loads(env["cfg"].ingest_stop_path.read_text(encoding="utf-8"))
    assert info["種類"] == STOP_GUARDED, r.alerts
    assert STOP_GUARDED not in FINISHABLE
    assert ("tools/make_handout.py" if what != "claude" else ".claude/settings.local.json") in info["原因"]
    assert _remote_log(env["f_remote"]) == ["init"]


def _plain_repo(tmp_path: Path) -> tuple[Path, RepoConfig]:
    work = tmp_path / "r"
    git("init", "-q", "-b", "master", str(work), cwd=tmp_path)
    return work, RepoConfig("company", "公事庫", work, tmp_path / "FRaw_Sources", "me/FWIKI")


def _commit_all(work: Path, msg: str) -> str:
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", msg, cwd=work)
    return git("rev-parse", "HEAD", cwd=work).strip()


def test_binary_files_count_when_deleted_or_overwritten_not_when_added(tmp_path):
    """公事庫追蹤著上百張 jpg、幾份 Word 檔:二進位檔沒有行數(numstat 印 `-`),整個刪掉、被改寫都要算大量刪減
    (攝入的 claude 寫不出圖片,改了就是毀了);新增的不算。"""
    work, rc = _plain_repo(tmp_path)
    jpg = b"\xff\xd8\xff\x00jpeg\x00" * 50
    (work / "圖.jpg").write_bytes(jpg)
    (work / "規章.docx").write_bytes(b"PK\x03\x04\x00docx\x00" * 50)
    before = _commit_all(work, "init")
    (work / "圖.jpg").unlink()
    (work / "規章.docx").write_text("(已改寫)\n", encoding="utf-8")
    (work / "新圖.jpg").write_bytes(jpg)
    _commit_all(work, "攝入")
    assert sorted(diff_lines(rc, before)[2]) == ["圖.jpg(二進位檔,整個刪掉)", "規章.docx(二進位檔,內容被改寫)"]


def test_gitattributes_cannot_hide_deletions(tmp_path):
    """`*.md -diff` 的 .gitattributes 會讓頁面變成「二進位」、不給行數。屬性照攝入前那一版讀:這次 commit 的、
    沒 commit 的都不影響行數;.gitattributes 本身被改要人看(推上去之後,之後每一次攝入都照它判斷)。"""
    work, rc = _plain_repo(tmp_path)
    (work / "大頁.md").write_text("".join(f"第 {i} 行\n" for i in range(100)), encoding="utf-8")
    (work / "小頁.md").write_text("".join(f"第 {i} 行\n" for i in range(50)), encoding="utf-8")
    before = _commit_all(work, "init")
    (work / ".gitattributes").write_text("*.md -diff\n", encoding="utf-8")
    (work / "大頁.md").write_text("第 0 行\n", encoding="utf-8")
    _commit_all(work, "攝入")
    assert sorted(diff_lines(rc, before)[2]) == [".gitattributes(動到 .gitattributes:之後每一次攝入都照它判斷誰是二進位)",
                                                 "大頁.md(原 100 行,淨刪 99 行)"]
    # 沒 commit 的 .gitattributes(留在工作區)也不影響:正常加兩行就是加兩行,不會被當成「二進位檔被改寫」
    git("reset", "-q", "--hard", before, cwd=work)
    (work / "小頁.md").write_text("".join(f"第 {i} 行\n" for i in range(52)), encoding="utf-8")
    git("commit", "-q", "-am", "攝入", cwd=work)
    (work / ".gitattributes").write_text("*.md -diff\n", encoding="utf-8")
    assert diff_lines(rc, before) == (2, 0, [])


def test_deleted_page_whose_name_starts_with_a_space_still_counts(tmp_path):
    """git() 會 strip() 整段輸出:路徑排在第一個、開頭又是空白(含全形空白)時會被吃掉,刪掉的檔就對不上。"""
    work, rc = _plain_repo(tmp_path)
    (work / " 備忘.md").write_text("一\n二\n三\n", encoding="utf-8")
    (work / "其他.md").write_text("x\n", encoding="utf-8")
    before = _commit_all(work, "init")
    git("rm", "-q", " 備忘.md", cwd=work)
    _commit_all(work, "攝入")
    assert diff_lines(rc, before) == (0, 3, [" 備忘.md(原 3 行,整個刪掉)"])


def test_emptying_a_short_page_counts_as_deleting_it(tmp_path):
    """攝入的 claude 刪不了檔,能做的「整個刪掉」就是用 Write 把頁面寫空:不到 20 行也要算。"""
    work, rc = _plain_repo(tmp_path)
    (work / "短頁.md").write_text("".join(f"第 {i} 行\n" for i in range(15)), encoding="utf-8")
    (work / "留著.md").write_text("".join(f"第 {i} 行\n" for i in range(15)), encoding="utf-8")
    before = _commit_all(work, "init")
    (work / "短頁.md").write_text("", encoding="utf-8")
    (work / "留著.md").write_text("".join(f"第 {i} 行\n" for i in range(10)), encoding="utf-8")   # 刪幾行不算
    _commit_all(work, "攝入")
    assert diff_lines(rc, before) == (0, 20, ["短頁.md(原 15 行,清成空檔)"])


def test_line_counts_follow_git_and_never_decode_the_content(tmp_path):
    """原檔行數照 git 的算法、不解碼:Big5 的舊檔解碼會丟例外(不是 IngestError,整輪當掉);結尾空行也算行。"""
    work, rc = _plain_repo(tmp_path)
    (work / "舊.bat").write_bytes("".join(f"rem 第{i}行\r\n" for i in range(60)).encode("cp950") + b"\n\n\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "init", cwd=work)
    before = git("rev-parse", "HEAD", cwd=work).strip()
    (work / "舊.bat").write_bytes("".join(f"rem 第{i}行\r\n" for i in range(40)).encode("cp950"))
    git("commit", "-q", "-am", "cut", cwd=work)
    assert diff_lines(rc, before) == (0, 23, ["舊.bat(原 63 行,淨刪 23 行)"])


def test_dirty_repo_before_ingest_is_not_touched(env):
    """使用者在 Mac 上的庫有沒 commit 的東西:不可捲進自動攝入的 commit。"""
    c = env["cfg"]
    (env["fwiki"] / "使用者草稿.md").write_text("draft", encoding="utf-8")
    _feed(env, "f.txt", b"fff")
    _feed(env, "g.txt", b"ggg")
    for _ in range(c.ingest_max_attempts + 1):
        r = ingest(c)
        assert r.outcomes == [] and any("沒 commit 的修改" in a for a in r.alerts)
    assert _calls(env, "claude.jsonl") == []
    # 整輪不攝入就什麼都不動:原件留在收件區,不先搬進 FRaw 的 _待處理/ 才發現庫不乾淨
    assert {p.name for p in c.pending_dir.iterdir()} >= {"f.txt", "g.txt"}
    assert not (env["fraw"] / "_待處理").exists() or not any((env["fraw"] / "_待處理").iterdir())
    # 庫不乾淨是整輪的問題,不算在每一筆的重試次數上:草稿清掉後照常攝入
    (env["fwiki"] / "使用者草稿.md").unlink()
    assert [o.status for o in ingest(c).outcomes] == ["done", "done"]


def test_discard_candidate_is_parked_not_ingested(env, monkeypatch):
    monkeypatch.setenv("FAKE_DOC2MD_MODE", "empty")
    _feed(env, "空白.pdf", b"%PDF-blank")
    r = ingest(env["cfg"])
    assert r.outcomes[0].status == "discarded"
    assert (env["fraw"] / "_捨棄候選" / "空白.pdf").exists()
    assert _calls(env, "claude.jsonl") == []


def test_push_rejected_is_rebased_never_forced(env, monkeypatch):
    c = env["cfg"]
    other = env["tmp"] / "other"
    git("clone", "-q", str(env["f_remote"]), str(other), cwd=env["tmp"])
    _feed(env, "g.txt", b"ggg")
    real_run = run_net

    def run_with_race(cmd, *a, **k):
        if cmd[:2] == ["git", "push"] and not (other / "race.md").exists():
            (other / "race.md").write_text("windows 剛好推了", encoding="utf-8")
            git("add", "-A", cwd=other)
            git("commit", "-q", "-m", "windows backfill", cwd=other)
            git("push", "-q", "origin", "master", cwd=other)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.run_net", run_with_race)
    r = ingest(c)

    assert r.ok, r.alerts
    log = _remote_log(env["f_remote"])
    assert log[:2] == ["docs(ingest): g", "windows backfill"]   # 兩邊都在,沒有人被蓋掉


INDEX = ("# index\n\n## 最近異動\n\n- [甲/a](甲/a.md)\n- [甲/b](甲/b.md)\n- [甲/c](甲/c.md)\n\n"
         "## 頁面列表\n\n- [a](甲/a.md) — a\n- [b](甲/b.md) — b\n\n## 互動工具\n\n- 工具一\n")


def _race_on_index(env, monkeypatch, edit) -> Path:
    """FWIKI 的 index.md 換成有最近異動的版本;第一次推送前,另一台照 edit 改 index.md 並搶先推上去。"""
    fwiki = env["fwiki"]
    (fwiki / "Wiki_Pages" / "index.md").write_text(INDEX, encoding="utf-8")
    git("commit", "-q", "-am", "index", cwd=fwiki)
    git("push", "-q", "origin", "master", cwd=fwiki)
    other = env["tmp"] / "other"
    git("clone", "-q", str(env["f_remote"]), str(other), cwd=env["tmp"])
    monkeypatch.setenv("FAKE_CLAUDE_RECENT", "1")
    real_run = run_net

    def run_with_race(cmd, *a, **k):
        if cmd[:2] == ["git", "push"] and not (other / "race.md").exists():
            idx = other / "Wiki_Pages" / "index.md"
            idx.write_text(edit(idx.read_text(encoding="utf-8")), encoding="utf-8")
            (other / "race.md").write_text("windows 剛好推了", encoding="utf-8")
            git("add", "-A", cwd=other)
            git("commit", "-q", "-m", "windows 改講義", cwd=other)
            git("push", "-q", "origin", "master", cwd=other)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.run_net", run_with_race)
    return other


def _windows_recent(text: str) -> str:
    """另一台照規則把講義推到最近異動頂端、擠掉最後一筆,並改了檔尾的互動工具。"""
    return (text.replace("- [甲/a](甲/a.md)\n", "- [乙/講義](乙/講義.md)\n- [甲/a](甲/a.md)\n")
            .replace("- [甲/c](甲/c.md)\n", "").replace("- 工具一\n", "- 工具一(改版)\n"))


def test_push_conflict_only_in_recent_changes_is_merged(env, monkeypatch):
    """2026-10-19:Windows 改講義、Mac 攝入履歷同一分鐘推,兩邊的最近異動撞在 index.md 同一處,
    履歷那筆卡在本機三小時等人解。只撞在最近異動時要自己合併、照常推上去,兩邊的改動都留著。"""
    c = env["cfg"]
    _race_on_index(env, monkeypatch, _windows_recent)
    _feed(env, "履歷.txt", b"resume")

    r = ingest(c)

    assert r.ok, r.alerts
    assert _remote_log(env["f_remote"])[:2] == ["docs(ingest): 履歷", "windows 改講義"]
    idx = git("show", "master:Wiki_Pages/index.md", cwd=env["f_remote"])
    assert idx == ("# index\n\n## 最近異動\n\n- [會議與月報/履歷](會議與月報/履歷.md)\n- [乙/講義](乙/講義.md)\n"
                   "- [甲/a](甲/a.md)\n\n## 頁面列表\n\n- [履歷](會議與月報/履歷.md) — 新頁\n- [a](甲/a.md) — a\n"
                   "- [b](甲/b.md) — b\n\n## 互動工具\n\n- 工具一(改版)\n")
    assert not c.ingest_stop_path.exists()
    assert not git("status", "--porcelain", cwd=env["fwiki"])


def test_push_conflict_outside_recent_changes_still_waits_for_a_person(env, monkeypatch):
    """頁面列表也撞在同一處:程式分不出要怎麼合,照舊中止 rebase、commit 留在本機等人,絕不 --force。"""
    c = env["cfg"]
    _race_on_index(env, monkeypatch, lambda t: _windows_recent(t).replace(
        "## 頁面列表\n\n", "## 頁面列表\n\n- [講義](乙/講義.md) — 講義\n"))
    _feed(env, "履歷.txt", b"resume")

    r = ingest(c)

    assert any("rebase 失敗" in a for a in r.alerts)
    assert _remote_log(env["f_remote"])[0] == "windows 改講義"
    assert git("log", "-1", "--format=%s", cwd=env["fwiki"]).strip() == "docs(ingest): 履歷"
    assert not (env["fwiki"] / ".git" / "rebase-merge").exists()
    assert not git("status", "--porcelain", cwd=env["fwiki"])


def test_merge_recent_keeps_moved_up_entry_and_refuses_unknown_layout():
    from wiki_feeder.ingest import merge_recent

    up = INDEX.replace("- [甲/a](甲/a.md)\n", "- [乙/x](乙/x.md)\n- [甲/a](甲/a.md)\n").replace("- [甲/c](甲/c.md)\n", "")
    # 這一筆更新的是既有的 c:c 推到頂端、其餘照順序往下
    mine = INDEX.replace("- [甲/a](甲/a.md)\n", "- [甲/c](甲/c.md)\n- [甲/a](甲/a.md)\n", 1).replace(
        "- [甲/b](甲/b.md)\n- [甲/c](甲/c.md)\n", "- [甲/b](甲/b.md)\n", 1)
    out = merge_recent(INDEX, up, mine)
    assert out is not None and "## 最近異動\n\n- [甲/c](甲/c.md)\n- [乙/x](乙/x.md)\n- [甲/a](甲/a.md)\n\n" in out
    # 最近異動裡出現清單以外的文字、或標題不只一個:不接手
    odd = INDEX.replace("- [甲/c](甲/c.md)\n", "- [甲/c](甲/c.md)\n說明文字\n")
    assert merge_recent(INDEX, up, odd) is None
    assert merge_recent(INDEX, up, mine + "\n## 最近異動\n") is None


def test_push_failure_after_commit_is_not_reingested(env, monkeypatch):
    c = env["cfg"]
    _feed(env, "h.txt", b"hhh")
    real_run = run_net

    def no_push(cmd, *a, **k):
        if cmd[:2] == ["git", "push"]:
            return real_run(["false"], *a, **k)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.run_net", no_push)
    r = ingest(c)

    assert r.outcomes[0].status == "done"
    assert any("推送" in a for a in r.alerts)
    monkeypatch.undo()
    r2 = ingest(c)                                 # 下一輪:只補推,不再攝入一次
    assert r2.outcomes == []
    assert "docs(ingest): h" in _remote_log(env["f_remote"])
    assert len(_calls(env, "claude.jsonl")) == 1


def test_same_day_summaries_append_to_one_file(env):
    """一天一個留底檔,每輪追加一段:蓋掉的話,事後查問題只剩當天最後一輪。"""
    _feed(env, "i.txt", b"iii")
    ingest(env["cfg"])
    _feed(env, "j.txt", b"jjj")
    ingest(env["cfg"])
    (f,) = env["cfg"].summaries_dir.glob("*.md")
    text = f.read_text(encoding="utf-8")
    assert "i.txt" in text and "j.txt" in text and text.count("這一輪") == 2


def test_user_sidecar_goes_into_prompt_then_archived(env, monkeypatch):
    c = env["cfg"]
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    (c.icloud_inbox / "2026-10-04_143005_iPhone_錄音.json").write_text('{"補述": "重點在外包"}', encoding="utf-8")
    (c.icloud_inbox / "2026-10-04_143005_iPhone_錄音.txt").write_text("逐字稿內容", encoding="utf-8")
    collect(c)
    convert(c)
    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    ingest(c)

    assert "重點在外包" in seen[0]
    assert not any(c.pending_dir.iterdir())
    assert any(p.name.endswith(".user.json") for p in c.sidecar_archive.iterdir())


def test_md_cache_is_pruned_days_after_ingest_but_originals_never(env):
    """轉寫快取可能含證號、個資:攝入結束 7 天後刪掉。.md／.txt 原件的「轉寫」就是原件本身,絕不可刪。"""
    from datetime import datetime, timedelta

    from wiki_feeder.ingest import prune_md_cache

    c = env["cfg"]
    _feed(env, "白板.jpg", b"jpg-bytes")
    _feed(env, "筆記.txt", b"text-original")
    ingest(c)
    mds = list(c.md_cache.glob("白板-*.md"))
    assert mds

    assert prune_md_cache(c) == 0                                   # 剛攝入:不刪
    later = datetime.now().astimezone() + timedelta(days=c.md_cache_keep_days + 1)
    assert prune_md_cache(c, now=later) == 1
    assert not mds[0].exists()
    assert (env["fraw"] / "會議與月報" / "筆記.txt").read_bytes() == b"text-original"
    assert (env["fraw"] / "會議與月報" / "白板.jpg").exists()


def test_reingest_discarded_item_with_users_note(env, monkeypatch):
    """實際情境:FWIKI 判斷「與公司無關」捨棄,使用者說明「這是公司最大股東辦的活動」要求攝入。"""
    from wiki_feeder.ingest import reingest

    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "skip")
    _feed(env, "IMG_活動.JPG", b"event-photo")
    assert ingest(c).outcomes[0].status == "discarded"

    print(reingest(c, "IMG_活動.JPG", "公司最大股東辦的活動"))
    assert (env["fraw"] / "_待處理" / "IMG_活動.JPG").exists()

    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    (o,) = ingest(c).outcomes
    assert o.status == "done"
    assert "公司最大股東辦的活動" in seen[0] and "不可填 skipped" in seen[0]
    assert (env["fraw"] / "會議與月報" / "IMG_活動.JPG").exists()


def test_prompt_says_unrelated_to_business_is_not_a_reason_to_skip(env, monkeypatch):
    """使用者 2026-10-04 定案:股東、關係企業、外部活動這類「跟業務沒有直接關係」的照樣攝入 FWIKI。"""
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(env, "活動流程.jpg", b"program")
    ingest(env["cfg"])
    assert "不是不攝入的理由" in seen[0]


def test_prompt_forbids_helper_scripts_in_repo(env, monkeypatch):
    """2026-10-05:FWIKI 規則叫它把檢查寫成 .py 再跑,攝入時跑不了 python 也刪不掉,留下 .tmp_check.py 而 STOP。"""
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(env, "帳單.xlsx", b"bill")
    ingest(env["cfg"])
    assert "不得在庫裡建立任何檔案" in seen[0] and "不能執行任意 python" in seen[0]
    # 更正依據只寫在 commit 訊息裡:不先查 git 就改,會照新掃描件把使用者更正過的數字改回去
    assert "改之前先查 git 的,照規則用上面的指令查" in seen[0]


class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        assert pw == "app-password"

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def test_summary_is_also_emailed(env, monkeypatch):
    """摘要寄 Email:信是唯一會送到使用者眼前的管道(不開 Issue,使用者 2026-10-06 定案)。"""
    from wiki_feeder import notify

    _FakeSMTP.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(notify, "smtp_password", lambda cfg: "app-password")
    c = replace(env["cfg"], mail_from="me@example.com", mail_to="me@example.com")
    _feed(env, "週會.txt", "週會內容".encode())

    ingest(c)

    (msg,) = _FakeSMTP.sent
    assert "攝入 1" in msg["Subject"]
    body = msg.get_content()
    assert "週會.txt" in body and "https://github.com/me/FWIKI/commit/" in body



def test_alert_mail_subject_says_it_needs_attention(env, monkeypatch):
    """卡住(停止重試、STOP、doc2md 跑不起來)時使用者要從主旨就看出要處理,不必點開每一封摘要。"""
    from wiki_feeder import notify
    from wiki_feeder.ingest import IngestReport, post_summary

    _FakeSMTP.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(notify, "smtp_password", lambda cfg: "app-password")
    c = replace(env["cfg"], mail_from="me@example.com", mail_to="me@example.com")

    post_summary(c, IngestReport(alerts=["有 1 個檔轉寫已停止重試,卡在 _待處理/:壞檔.pdf"]))

    (msg,) = _FakeSMTP.sent
    assert msg["Subject"].startswith("⚠️ 需要處理") and "壞檔.pdf" in msg.get_content()

def test_mail_failure_does_not_break_ingest(env, monkeypatch):
    from wiki_feeder import notify

    def no_password(cfg):
        raise notify.MailError("鑰匙圈裡找不到寄信密碼")

    monkeypatch.setattr(notify, "smtp_password", no_password)
    c = replace(env["cfg"], mail_from="me@example.com", mail_to="me@example.com")
    _feed(env, "週會2.txt", "週會內容2".encode())

    r = ingest(c)

    assert r.outcomes[0].status == "done"
    assert "找不到寄信密碼" in c.alerts_path.read_text(encoding="utf-8")
    assert "週會2.txt" in _summary(env)                                    # 本機照樣留底
    assert "當日摘要發佈失敗" not in c.alerts_path.read_text(encoding="utf-8")


# -- 2026-10-05 審查:當掉、半途、發不出去 ----------------------------------------------

def test_crash_mid_ingest_stops_instead_of_pushing_unverified_commits(env, monkeypatch):
    """攝入在 claude commit 之後、驗證之前當掉(資料庫鎖逾時、行程被砍):下一輪不可把沒驗證過的
    commit 補推上主線,也不可把同一筆再攝入一次——停住等人,resume 之後才推。"""
    import sqlite3

    from wiki_feeder.ingest import resume

    c = env["cfg"]
    _feed(env, "k.txt", b"kkk")

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("wiki_feeder.ingest.new_commits", locked)
    with pytest.raises(sqlite3.OperationalError):
        ingest(c)
    monkeypatch.undo()
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(env["tmp"] / "claude.jsonl"))

    for _ in range(2):
        r = ingest(c)
        assert r.outcomes == [] and any("resume" in a for a in r.alerts)
    assert _remote_log(env["f_remote"]) == ["init"]
    assert len(_calls(env, "claude.jsonl")) == 1

    resume(c)
    r = ingest(c)
    assert r.outcomes == [] and not r.alerts                       # 那筆不自動重攝入
    assert _remote_log(env["f_remote"])[0] == "docs(ingest): k"    # 人認可後才推
    assert len(_calls(env, "claude.jsonl")) == 1


def test_claude_never_touches_the_real_wiki(env, monkeypatch):
    """回填只能寫副本(使用者 2026-10-07 放行回填,但真的個人庫有會執行腳本的 hook):claude 拿到的 --add-dir 是
    副本、不是個人庫;它若硬是在個人庫 commit,就 STOP、不推。"""
    c = env["cfg"]
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append((cmd, k.get("input", "")))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "backfill")
    _feed(env, "q.txt", b"qqq")

    r = ingest(c)

    (cmd, prompt), = seen
    stage = c.wiki_stage_dir
    assert cmd[cmd.index("--add-dir") + 1] == str(stage) and cmd.count("--add-dir") == 1
    # 寫檔、編輯可用,但不進允許清單:沒加限定的 Write／Edit 允許規則什麼路徑都寫得進去(2026-10-07 實測)
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
    assert {"Write", "Edit"} <= set(cmd[cmd.index("--tools") + 1].split(","))
    assert not [t for t in allowed if t.split("(")[0] in ("Write", "Edit")]
    denied = cmd[cmd.index("--disallowedTools") + 1:]
    assert f"Write(/{env['fwiki'].parent / 'WIKI'}/**)" in denied and f"Edit(/{env['fwiki'].parent / 'WIKI'}/**)" in denied
    assert str(env["fwiki"].parent / "WIKI") not in cmd and f"副本在 {stage}" in prompt
    assert r.outcomes[0].error.startswith("STOP:") and "WIKI" in r.outcomes[0].error
    assert c.ingest_stop_path.exists()
    assert _remote_log(env["f_remote"].parent / "WIKI.git") == ["init"]
    assert "docs(ingest): q" not in _remote_log(env["f_remote"])


def test_failed_ingest_that_left_a_commit_stops(env, monkeypatch):
    """攝入失敗(沒有公事庫的 commit)卻在個人庫留下 commit:不可等下一筆驗證通過時一起推上去。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "backfill_only")
    _feed(env, "m.txt", b"mmm")
    _feed(env, "n.txt", b"nnn")

    r = ingest(c)

    assert len(r.outcomes) == 1 and r.outcomes[0].error.startswith("STOP:")
    assert c.ingest_stop_path.exists()
    wiki_remote = env["f_remote"].parent / "WIKI.git"
    assert _remote_log(wiki_remote) == ["init"]


def test_git_history_and_page_checks_are_allowed_one_command_at_a_time(env, monkeypatch):
    """查 git 歷史、頁面檢查:提示給指令、允許清單一個子命令一條。不放行整個 wiki_feeder(resume、ingest 會動真資料),
    也不放行 git log／show／diff。"""
    c = env["cfg"]
    # 有講義腳本的庫才提重產講義(沒有的庫照桌面版講義建、沒有講義功能,提了 claude 會去找 handouts/)
    (env["fwiki"] / "tools").mkdir()
    (env["fwiki"] / "tools" / "make_handout.py").write_text("# 講義\n", encoding="utf-8")
    git("add", "-A", cwd=env["fwiki"])
    git("commit", "-q", "-m", "tools", cwd=env["fwiki"])
    git("push", "-q", "origin", "master", cwd=env["fwiki"])
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append((cmd, k.get("input", "")))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    _feed(env, "a.txt", b"aaa")
    ingest(c)

    ((cmd, prompt),) = seen
    allowed = cmd[cmd.index("--allowedTools"):cmd.index("--disallowedTools")]
    tools = [a for a in allowed if a.startswith("Bash(/x/python")]
    assert tools == [f"Bash(/x/python -P -m wiki_feeder {t}:*)"
                     for t in ("office-dump", "page-history", "commit-detail", "check-pages", "table-sums",
                               "make-handout", "add-image")]
    assert not any(a.startswith(("Bash(git log", "Bash(git show", "Bash(git diff")) for a in allowed)
    for t in ("check-pages <頁面路徑>", "page-history <頁面路徑>", "page-history --grep", "commit-detail <commit 雜湊>",
              "table-sums <頁面路徑>", "commit-detail HEAD", "make-handout --src", "add-image <"):
        assert f"`/x/python -P -m wiki_feeder {t}" in prompt
    # commit 完的自我確認寫在 commit 那一條:只寫在第 6 條長段落時,一晚 5 筆先打 git show／log 被擋
    rule2 = prompt.split("\n2. ", 1)[1].split("\n", 1)[0]
    assert "commit-detail HEAD" in rule2 and "`git show`" in rule2


def test_pages_are_checked_again_after_ingest(env, monkeypatch):
    """claude 可能沒跑 check-pages:程式對這次改過的頁面再查一次,新出現的問題列成 ⚠️ 備註,不 STOP。"""
    monkeypatch.setenv("FAKE_CLAUDE_PAGE_EXTRA", "\n說**「quoted」**中文\n路徑\x826BSI\n")
    _feed(env, "b.txt", b"bbb")
    (o,) = ingest(env["cfg"]).outcomes
    assert o.status == "done", o.error
    assert o.notes == ["頁面檢查:Wiki_Pages/會議與月報/b.md 第 5 行粗體失效(渲染後還留著 **)",
                       "頁面檢查:Wiki_Pages/會議與月報/b.md 第 6 行控制字元 U+0082"]


def test_tool_calls_blocked_by_permissions_are_logged(env, monkeypatch, caplog):
    """攝入還缺哪些只讀指令要看得到:claude 被擋下的指令記進 log(以前只能翻公事庫的 commit message 猜)。"""
    monkeypatch.setenv("FAKE_CLAUDE_DENIALS", json.dumps([
        {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "python3 /tmp/sum.py"}},
        {"tool_name": "Write", "tool_use_id": "t2", "tool_input": {"file_path": "/etc/x", "content": "y"}}]))
    _feed(env, "d.txt", b"ddd")
    with caplog.at_level(logging.INFO, logger="wiki_feeder.ingest"):
        (o,) = ingest(env["cfg"]).outcomes
    assert o.status == "done", o.error
    assert "攝入 d.txt:有 2 次工具呼叫被權限擋下:Bash: python3 /tmp/sum.py | Write: /etc/x" in caplog.text
    from wiki_feeder.toolgaps import digest
    assert any("被擋下「Bash: python3 sum.py」" in x for x in digest(env["cfg"]))   # 摘要信的提醒從這裡來


def test_checks_claude_could_not_do_reach_the_summary_and_log(env, monkeypatch, caplog):
    """claude 沒去試、直接寫「未驗」的檢查,權限擋下的紀錄看不到:要它自己回報,進摘要也進 log。"""
    monkeypatch.setenv("FAKE_CLAUDE_UNVERIFIED", json.dumps(["同名 docx 未重產:要執行本庫 tools/ 的腳本", " "]))
    _feed(env, "u.txt", b"uuu")
    with caplog.at_level(logging.INFO, logger="wiki_feeder.ingest"):
        (o,) = ingest(env["cfg"]).outcomes
    assert o.status == "done", o.error
    assert o.unverified == ["同名 docx 未重產:要執行本庫 tools/ 的腳本"]          # 空白的不算
    assert "  - 🔍 未驗:同名 docx 未重產:要執行本庫 tools/ 的腳本" in _summary(env)
    assert "攝入 u.txt:沒能驗證的項目 1 項:同名 docx 未重產" in caplog.text
    from wiki_feeder.toolgaps import digest
    assert any("未驗「同名 docx 未重產」" in x for x in digest(env["cfg"]))
    (args,) = _calls(env, "claude.jsonl")
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert "unverified" in schema["required"]


def test_commit_without_report_alerts_and_logs_why(env, monkeypatch, caplog):
    """claude commit 了卻沒交回報(2026-10-07 業務月會逐字稿,疑似花完預算):群組與原件位置都不知道,
    原件只能留在 _待處理/。要發警示(信的主旨才會標「需要處理」),log 要看得出它怎麼結束、花了多少。"""
    monkeypatch.setenv("FAKE_CLAUDE_NOREPORT", "1")
    _feed(env, "n.txt", b"nnn")
    with caplog.at_level(logging.INFO, logger="wiki_feeder.ingest"):
        rep = ingest(env["cfg"])
    (o,) = rep.outcomes
    assert o.status == "done", o.error                       # commit 已驗證、推上去:重攝入會重複建頁
    assert _remote_log(env["f_remote"])[0] == "docs(ingest): n"
    assert Path(o.raw_path) == env["fraw"] / "_待處理" / "n.txt"
    assert any("n.txt:攝入有 commit 但 claude 沒交回報(error_max_budget_usd)" in a for a in rep.alerts)
    assert "攝入 n.txt:claude 結束(error_max_budget_usd、is_error),花費 US$5.03、61 輪、497 秒,沒有結構化回報" \
        in caplog.text
    assert not any("群組「」" in n for n in o.notes)


def test_ingest_that_dies_after_committing_stops(env, monkeypatch):
    """claude commit 完才死掉(逾時、被 unstick 砍掉,沒有回報):失敗本身不是 STOP,但留下沒驗證過的 commit,
    要轉成 STOP——否則同一輪下一筆驗證通過時,會把它一起記成驗證過、推上主線。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_DIE_ON", "m.txt")
    _feed(env, "m.txt", b"mmm")
    _feed(env, "n.txt", b"nnn")

    ingest(c)

    assert c.ingest_stop_path.exists()
    assert "docs(ingest): m" not in _remote_log(env["f_remote"])


def test_rebased_commits_are_still_verified_when_push_keeps_failing(env, monkeypatch):
    """推送被拒 → pull --rebase 換掉了 commit 雜湊 → 還是推不上去:下一輪要照常補推,不可誤判成沒驗證過而 STOP。"""
    c = env["cfg"]
    other = env["tmp"] / "other"
    git("clone", "-q", str(env["f_remote"]), str(other), cwd=env["tmp"])
    _feed(env, "p.txt", b"ppp")
    real_run = run_net

    def race_then_reject(cmd, *a, **k):
        if cmd[:2] == ["git", "push"]:
            if not (other / "race.md").exists():
                (other / "race.md").write_text("windows 剛好推了", encoding="utf-8")
                git("add", "-A", cwd=other)
                git("commit", "-q", "-m", "windows backfill", cwd=other)
                git("push", "-q", "origin", "master", cwd=other)
            return real_run(["false"], *a, **k)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.run_net", race_then_reject)
    r = ingest(c)
    assert r.outcomes[0].status == "done" and any("推送" in a for a in r.alerts)
    monkeypatch.undo()
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(env["tmp"] / "claude.jsonl"))

    r = ingest(c)

    assert not c.ingest_stop_path.exists(), r.alerts
    assert _remote_log(env["f_remote"])[:2] == ["docs(ingest): p", "windows backfill"]


@pytest.mark.parametrize("crash_at", ["after_link", "after_unlink"])
def test_crash_while_moving_into_target_pending_is_finished_next_round(env, monkeypatch, crash_at):
    """原件剛搬進 FRaw_Sources/_待處理/、還沒寫進處理紀錄就當掉:下一輪要接著攝入,
    不可當成「手動移走」略過(原件會從此卡在那裡,reingest 也救不回來)。"""
    import pathlib

    c = env["cfg"]
    _feed(env, "q.txt", b"qqq")
    real_unlink = pathlib.Path.unlink

    def crash_unlink(self, *a, **k):
        if self.parent == c.pending_dir and self.name == "q.txt":
            raise KeyboardInterrupt
        return real_unlink(self, *a, **k)

    def crash_archive(*a, **k):
        raise KeyboardInterrupt

    if crash_at == "after_link":
        monkeypatch.setattr(pathlib.Path, "unlink", crash_unlink)
    else:
        monkeypatch.setattr("wiki_feeder.ingest._archive_sidecar", crash_archive)
    with pytest.raises(KeyboardInterrupt):
        ingest(c)
    monkeypatch.undo()
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(env["tmp"] / "claude.jsonl"))

    r = ingest(c)

    assert [o.status for o in r.outcomes] == ["done"], r.alerts
    assert not (c.pending_dir / "q.txt").exists()
    assert not (c.pending_dir / "q.txt.feeder.json").exists()             # sidecar 也收走了
    assert [p.read_bytes() for p in env["fraw"].rglob("q*.txt")] == [b"qqq"]   # 只有一份


def test_alerts_come_back_when_mail_did_not_go_out(env, monkeypatch):
    """摘要信寄不出去:警示不可記成已報而吞掉一天,下一輪要再報(本機留底沒有人會看)。"""
    from wiki_feeder import notify
    from wiki_feeder.collect import _alert
    from wiki_feeder.ingest import IngestReport, post_summary

    def no_password(cfg):
        raise notify.MailError("鑰匙圈裡找不到寄信密碼")

    monkeypatch.setattr(notify, "smtp_password", no_password)
    c = replace(env["cfg"], mail_from="me@example.com", mail_to="me@example.com")
    msg = "有 1 個檔攝入已停止重試:壞檔.pdf"
    assert _alert(c, msg)

    post_summary(c, IngestReport(alerts=[msg]))

    assert _alert(c, msg)                       # 撤銷了「已報」:下一輪會再發


def test_alert_stays_reported_when_mail_is_not_configured(env):
    """沒設定寄信:不撤銷「已報」,否則同一則警示每分鐘在警示檔多一行。"""
    from wiki_feeder.collect import _alert
    from wiki_feeder.ingest import IngestReport, post_summary

    c = env["cfg"]
    assert not c.mail_from
    msg = "有 1 個檔攝入已停止重試:壞檔.pdf"
    assert _alert(c, msg)

    post_summary(c, IngestReport(alerts=[msg]))

    assert not _alert(c, msg) and "壞檔.pdf" in _summary(env)


def test_crash_before_any_commit_is_not_left_stuck_silently(env, monkeypatch):
    """claude 還沒 commit 就被砍:本機沒有多出 commit,但那一筆卡在「攝入中」不再是候選——
    沒人說的話,原件就默默卡在 _待處理/。要 STOP 報出來,resume 後用 reingest 救回。"""
    from wiki_feeder.ingest import reingest, resume

    c = env["cfg"]
    _feed(env, "s.txt", b"sss")
    real_run = __import__("subprocess").run

    def killed(cmd, *a, **k):
        if "fake_claude.py" in " ".join(map(str, cmd)):
            raise KeyboardInterrupt
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", killed)
    with pytest.raises(KeyboardInterrupt):
        ingest(c)
    monkeypatch.undo()
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(env["tmp"] / "claude.jsonl"))

    r = ingest(c)
    assert any("resume" in a for a in r.alerts) and "s.txt" in c.ingest_stop_path.read_text(encoding="utf-8")

    resume(c)
    reingest(c, "s.txt", "上次攝入被中斷")
    assert [o.status for o in ingest(c).outcomes] == ["done"]


def test_unverified_local_commit_is_not_pushed_by_catch_up(env):
    """本機有一個不是攝入驗證過的 commit(當掉時處理紀錄也沒寫成、或有人在這台直接 commit):補推不可推它。"""
    c = env["cfg"]
    (env["fwiki"] / "Wiki_Pages" / "手動.md").write_text("# 手動\n", encoding="utf-8")
    git("add", "-A", cwd=env["fwiki"])
    git("commit", "-q", "-m", "manual", cwd=env["fwiki"])

    r = ingest(c)

    assert any("resume" in a for a in r.alerts)
    assert _remote_log(env["f_remote"]) == ["init"]


def test_original_goes_where_repo_rules_say(env, monkeypatch):
    """FWIKI 規則要原件放進子資料夾、改成描述性檔名(請款單 → 費用請款/YYYY-MM/):照回報的 raw_subpath 放。
    2026-10-05 實例:提示把去處寫死成原檔名,5 份請款單都以「掃描的文件*.pdf」落在群組根目錄。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_SUBPATH", "費用請款\\2026-10\\請款單-新交所機房服務費-2026-09.txt")
    _feed(env, "掃描的文件.txt", b"sgx bill")

    r = ingest(c)

    assert r.ok, r.alerts
    (o,) = r.outcomes
    dest = env["fraw"] / "會議與月報" / "費用請款" / "2026-10" / "請款單-新交所機房服務費-2026-09.txt"
    assert dest.read_bytes() == b"sgx bill" and o.raw_path == str(dest) and o.notes == [] and o.lines == "+3／−0"   # 沒有任何提醒,增刪行數在另一欄
    assert not (env["fraw"] / "會議與月報" / "掃描的文件.txt").exists()
    (args,) = _calls(env, "claude.jsonl")
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert "raw_subpath" in schema["required"]
    with Ledger(c.ledger_path) as led:
        assert led._db.execute("SELECT raw_path FROM ingests").fetchone()[0] == str(dest)


@pytest.mark.parametrize("asked", ["..\\..\\逃出去.txt", "_待處理\\x.txt", "費用請款\\副檔名不對.pdf", "\\abs.txt",
                                   "a\\b\\c\\d\\太深.txt"])
def test_unsafe_raw_subpath_falls_back_to_group_root(env, monkeypatch, asked):
    """raw_subpath 是不可信的輸出:跳出群組、進底線資料夾、換副檔名都擋下,照原名放群組根目錄並提醒對齊來源。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_SUBPATH", asked)
    _feed(env, "掃描的文件.txt", b"bill")

    (o,) = ingest(c).outcomes

    assert o.status == "done"
    assert (env["fraw"] / "會議與月報" / "掃描的文件.txt").read_bytes() == b"bill"
    assert any("不安全" in n for n in o.notes)


def test_raw_subpath_never_overwrites_existing_file(env, monkeypatch):
    c = env["cfg"]
    d = env["fraw"] / "會議與月報" / "費用請款" / "2026-10"
    d.mkdir(parents=True)
    (d / "請款單-A.txt").write_bytes(b"earlier")
    monkeypatch.setenv("FAKE_CLAUDE_SUBPATH", "費用請款\\2026-10\\請款單-A.txt")
    _feed(env, "掃描的文件.txt", b"later")

    (o,) = ingest(c).outcomes

    assert (d / "請款單-A.txt").read_bytes() == b"earlier"
    assert (d / "請款單-A_2.txt").read_bytes() == b"later"
    assert any("手動對齊" in n for n in o.notes)


def test_api_down_skips_the_round_without_counting_or_stopping(env, monkeypatch):
    """claude 連不上 API(2026-10-05 斷網實例):整輪略過,不扣次數、不留 ingesting(否則下一輪 STOP)。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "apidown")
    _feed(env, "a.txt", b"aaa")
    _feed(env, "b.txt", b"bbb")

    for _ in range(c.ingest_max_attempts + 1):
        r = ingest(c)
        assert r.outcomes == [] and any("連不上 API" in a for a in r.alerts)
    assert len(_calls(env, "claude.jsonl")) == c.ingest_max_attempts + 1   # 每輪只試第一筆就停
    assert not c.ingest_stop_path.exists()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    assert [o.status for o in ingest(c).outcomes] == ["done", "done"]


def test_only_the_managed_library_may_open_new_groups():
    """公事庫的群組照它的規則固定:回報只能從原件樹現有的群組挑。程式代管的庫(朋友照講義新建的)才可以開新群組。"""
    from wiki_feeder.ingest import _schema

    assert _schema(["會議與月報"], backfill=True, managed=False)["properties"]["group"]["enum"] == ["會議與月報"]
    assert "enum" not in _schema([], backfill=False, managed=True)["properties"]["group"]


@pytest.mark.parametrize("mode", ["loggedout", "loggedout_json"])
def test_claude_not_logged_in_skips_the_round_and_says_so(env, monkeypatch, mode):
    """朋友那台登入過期:原本每一筆記「Expecting value: line 1 column 1」、三輪後停止重試。改成整輪略過、警示講清楚。"""
    from wiki_feeder.ingest import NOT_LOGGED_IN_ALERT

    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    _feed(env, "a.txt", b"aaa")
    for _ in range(c.ingest_max_attempts + 1):
        r = ingest(c)
        assert r.outcomes == [] and len(r.alerts) == 1 and NOT_LOGGED_IN_ALERT in r.alerts[0]
    assert not c.ingest_stop_path.exists()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    assert [o.status for o in ingest(c).outcomes] == ["done"]


def test_claude_that_prints_no_json_says_what_it_printed(env, monkeypatch):
    """不是 JSON 的回應:錯誤要帶 claude 實際印的話,不是只有 json 的「Expecting value」(原件樹沒有群組時
    claude 拒絕回報格式,2026-10-20 實測只看得到 Expecting value)。"""
    import shutil

    for d in env["fraw"].iterdir():
        if d.is_dir() and not d.name.startswith("_"):
            shutil.rmtree(d)
    _feed(env, "a.txt", b"aaa")
    (o,) = ingest(env["cfg"]).outcomes
    assert o.status == "failed" and "json-schema" in o.error and "Expecting value" not in o.error


def test_network_drop_mid_round_does_not_count_against_later_files(env, monkeypatch):
    """第一筆攝入後斷網:後面幾筆 pull 失敗是整輪的問題,不可各記一次失敗(2026-10-05 實例)。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_BREAK_REMOTE", "1")
    _feed(env, "a.txt", b"aaa")
    _feed(env, "b.txt", b"bbb")

    r = ingest(c)

    assert [o.status for o in r.outcomes] == ["done"]          # 第一筆完成(commit 在本機,待補推)
    with Ledger(c.ledger_path) as led:
        rows = dict(led._db.execute("SELECT status, attempts FROM ingests WHERE status != 'done'").fetchall())
    assert rows == {"moved": 0}
    git("remote", "set-url", "origin", str(env["f_remote"]), cwd=env["fwiki"])
    monkeypatch.delenv("FAKE_CLAUDE_BREAK_REMOTE")
    r = ingest(c)
    assert [o.status for o in r.outcomes] == ["done"] and r.ok, r.alerts
    assert len(_remote_log(env["f_remote"])) == 3


def test_raw_subpath_through_a_symlink_out_of_the_group_is_refused(env, monkeypatch):
    c = env["cfg"]
    outside = env["tmp"] / "外面"
    outside.mkdir()
    try:
        (env["fraw"] / "會議與月報" / "連結").symlink_to(outside)
    except OSError as e:   # Windows 建符號連結要開發人員模式或系統管理員(WinError 1314)
        pytest.skip(f"這台建不了符號連結:{e}")
    monkeypatch.setenv("FAKE_CLAUDE_SUBPATH", "連結\\x.txt")
    _feed(env, "掃描的文件.txt", b"bill")

    (o,) = ingest(c).outcomes

    assert not any(outside.iterdir())
    assert (env["fraw"] / "會議與月報" / "掃描的文件.txt").read_bytes() == b"bill"
    assert any("不安全" in n for n in o.notes)



def test_attempt_that_died_halfway_and_left_the_repo_dirty_stops(env, monkeypatch):
    """claude 逾時或被 unstick 砍掉時,頁面可能寫到一半、沒 commit。只記一次失敗的話,之後每一輪都因
    「庫不乾淨」整輪略過,一天只有一封警示,看門狗也看不出來;要 STOP 才會有人(或修理)接手。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "halfway")
    _feed(env, "h.txt", b"hhh")
    (o,) = ingest(c).outcomes
    assert o.error.startswith("STOP:") and "寫到一半" in o.error and c.ingest_stop_path.exists()


def test_resume_landing_between_the_stop_checks_does_not_stop_again(env, monkeypatch):
    """自動修理在發佈後立刻 resume,剛好撞上發佈裝回來、馬上跑的那一輪:resume 記完已驗證、刪掉停止檔的
    那一刻,那一輪若已用舊標記算出「有沒驗證過的 commit」,又看到停止檔沒了,就會馬上再 STOP 一次。"""
    import wiki_feeder.ingest as ing
    from wiki_feeder.ingest import resume
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "dirty")
    _feed(env, "r.txt", b"rrr")
    ingest(c)
    (env["fwiki"] / "暫存.txt").unlink()
    real = ing.unverified_commits
    fired = []

    def racing(cfg, rc):
        out = real(cfg, rc)
        if not fired:
            fired.append(1)
            resume(cfg)          # 人(或修理)正好在這時解除
        return out
    monkeypatch.setattr(ing, "unverified_commits", racing)
    monkeypatch.delenv("FAKE_CLAUDE_MODE")
    ingest(c)
    info = json.loads(c.ingest_stop_path.read_text(encoding="utf-8")) if c.ingest_stop_path.exists() else {}
    assert info.get("檔案") != "(補推)"     # 看到停止檔就不再自己算一次、另開一個 STOP



def test_crash_right_after_claude_returns_stops_and_never_reingests(env, monkeypatch):
    """claude 已經 commit、回報還沒存下就當掉(行程被砍):處理紀錄要先記「攝入中」才叫 claude,
    下一輪才看得出是中斷的那一筆而 STOP;否則 resume 之後它又是候選,同一份原件再攝入一次、FWIKI 重複頁。"""
    import sqlite3
    import subprocess as sp

    from wiki_feeder.ingest import resume

    c = env["cfg"]
    _feed(env, "m.txt", b"mmm")
    real = sp.run

    def dies_after_claude(cmd, *a, **k):
        r = real(cmd, *a, **k)
        if "-p" in cmd:
            raise sqlite3.OperationalError("database is locked")
        return r
    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", dies_after_claude)
    with pytest.raises(sqlite3.OperationalError):
        ingest(c)
    monkeypatch.undo()
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(env["tmp"] / "claude.jsonl"))
    ingest(c)
    resume(c)
    ingest(c)
    assert len(_calls(env, "claude.jsonl")) == 1                   # 沒有再攝入一次


# -- 回填個人 WIKI(使用者 2026-10-07 放行):寫副本、程式檢查過才 commit ------------------------------

def _wiki(env) -> Path:
    return env["fwiki"].parent / "WIKI"


def _wiki_seed(env, files: dict[str, str]) -> None:
    w = _wiki(env)
    for rel, text in files.items():
        (w / rel).parent.mkdir(parents=True, exist_ok=True)
        (w / rel).write_text(text, encoding="utf-8")
    git("add", "-A", cwd=w)
    git("commit", "-q", "-m", "seed", cwd=w)
    git("push", "-q", "origin", "master", cwd=w)


def test_backfill_is_written_to_wiki_by_the_program_and_pushed(env, monkeypatch):
    c = env["cfg"]
    _wiki_seed(env, {"CLAUDE.md": "# 個人庫規則\n"})
    monkeypatch.setenv("FAKE_CLAUDE_STAGE", "new")
    _feed(env, "w.txt", b"www")

    r = ingest(c)

    assert r.ok, r.alerts
    (o,) = r.outcomes
    assert o.status == "done" and not o.notes
    w_remote = env["f_remote"].parent / "WIKI.git"
    assert _remote_log(w_remote)[0] == "docs(backfill): 通用知識"          # 程式 commit、推上去了
    assert "docs(ingest): w" in _remote_log(env["f_remote"])
    page = git("show", "master:Wiki_Pages/通用知識.md", cwd=w_remote)
    assert "期貨市場的一般做法" in page
    assert "- [通用知識](通用知識.md)" in git("show", "master:Wiki_Pages/index.md", cwd=w_remote)
    assert not git("status", "--porcelain", cwd=_wiki(env))
    assert "https://github.com/me/WIKI/commit/" in _summary(env)            # 摘要附個人庫的 commit 連結
    assert not c.ingest_stop_path.exists()
    # 下一筆照常:程式自己的個人庫 commit 已記成驗證過,不會被當成沒驗證的而 STOP
    _feed(env, "w2.txt", b"www2")
    r2 = ingest(c)
    assert r2.ok and r2.outcomes[0].status == "done", r2.alerts


def test_backfilled_pages_are_checked_again_by_the_program(env, monkeypatch):
    """claude 可能沒對副本跑 check-pages:寫回個人 WIKI 的頁由程式再查一次,問題列成備註、不擋回填。"""
    c = env["cfg"]
    _wiki_seed(env, {"CLAUDE.md": "# 個人庫規則\n"})
    monkeypatch.setenv("FAKE_CLAUDE_STAGE", "bold")
    _feed(env, "w.txt", b"www")

    r = ingest(c)

    (o,) = r.outcomes
    assert o.status == "done"
    assert o.notes == ["頁面檢查:WIKI Wiki_Pages/通用知識.md 第 4 行粗體失效(渲染後還留著 **)"]
    assert "前文**X（Y）**中文" in git("show", "master:Wiki_Pages/通用知識.md", cwd=env["f_remote"].parent / "WIKI.git")


@pytest.mark.parametrize("mode, why", [
    pytest.param("leak", "提到「甲公司」", id="leak"),
    pytest.param("script", "知識圖譜/ 除外", id="script"),
    pytest.param("graph", "知識圖譜/ 除外", id="graph"),
    pytest.param("nonmd", "只准新增或修改", id="nonmd"),
    pytest.param("delete", "刪掉了", id="delete"),
    pytest.param("cut", "大量刪減既有內容", id="cut"),
])
def test_bad_backfill_is_not_written_but_fwiki_ingest_completes(env, monkeypatch, mode, why):
    """回填沒過檢查:個人庫一個字都不動、改動留在 wiki-refused/、摘要列出;公事庫那筆照常完成,不 STOP。"""
    c = env["cfg"]
    _wiki_seed(env, {"Wiki_Pages/知識圖譜/_check.py": "print('ok')\n",
                     "Wiki_Pages/長頁.md": "".join(f"原本第 {i} 行\n" for i in range(60))})
    monkeypatch.setenv("FAKE_CLAUDE_STAGE", mode)
    _feed(env, "b.txt", b"bbb")

    r = ingest(c)

    (o,) = r.outcomes
    assert o.status == "done", o.error
    assert not c.ingest_stop_path.exists()
    assert "docs(ingest): b" in _remote_log(env["f_remote"])
    w_remote = env["f_remote"].parent / "WIKI.git"
    assert _remote_log(w_remote)[0] == "seed"
    assert not git("status", "--porcelain", cwd=_wiki(env))
    assert not (_wiki(env) / "Wiki_Pages" / "通用知識.md").exists()
    assert (_wiki(env) / "Wiki_Pages" / "知識圖譜" / "_check.py").read_text(encoding="utf-8") == "print('ok')\n"
    note = "".join(o.notes)
    assert "回填個人 WIKI 沒寫進去" in note and why in note
    kept = list(c.wiki_refused_dir.rglob("通用知識.md"))
    assert kept and "通用知識" in kept[0].read_text(encoding="utf-8")       # 改動沒丟,留給人看
    assert "回填個人 WIKI 沒寫進去" in _summary(env)


def test_stage_is_rebuilt_from_wiki_for_every_ingest(env, monkeypatch):
    """副本每筆重建:上一筆被擋下、留在副本裡的改動,不會在下一筆被當成新的回填寫進個人庫。"""
    c = env["cfg"]
    monkeypatch.setenv("FAKE_CLAUDE_STAGE", "leak")
    _feed(env, "s1.txt", b"s1")
    assert ingest(c).outcomes[0].status == "done"
    monkeypatch.delenv("FAKE_CLAUDE_STAGE")
    _feed(env, "s2.txt", b"s2")

    r = ingest(c)

    assert r.ok and not r.outcomes[0].notes, r.outcomes[0].notes
    assert _remote_log(env["f_remote"].parent / "WIKI.git") == ["init"]
    assert not (c.wiki_stage_dir / "Wiki_Pages" / "通用知識.md").exists()


def test_wiki_push_failure_is_retried_next_round_without_stop(env, monkeypatch):
    """個人庫推不上去(斷網):程式自己 commit 的那筆是驗證過的,下一輪補推、不當成沒驗證的 commit 而 STOP。"""
    c = env["cfg"]
    w, w_remote = _wiki(env), env["f_remote"].parent / "WIKI.git"
    monkeypatch.setenv("FAKE_CLAUDE_BREAK_WIKI_REMOTE", "1")
    monkeypatch.setenv("FAKE_CLAUDE_STAGE", "new")
    _feed(env, "p1.txt", b"p1")
    r = ingest(c)
    assert r.outcomes[0].status == "done" and r.alerts            # 推送失敗列進警示
    git("remote", "set-url", "origin", str(w_remote), cwd=w)
    monkeypatch.delenv("FAKE_CLAUDE_STAGE")
    monkeypatch.delenv("FAKE_CLAUDE_BREAK_WIKI_REMOTE")
    _feed(env, "p2.txt", b"p2")

    r2 = ingest(c)

    assert not c.ingest_stop_path.exists(), r2.outcomes[0].error
    assert r2.outcomes[0].status == "done"
    assert _remote_log(w_remote)[0] == "docs(backfill): 通用知識"   # 補推上去了
