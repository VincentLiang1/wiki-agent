"""常駐身分下的冒煙檢查 `wiki-feeder selfcheck`(selfcheck.py;scripts/launchd.py check 在 launchd 底下叫它)。

真的 claude、鑰匙圈、GitHub 一個都不碰:claude 與 doc2md 換成假腳本,鑰匙圈換成假的 secret,git 用 tmp_path 的 bare remote。
每一項都要測「不可用」那一支:吞掉的話,資安修正把憑證弄壞時 check 照樣說全部可用(2026-11-11、11-12 兩次整晚停擺)。
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import git
from wiki_feeder import selfcheck
from wiki_feeder.config import RepoConfig

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="假的固定入口是 sh 腳本;Windows 的入口是真的 .exe")
FAKE_DOC2MD = Path(__file__).parent / "fake_doc2md.py"
CORE_INFO = {"name": "Scribe2MD", "version": "1.12.0", "build": "core", "entry_contract": 1}

# 假的 claude:FAKE_SC_MODE 決定回什麼,收到的參數記在 FAKE_SC_ARGS;--version 印 FAKE_SC_VERSION(沒給就失敗)
FAKE_CLAUDE = r'''
import json, os, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    v = os.environ.get("FAKE_SC_VERSION")
    if not v:
        sys.exit(1)
    print(v)
    sys.exit(0)
with open(os.environ["FAKE_SC_ARGS"], "w", encoding="utf-8") as f:
    json.dump({"args": args, "cwd": os.getcwd()}, f)
mode = os.environ.get("FAKE_SC_MODE", "ok")
if not sys.stdin.read().strip():   # 真的 claude:提示被 --tools 吃掉、stdin 又沒給時這樣結束(2026-11-14 實測)
    print("Error: Input must be provided either through stdin or as a prompt argument when using --print", file=sys.stderr)
    sys.exit(1)
if mode == "ok":
    print(json.dumps({"type": "result", "is_error": False, "result": "OK"}))
elif mode == "loggedout":
    print("Not logged in · Please run /login", file=sys.stderr)
    sys.exit(1)
elif mode == "loggedout_json":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}))
elif mode == "apidown":
    print(json.dumps({"type": "result", "is_error": True,
                      "result": "API Error: Connection refused — a firewall or proxy may be blocking it (ECONNREFUSED)"}))
elif mode == "hang":
    time.sleep(30)
else:
    print("boom", file=sys.stderr)
    sys.exit(3)
'''


@pytest.fixture
def scfg(cfg, tmp_path, monkeypatch):
    fake = tmp_path / "fake_claude_sc.py"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    monkeypatch.setenv("FAKE_SC_ARGS", str(tmp_path / "claude-args.json"))
    # 公事庫:本機 clone 一個 bare remote
    remote = tmp_path / "fwiki.git"
    git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    repo = tmp_path / "FWIKI"
    git("clone", "-q", str(remote), str(repo), cwd=tmp_path)
    (repo / "a.md").write_text("a", encoding="utf-8")
    git("add", "a.md", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    git("push", "-q", "origin", "HEAD:main", cwd=repo)
    rc = RepoConfig(key="company", label="公事庫", repo_dir=repo, raw_root=tmp_path / "FRaw", github="", branch="main")
    return replace(cfg, claude_cmd=(sys.executable, str(fake)), repos=(rc,),
                   mail_from="me@example.com", mail_to="me@example.com")


def _args(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "claude-args.json").read_text(encoding="utf-8"))


# --- claude ---

def test_claude_ok_uses_the_cheapest_model_and_the_ingest_setting_sources(scfg, tmp_path, monkeypatch):
    """跟攝入一樣帶 --setting-sources user,project(否則實測的不是攝入那一套設定);最便宜的模型、不給工具、不在知識庫裡跑。"""
    monkeypatch.setenv("FAKE_SC_MODE", "ok")
    assert selfcheck.check_claude(scfg) == (True, "回得來")
    got = _args(tmp_path)
    a = got["args"]
    assert a[a.index("--setting-sources") + 1] == "user,project"
    assert a[a.index("--model") + 1] == "haiku"
    assert a[a.index("--tools") + 1] == "" and selfcheck.PROMPT not in a   # 提示放 --tools 後面會被當成工具名
    assert Path(got["cwd"]).resolve() == scfg.state_dir.resolve()


@pytest.mark.parametrize("mode", ["loggedout", "loggedout_json"])
def test_claude_logged_out_is_told_apart(scfg, monkeypatch, mode):
    """沒登入(stderr 一句或 JSON 的 is_error,真的 claude 兩種都見過)要明講是沒登入:修法是重新登入,不是等網路。"""
    monkeypatch.setenv("FAKE_SC_MODE", mode)
    ok, why = selfcheck.check_claude(scfg)
    assert not ok and why.startswith("沒登入")


def test_claude_api_down_is_told_apart(scfg, monkeypatch):
    monkeypatch.setenv("FAKE_SC_MODE", "apidown")
    ok, why = selfcheck.check_claude(scfg)
    assert not ok and why.startswith("連不上")


def test_claude_hang_counts_as_unreachable(scfg, monkeypatch):
    monkeypatch.setenv("FAKE_SC_MODE", "hang")
    monkeypatch.setattr(selfcheck, "CLAUDE_TIMEOUT", 1)
    ok, why = selfcheck.check_claude(scfg)
    assert not ok and why.startswith("連不上")


def test_claude_other_failure_is_not_ok(scfg, monkeypatch):
    monkeypatch.setenv("FAKE_SC_MODE", "weird")
    ok, why = selfcheck.check_claude(scfg)
    assert not ok and "boom" in why


def test_claude_missing_binary_is_not_ok(scfg, tmp_path):
    ok, _ = selfcheck.check_claude(replace(scfg, claude_cmd=(str(tmp_path / "沒有這個" / "claude"),)))
    assert not ok


# --- 記下 claude 版本 ---

def test_claude_version_is_recorded_and_a_change_is_flagged(scfg, monkeypatch):
    """claude 換版要提醒重跑攝入權限實測:權限參數的行為可能變了(docs/dev/攝入權限實測.md)。"""
    monkeypatch.setenv("FAKE_SC_MODE", "ok")
    monkeypatch.setattr(selfcheck, "CHECKS", {n: (lambda c: (True, "")) for n in selfcheck.ITEMS})
    monkeypatch.setenv("FAKE_SC_VERSION", "2.1.0 (Claude Code)")
    _, lines = selfcheck.run(scfg)
    assert (scfg.state_dir / selfcheck.VERSION_FILE).read_text(encoding="utf-8").strip() == "2.1.0 (Claude Code)"
    assert not any("版本變了" in ln for ln in lines)          # 第一次只記下
    _, lines = selfcheck.run(scfg)
    assert not any("版本變了" in ln for ln in lines)          # 沒變不吵
    monkeypatch.setenv("FAKE_SC_VERSION", "2.2.0 (Claude Code)")
    _, lines = selfcheck.run(scfg)
    changed = [ln for ln in lines if "版本變了" in ln]
    assert len(changed) == 1 and "2.1.0" in changed[0] and "2.2.0" in changed[0] and "攝入權限實測" in changed[0]
    assert (scfg.state_dir / selfcheck.VERSION_FILE).read_text(encoding="utf-8").strip() == "2.2.0 (Claude Code)"


def test_claude_version_unknown_keeps_the_record(scfg, monkeypatch):
    monkeypatch.delenv("FAKE_SC_VERSION", raising=False)
    (scfg.state_dir).mkdir(parents=True, exist_ok=True)
    (scfg.state_dir / selfcheck.VERSION_FILE).write_text("2.1.0\n", encoding="utf-8")
    assert selfcheck.claude_version(scfg) == ("", "2.1.0")
    assert (scfg.state_dir / selfcheck.VERSION_FILE).read_text(encoding="utf-8") == "2.1.0\n"


# --- 寄信密碼 ---

def test_mail_password_read_without_sending(scfg, monkeypatch):
    import smtplib
    monkeypatch.setattr("wiki_feeder.notify.secret", lambda s, a: "abcd efgh")
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **k: pytest.fail("check 不可以真的寄信"))
    ok, why = selfcheck.check_mail(scfg)
    assert ok and "wiki-feeder-smtp" in why


def test_mail_password_missing_is_not_ok(scfg, monkeypatch):
    monkeypatch.setattr("wiki_feeder.notify.secret", lambda s, a: None)
    ok, why = selfcheck.check_mail(scfg)
    assert not ok and "寄信密碼" in why


def test_mail_not_configured_is_not_ok(scfg, monkeypatch):
    monkeypatch.setattr("wiki_feeder.notify.secret", lambda s, a: "pw")
    assert not selfcheck.check_mail(replace(scfg, mail_to=""))[0]


# --- git 遠端 ---

def test_git_remote_reachable(scfg):
    ok, why = selfcheck.check_git(scfg)
    assert ok and "FWIKI" in why


def test_git_remote_unreachable_is_not_ok(scfg, tmp_path):
    git("remote", "set-url", "origin", str(tmp_path / "不存在.git"), cwd=scfg.repos[0].repo_dir)
    ok, why = selfcheck.check_git(scfg)
    assert not ok and "ls-remote" in why


def test_git_goes_through_run_net_with_a_timeout(scfg, monkeypatch):
    """ls-remote 經 ssh 卡過 44 分鐘(proc.py):一定走 run_net、有逾時。"""
    seen = {}
    real = selfcheck.run_net

    def spy(cmd, timeout, **kw):
        seen["timeout"] = timeout
        return real(cmd, timeout, **kw)
    monkeypatch.setattr(selfcheck, "run_net", spy)
    selfcheck.check_git(scfg)
    assert 0 < seen["timeout"] <= 120


# --- doc2md 固定入口 ---

def _entry(root: Path) -> None:
    from wiki_feeder.doc2md import entry_exe
    exe = entry_exe(root)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_DOC2MD}" "$@"\n', encoding="utf-8")
    exe.chmod(0o755)


@posix_only
def test_doc2md_fixed_entry_answers(scfg, tmp_path, monkeypatch):
    root = tmp_path / "meeting-scribe"
    _entry(root)
    monkeypatch.setenv("FAKE_DOC2MD_VERSION", json.dumps(CORE_INFO))
    ok, why = selfcheck.check_doc2md(replace(scfg, doc2md_root=root))
    assert ok and "1.12.0" in why


@posix_only
def test_doc2md_old_or_broken_entry_is_not_ok(scfg, tmp_path, monkeypatch):
    root = tmp_path / "meeting-scribe"
    _entry(root)
    monkeypatch.delenv("FAKE_DOC2MD_VERSION", raising=False)   # 舊版:argparse 報錯、離開碼 2
    assert not selfcheck.check_doc2md(replace(scfg, doc2md_root=root))[0]
    assert not selfcheck.check_doc2md(replace(scfg, doc2md_root=tmp_path / "沒裝"))[0]
    assert not selfcheck.check_doc2md(replace(scfg, doc2md_root=None))[0]


# --- 整體 ---

def test_any_unavailable_item_fails_the_whole_check(scfg, monkeypatch):
    monkeypatch.delenv("FAKE_SC_VERSION", raising=False)
    for bad in selfcheck.ITEMS:
        monkeypatch.setattr(selfcheck, "CHECKS", {n: (lambda c, n=n: (n != bad, "原因")) for n in selfcheck.ITEMS})
        ok, lines = selfcheck.run(scfg)
        text = "\n".join(lines)
        assert not ok and not selfcheck.passed(text)
        assert f"{bad}\t不可用\t原因" in text


def test_passed_needs_every_item_to_say_available():
    """空輸出、少一項(沒跑到就當掉)都不算過。"""
    good = "\n".join(f"{n}\t可用\tx" for n in selfcheck.ITEMS)
    assert selfcheck.passed(good)
    assert not selfcheck.passed("")
    assert not selfcheck.passed("\n".join(good.splitlines()[1:]))
    assert not selfcheck.passed(good.replace("mail\t可用", "mail\t不可用"))


def test_cli_exit_code_follows_the_result(scfg, monkeypatch, capsys):
    from wiki_feeder.cli import main
    monkeypatch.delenv("FAKE_SC_VERSION", raising=False)
    monkeypatch.setattr(selfcheck, "CHECKS", {n: (lambda c: (True, "好")) for n in selfcheck.ITEMS})
    assert main(["selfcheck"], cfg=scfg) == 0
    monkeypatch.setattr(selfcheck, "CHECKS", {n: (lambda c, n=n: (n != "git", "壞")) for n in selfcheck.ITEMS})
    assert main(["selfcheck"], cfg=scfg) == 1
    assert "git\t不可用\t壞" in capsys.readouterr().out
