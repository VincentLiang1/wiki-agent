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


# --- 介面語言(i18n.py):朋友的設定檔 [general] language;使用者本人永遠繁中原文 ---
_CJK = r"[㐀-鿿]"


def test_list_prints_readable_in_the_original_words(cfg, capsys):
    """使用者本人(zh-Hant):scripts/launchd.py 以 "\\t可讀" 比對,一個字都不能變。"""
    assert main(["collect", "--list"], cfg=cfg) == 0
    assert capsys.readouterr().out.splitlines() == ["iCloud\t可讀,0 組候選", "OneDrive\t可讀,0 組候選"]


def test_list_says_readable_in_the_config_language(cfg, capsys):
    """英文設定檔:「可讀」是單獨一個鍵,scripts/macsched.py 以 "\\t" + L("可讀") 比對;錯誤那行也是英文。"""
    import re

    from wiki_feeder import i18n

    c = replace(cfg, lang="en", onedrive_inbox=cfg.onedrive_inbox.parent / "gone")
    (c.icloud_inbox / "a.jpg").write_bytes(b"jpg")
    assert main(["collect", "--list"], cfg=c) == 0
    assert i18n.get_lang() == "en"                      # 整個行程照設定檔的語言
    readable = i18n.L("可讀")
    assert readable != "可讀" and not re.search(_CJK, readable)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "iCloud\t" + readable + i18n.L(",{n} 組候選", n=1)
    assert lines[0].startswith("iCloud\t" + readable) and not re.search(_CJK, lines[0])
    assert lines[-1].startswith("OneDrive\t" + i18n.L("錯誤:")) and "錯誤" not in lines[-1]


def test_test_mail_subject_follows_the_config_language(cfg, monkeypatch, capsys):
    import re

    from wiki_feeder import notify

    sent = []
    monkeypatch.setattr(notify, "send", lambda c, subject, body: sent.append((subject, body)))
    c = replace(cfg, lang="en", mail_from="a@example.com", mail_to="b@example.com")
    assert main(["test-mail"], cfg=c) == 0
    (subject, body), = sent
    assert "wiki-feeder" in subject and not re.search(_CJK, subject) and not re.search(_CJK, body)
    assert not re.search(_CJK, capsys.readouterr().out)

    def fail(c, subject, body):
        raise notify.MailError("boom")
    monkeypatch.setattr(notify, "send", fail)
    assert main(["test-mail"], cfg=c) == 1
    out = capsys.readouterr().out
    assert "boom" in out and not re.search(_CJK, out)


def test_missing_config_is_reported_in_the_system_language(tmp_path, monkeypatch, capsys):
    """還沒有設定檔就不知道朋友選的語言:錯誤訊息照系統介面語言(i18n.detect)。"""
    import re

    from wiki_feeder import cli

    monkeypatch.setattr("wiki_feeder.config.PLATFORM", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "detect", lambda: "en")
    assert main(["ledger"]) == 2
    err = capsys.readouterr().err
    assert "wiki-feeder" in err and not re.search(_CJK, err.replace("安裝.bat", ""))
