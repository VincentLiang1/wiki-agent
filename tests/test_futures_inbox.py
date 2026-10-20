"""FUTURES 入口:用 tmp_path 裡的假 bare remote,絕不碰真的 FUTURES。"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder.collect import collect
from wiki_feeder.inboxes import FuturesInbox
from wiki_feeder.ledger import Ledger


def _run(cfg, futures_cfg):
    return collect(replace(cfg, icloud_inbox=None, onedrive_inbox=None, futures=futures_cfg))


def test_takes_process_files_and_pushes_removal(cfg, futures_cfg, fake_futures):
    fake_futures.write("PROCESS/會議紀錄.txt", "公司端放的無害檔")
    fake_futures.write("PROCESS/子目錄/b.txt", "第二個")
    fake_futures.push()

    r = _run(cfg, futures_cfg)

    assert r.ok, r.alerts
    assert sorted(r.moved) == sorted(str(cfg.pending_dir / n) for n in ("會議紀錄.txt", "b.txt"))
    assert (cfg.pending_dir / "會議紀錄.txt").read_text(encoding="utf-8") == "公司端放的無害檔"
    side = json.loads((cfg.pending_dir / "會議紀錄.txt.feeder.json").read_text(encoding="utf-8"))
    assert side["來源"] == "FUTURES" and side["原路徑"] == "PROCESS/會議紀錄.txt" and side["commit"]
    # 遠端:只少了取走的兩個檔,_.txt 與 PROCESS 以外的檔都還在
    assert fake_futures.remote_files() == {"PROCESS/_.txt", "公司工作檔/機密.txt", "根目錄檔.txt"}


def test_placeholder_txt_is_never_taken(cfg, futures_cfg, fake_futures):
    r = _run(cfg, futures_cfg)
    assert r.moved == [] and r.ok
    assert "PROCESS/_.txt" in fake_futures.remote_files()


def test_sparse_checkout_never_materializes_company_files(cfg, futures_cfg, fake_futures):
    _run(cfg, futures_cfg)
    repo = futures_cfg.repo_dir
    assert (repo / "PROCESS" / "_.txt").exists()
    assert not (repo / "根目錄檔.txt").exists()
    assert not (repo / "公司工作檔").exists()


def test_file_arriving_after_pull_is_not_removed(cfg, futures_cfg, fake_futures, monkeypatch):
    """pull 之後、推回之前公司端又推了新檔:新檔不可被 git rm,留給下一輪。"""
    fake_futures.write("PROCESS/first.txt", "第一個")
    fake_futures.push()
    real_finish = FuturesInbox.finish

    def finish_with_race(self):
        fake_futures.write("PROCESS/late.txt", "晚到的")
        fake_futures.push("company pushes during our run")
        real_finish(self)

    monkeypatch.setattr(FuturesInbox, "finish", finish_with_race)
    r = _run(cfg, futures_cfg)

    assert r.ok, r.alerts  # 推送被拒 → pull --rebase → 重推成功
    files = fake_futures.remote_files()
    assert "PROCESS/late.txt" in files
    assert "PROCESS/first.txt" not in files

    monkeypatch.setattr(FuturesInbox, "finish", real_finish)
    r2 = _run(cfg, futures_cfg)
    assert [Path(p).name for p in r2.moved] == ["late.txt"]
    assert "PROCESS/late.txt" not in fake_futures.remote_files()


def test_same_content_already_taken_is_only_removed(cfg, futures_cfg, fake_futures):
    (cfg.icloud_inbox / "x.txt").write_text("同一份", encoding="utf-8")
    collect(replace(cfg, onedrive_inbox=None))
    fake_futures.write("PROCESS/x-copy.txt", "同一份")
    fake_futures.push()

    r = _run(cfg, futures_cfg)

    assert r.duplicates == ["FUTURES:PROCESS/x-copy.txt"]
    assert "PROCESS/x-copy.txt" not in fake_futures.remote_files()
    with Ledger(cfg.ledger_path) as led:
        assert led.count() == 1


def test_unreachable_remote_alerts(cfg, futures_cfg, tmp_path):
    bad = replace(futures_cfg, remote=(tmp_path / "nope.git").as_uri())
    r = _run(cfg, bad)
    assert not r.ok
    assert any("FUTURES" in a for a in r.alerts)


@pytest.mark.skipif(sys.platform == "win32", reason="假的 git 是 sh 腳本;FUTURES 只在使用者的 Mac 上收")
def test_hanging_remote_times_out_and_alerts(cfg, futures_cfg, fake_futures, tmp_path, monkeypatch):
    """2026-10-05:ls-remote 經 ssh 卡 44 分鐘,收件停擺、還一直握著 deploy.lock 讓發佈等不到。"""
    import os
    import shutil
    import time

    real = shutil.which("git")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "git"
    fake.write_text(f'#!/bin/sh\ncase "$*" in *ls-remote*) sleep 30 & sleep 30; exit 0;; esac\nexec "{real}" "$@"\n')
    fake.chmod(0o755)
    fake_futures.write("PROCESS/a.txt", "a")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    t = time.monotonic()
    r = _run(cfg, replace(futures_cfg, net_timeout=2))
    assert time.monotonic() - t < 20
    assert any("FUTURES" in a and "逾時" in a for a in r.alerts)


def test_failed_push_is_retried_next_round_without_force(cfg, futures_cfg, fake_futures):
    fake_futures.write("PROCESS/a.txt", "a")
    fake_futures.push()

    r = _run(cfg, replace(futures_cfg, push_retries=0))  # 模擬推不上去
    assert any("推送失敗" in a for a in r.alerts)
    assert "PROCESS/a.txt" in fake_futures.remote_files()  # 遠端還沒清
    assert (cfg.pending_dir / "a.txt").exists()             # 但副本已安全落地

    fake_futures.write("PROCESS/b.txt", "b")  # 期間公司端又推了東西
    fake_futures.push()
    r2 = _run(cfg, futures_cfg)

    assert r2.ok, r2.alerts
    assert fake_futures.remote_files() == {"PROCESS/_.txt", "公司工作檔/機密.txt", "根目錄檔.txt"}
    log = git("log", "--format=%s", "main", cwd=fake_futures.remote)
    assert log.count("process: 取走") == 2


def test_remote_is_checked_at_most_every_interval(cfg, futures_cfg, fake_futures):
    """launchd 每分鐘一輪,但 FUTURES 的遠端只每 5 分鐘查一次(公司端只在鎖定／登入時才推)。"""
    import os
    import time

    fc = replace(futures_cfg, check_interval=300)
    _run(cfg, fc)
    fake_futures.write("PROCESS/new.txt", "剛推上來")
    fake_futures.push()

    assert _run(cfg, fc).moved == []                    # 還在 5 分鐘內:不連 GitHub

    stamp = cfg.state_dir / "futures_last_check"
    old = time.time() - 301
    os.utime(stamp, (old, old))
    assert [Path(p).name for p in _run(cfg, fc).moved] == ["new.txt"]
