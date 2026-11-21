"""gitsync 的邊角:跟上遠端時「只碰自己開始的 rebase」。整條推送流程在 test_ingest／test_futures_inbox 用假 remote 測,
這裡用假的 git 指令演出真 git 很難湊出來的時機(別人剛好同時開始 rebase、中止失敗)。"""
from __future__ import annotations

import subprocess

from conftest import git

from wiki_feeder import gitsync


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    return repo


def _runner(repo, rebase_err: str, abort_clears: bool = True):
    """fetch 成功;rebase 失敗並留下 rebase-merge(像停在 rebase 中);abort 照 abort_clears 收拾。記下每個指令。"""
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == "rebase" and args[1] == "-q":
            (repo / ".git" / "rebase-merge").mkdir(exist_ok=True)
            return subprocess.CompletedProcess(args, 1, "", rebase_err)
        if args[:2] == ("rebase", "--abort") and abort_clears:
            (repo / ".git" / "rebase-merge").rmdir()
        return subprocess.CompletedProcess(args, 0, "", "")

    return run, calls


def test_someone_starting_a_rebase_at_the_same_moment_is_not_aborted(tmp_path):
    """fetch 之後、我們的 rebase 之前,有人(桌面的 pull-all)剛好開始 rebase:那是人的,不中止、不留我們的記號。"""
    repo = _repo(tmp_path)
    run, calls = _runner(repo, "fatal: It seems that there is already a rebase-merge directory")
    state, _ = gitsync.rebase_onto_remote(repo, "main", run)
    assert state == gitsync.TRANSIENT
    assert ("rebase", "--abort") not in calls
    assert not gitsync.ours(repo)


def test_mark_stays_when_abort_fails_so_next_round_cleans_up_its_own_rebase(tmp_path):
    """真的衝突、中止也失敗:記號要留著,下一輪才認得出這個停在半路的 rebase 是自己的、照自己的收拾;
    清掉的話它看起來像「有人在處理」,攝入就安靜地一直暫停。"""
    repo = _repo(tmp_path)
    run, calls = _runner(repo, "CONFLICT (content): Merge conflict in a.md", abort_clears=False)
    state, _ = gitsync.rebase_onto_remote(repo, "main", run)
    assert state == gitsync.CONFLICT
    assert ("rebase", "--abort") in calls
    assert gitsync.ours(repo)
