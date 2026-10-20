"""每個子命令都要能從命令列跑起來(曾因 convert 讀到只屬於 collect 的參數而整個炸掉)。"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from wiki_feeder.cli import main

mac_only = pytest.mark.skipif(sys.platform == "win32", reason="deploy／launchd.py 只在 Mac(開頭 import fcntl);Windows 用 winsched.py、不 deploy")

FAKE = Path(__file__).with_name("fake_doc2md.py")


@pytest.mark.parametrize("argv", [["collect"], ["collect", "--list"], ["collect", "--only", "icloud"],
                                  ["convert"], ["ledger"]])
def test_every_subcommand_runs(cfg, argv):
    c = replace(cfg, doc2md_cmd=(sys.executable, str(FAKE)))
    (c.icloud_inbox / "a.jpg").write_bytes(b"jpg")
    assert main(argv, cfg=c) == 0


def test_log_rotates_and_keeps_only_a_few_files(cfg):
    import logging

    from wiki_feeder import cli

    cli._setup_logging(cfg)
    line = "x" * 1000
    for _ in range(8000):                      # 約 8 MB
        logging.info(line)
    files = sorted(cfg.log_path.parent.glob("feeder.log*"))
    assert len(files) == 1 + cli.LOG_BACKUPS
    assert sum(f.stat().st_size for f in files) <= (1 + cli.LOG_BACKUPS) * cli.LOG_MAX_BYTES + 2000


def test_idle_run_writes_nothing_to_the_log(cfg):
    """launchd 每分鐘一輪:沒事就不寫,否則 log 一天多出幾千行空摘要。"""
    assert main(["collect"], cfg=cfg) == 0
    assert not cfg.log_path.exists() or "收件" not in cfg.log_path.read_text(encoding="utf-8")
    (cfg.icloud_inbox / "a.txt").write_bytes(b"a")
    assert main(["collect"], cfg=cfg) == 0
    assert "取到 1" in cfg.log_path.read_text(encoding="utf-8")


def test_runs_without_any_std_streams(cfg, monkeypatch):
    """Windows 工作排程器跑的 pythonw.exe:stdin／stdout／stderr 都是 None。曾在 sys.stderr.isatty() 當掉,
    每一輪結束碼 1、log 一行都沒有、檔案一直留在收件匣(2026-10-20 Windows 實測)。"""
    for name in ("stdin", "stdout", "stderr"):
        monkeypatch.setattr(sys, name, None)
    (cfg.icloud_inbox / "a.txt").write_bytes(b"a")
    assert main(["collect"], cfg=cfg) == 0
    assert "取到 1" in cfg.log_path.read_text(encoding="utf-8")


@mac_only
def test_run_waits_out_a_deploy_and_deploy_waits_for_the_whole_run(cfg):
    """deploy 握 deploy.lock 時新的一輪直接結束;一輪在跑(含鎖外的寄摘要信)時 deploy 等它。"""
    import fcntl

    (cfg.icloud_inbox / "a.txt").write_bytes(b"a")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.deploy_lock_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main(["collect"], cfg=cfg) == 0
        assert (cfg.icloud_inbox / "a.txt").exists()          # 發佈中:沒有動任何檔
    assert main(["collect"], cfg=cfg) == 0
    assert not (cfg.icloud_inbox / "a.txt").exists()
