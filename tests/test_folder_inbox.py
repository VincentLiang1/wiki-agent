"""iCloud／OneDrive 資料夾入口與共同主流程。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import replace

import pytest

from wiki_feeder import collect as collect_mod
from wiki_feeder import inboxes, mover
from wiki_feeder.collect import collect, run_lock
from wiki_feeder.ledger import Ledger


def _pending_files(cfg) -> list[str]:
    if not cfg.pending_dir.exists():
        return []
    return sorted(p.name for p in cfg.pending_dir.iterdir())


def _ledger_count(cfg) -> int:
    with Ledger(cfg.ledger_path) as led:
        return led.count()


def test_moves_file_writes_sidecar_and_ledger(cfg):
    src = cfg.icloud_inbox / "2026-10-04_143005_iPhone_錄音.m4a"
    src.write_bytes(b"audio-1")

    r = collect(cfg)

    assert r.ok
    assert not src.exists()
    dest = cfg.pending_dir / src.name
    assert dest.read_bytes() == b"audio-1"
    side = json.loads((cfg.pending_dir / (src.name + ".feeder.json")).read_text(encoding="utf-8"))
    assert side["來源"] == "iCloud"
    assert side["原路徑"] == src.name
    assert side["sha256"] == mover.sha256_of(dest)
    assert _ledger_count(cfg) == 1


def test_verification_failure_keeps_source(cfg, monkeypatch):
    """複製出來的內容跟來源不同 → 不落正式名、不寫紀錄、不刪來源。"""
    src = cfg.onedrive_inbox / "逐字稿.md"
    src.write_text("原始內容", encoding="utf-8")
    real_copy = mover.shutil.copy2

    def corrupt_copy(a, b):
        real_copy(a, b)
        with open(b, "ab") as f:
            f.write(b"!")

    monkeypatch.setattr(mover.shutil, "copy2", corrupt_copy)

    r = collect(cfg)

    assert src.read_text(encoding="utf-8") == "原始內容"
    assert _pending_files(cfg) == []  # 連 .partial 都不留
    assert _ledger_count(cfg) == 0
    assert r.failed == ["OneDrive:逐字稿.md"]
    assert not r.ok


def test_ledger_write_failure_keeps_source(cfg, monkeypatch):
    """處理紀錄寫不進去就不可刪來源(副本可能已落地,下一輪重複也比遺失好)。"""
    src = cfg.icloud_inbox / "a.jpg"
    src.write_bytes(b"photo")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Ledger, "record", boom)
    r = collect(cfg)

    assert src.read_bytes() == b"photo"
    assert r.failed == ["iCloud:a.jpg"]


def test_same_content_again_only_removes_source(cfg):
    (cfg.icloud_inbox / "a.m4a").write_bytes(b"same")
    collect(cfg)
    # 衝突副本、或從另一個入口再送一次同樣內容
    again = cfg.onedrive_inbox / "a 2.m4a"
    again.write_bytes(b"same")

    r = collect(cfg)

    assert not again.exists()
    assert r.duplicates == ["OneDrive:a 2.m4a"]
    assert r.moved == []
    assert _pending_files(cfg) == ["a.m4a", "a.m4a.feeder.json"]
    assert _ledger_count(cfg) == 1


def test_missing_inbox_alerts_but_other_inboxes_still_run(cfg):
    cfg.onedrive_inbox.rmdir()
    (cfg.icloud_inbox / "x.pdf").write_bytes(b"pdf")

    r = collect(cfg)

    assert not r.ok
    assert any("OneDrive 收件匣不存在" in a for a in r.alerts)
    assert _pending_files(cfg) == ["x.pdf", "x.pdf.feeder.json"]
    lines = cfg.alerts_path.read_text(encoding="utf-8").splitlines()
    assert any("OneDrive 收件匣不存在" in json.loads(x)["訊息"] for x in lines)


def test_system_and_temp_files_are_ignored(cfg):
    names = [".DS_Store", "Icon\r", "~$報告.docx", "下載中.tmp", ".849C9593"]
    if sys.platform == "win32":
        names.remove("Icon\r")   # 檔名不能含 \r(那是 macOS 資料夾自訂圖示的檔)
    for name in names:
        (cfg.onedrive_inbox / name).write_bytes(b"x")

    r = collect(cfg)

    assert r.moved == []
    assert len(list(cfg.onedrive_inbox.iterdir())) == len(names)


def test_pair_with_same_stem_moves_together_with_same_suffix(cfg):
    cfg.pending_dir.mkdir(parents=True)
    (cfg.pending_dir / "t_錄音.m4a").write_bytes(b"older")
    (cfg.icloud_inbox / "t_錄音.m4a").write_bytes(b"audio")
    (cfg.icloud_inbox / "t_錄音.json").write_text('{"補述": "x"}', encoding="utf-8")

    collect(cfg)

    names = _pending_files(cfg)
    assert "t_錄音_2.m4a" in names and "t_錄音_2.json" in names
    assert (cfg.pending_dir / "t_錄音.m4a").read_bytes() == b"older"


def test_file_still_changing_is_left_for_next_round(cfg, monkeypatch):
    src = cfg.icloud_inbox / "growing.m4a"
    src.write_bytes(b"part")
    monkeypatch.setattr(collect_mod.time, "sleep", lambda s: src.write_bytes(b"part-more"))

    r = collect(replace(cfg, stable_wait=1))

    assert src.exists()
    assert r.skipped_unstable == ["growing.m4a"]
    assert _ledger_count(cfg) == 0


def test_cloud_placeholder_is_not_taken(cfg, monkeypatch):
    src = cfg.onedrive_inbox / "只有佔位.md"
    src.write_text("", encoding="utf-8")
    monkeypatch.setattr(inboxes, "is_dataless", lambda p: p == src)

    r = collect(cfg)

    assert src.exists()
    assert r.moved == []


def test_files_in_subfolders_are_taken_with_relative_path(cfg):
    sub = cfg.icloud_inbox / "會議"
    sub.mkdir()
    (sub / "白板.jpg").write_bytes(b"jpg")

    collect(cfg)

    side = json.loads((cfg.pending_dir / "白板.jpg.feeder.json").read_text(encoding="utf-8"))
    assert side["原路徑"] == "會議/白板.jpg"
    assert sub.is_dir()  # 只刪檔、不刪使用者的資料夾


def test_second_run_exits_when_locked(cfg):
    src = cfg.icloud_inbox / "a.m4a"
    src.write_bytes(b"a")
    with run_lock(cfg.lock_path) as got:
        assert got
        r = collect(cfg)
    assert r.locked
    assert src.exists()


def test_copy_never_overwrites_existing_file(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"new")
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "a.txt").write_bytes(b"old")
    with pytest.raises(FileExistsError):
        mover.copy_verified(src, dest, "a.txt", mover.sha256_of(src))
    assert (dest / "a.txt").read_bytes() == b"old"
    assert sorted(p.name for p in dest.iterdir()) == ["a.txt"]


def test_unexpected_error_in_one_inbox_does_not_stop_others(cfg, monkeypatch):
    (cfg.icloud_inbox / "a.m4a").write_bytes(b"a")
    (cfg.onedrive_inbox / "b.md").write_bytes(b"b")

    def boom(p):
        if "icloud" in str(p):
            raise RuntimeError("意外")
        return False

    monkeypatch.setattr(inboxes, "is_dataless", boom)
    r = collect(cfg)

    assert any("iCloud 發生預期外的錯誤" in a for a in r.alerts)
    assert (cfg.icloud_inbox / "a.m4a").exists()
    assert _pending_files(cfg) == ["b.md", "b.md.feeder.json"]


def test_file_deleted_during_listing_is_skipped(cfg, monkeypatch):
    gone = cfg.icloud_inbox / "gone.m4a"
    gone.write_bytes(b"x")
    (cfg.icloud_inbox / "stay.m4a").write_bytes(b"y")
    real = inboxes.is_dataless

    def vanish(p):
        if p == gone:
            gone.unlink()
        return real(p)

    monkeypatch.setattr(inboxes, "is_dataless", vanish)
    r = collect(cfg)

    assert r.ok, r.alerts
    assert _pending_files(cfg) == ["stay.m4a", "stay.m4a.feeder.json"]


# --- 既有原件索引(Raw_Sources／FRaw_Sources 已有的檔不再收一次) ------------------

def _with_raw(cfg, tmp_path):
    raw, fraw = tmp_path / "Raw_Sources", tmp_path / "FRaw_Sources"
    (raw / "健康生活").mkdir(parents=True)
    (fraw / "會議與月報").mkdir(parents=True)
    return replace(cfg, raw_roots=(raw, fraw)), raw, fraw


def test_content_already_in_raw_sources_is_duplicate(cfg, tmp_path):
    c, raw, fraw = _with_raw(cfg, tmp_path)
    (fraw / "會議與月報" / "月報.pdf").write_bytes(b"monthly")
    src = c.icloud_inbox / "月報 2.pdf"
    src.write_bytes(b"monthly")

    r = collect(c)

    assert r.duplicates == ["iCloud:月報 2.pdf"] and r.moved == []
    assert not src.exists()


def test_pending_and_discard_dirs_are_not_indexed(cfg, tmp_path):
    """_待處理/ 裡的檔還沒攝入,不可拿來當「已經有了」的依據(否則收到的檔會被自己判成重複)。"""
    c, raw, fraw = _with_raw(cfg, tmp_path)
    c = replace(c, pending_dir=raw / "_待處理")
    (raw / "_待處理").mkdir()
    (raw / "_待處理" / "a.m4a").write_bytes(b"pending")
    (raw / "_捨棄候選").mkdir()
    (raw / "_捨棄候選" / "b.m4a").write_bytes(b"discard")
    (c.icloud_inbox / "a2.m4a").write_bytes(b"pending")
    (c.icloud_inbox / "b2.m4a").write_bytes(b"discard")

    r = collect(c)

    assert sorted(Path(p).name for p in r.moved) == ["a2.m4a", "b2.m4a"]


def test_dot_dirs_and_files_are_not_indexed(cfg, tmp_path):
    """.stversions/ 裡的舊版、同步中的 .syncthing.*.tmp 不是原件:算進索引的話,同內容再送來
    會被判成重複、只清來源,唯一的副本只剩藏起來的 .stversions/。"""
    c, raw, fraw = _with_raw(cfg, tmp_path)
    (fraw / ".stversions" / "會議").mkdir(parents=True)
    (fraw / ".stversions" / "會議" / "old.pdf").write_bytes(b"only-in-versions")
    (raw / "健康生活" / ".syncthing.x.pdf.tmp").write_bytes(b"in-transfer")
    (c.icloud_inbox / "a.pdf").write_bytes(b"only-in-versions")
    (c.icloud_inbox / "b.pdf").write_bytes(b"in-transfer")

    r = collect(c)

    assert sorted(Path(p).name for p in r.moved) == ["a.pdf", "b.pdf"]


def test_raw_index_follows_changes(cfg, tmp_path):
    c, raw, fraw = _with_raw(cfg, tmp_path)
    f = raw / "健康生活" / "x.md"
    f.write_bytes(b"v1")
    with Ledger(c.ledger_path) as led:
        assert led.refresh_raw_index(c.raw_roots, c.raw_skip_dirs) == (1, 0)
        assert led.refresh_raw_index(c.raw_roots, c.raw_skip_dirs) == (0, 0)  # 沒變就不重算
        f.write_bytes(b"version-2")
        assert led.refresh_raw_index(c.raw_roots, c.raw_skip_dirs) == (1, 0)
        assert led.raw_lookup(mover.sha256_of(f)) == str(f)
        f.unlink()
        assert led.refresh_raw_index(c.raw_roots, c.raw_skip_dirs) == (0, 1)
        assert led.raw_shas_under(raw) == set()


def test_raw_index_prefix_uses_the_platform_separator():
    """索引存的是 os.walk 組的路徑:Windows 是 `\\`。前綴寫死 `/` 的話 Windows 上原件少一份也不會 STOP
    (2026-10-19 Windows 實測)。Mac 上也測得到:分隔字元當參數換掉。"""
    from pathlib import PureWindowsPath

    from wiki_feeder.ledger import _dir_prefix
    assert _dir_prefix(PureWindowsPath(r"C:\LLMWIKI\Raw_Sources"), "\\") == "C:\\LLMWIKI\\Raw_Sources\\"
    assert _dir_prefix("/Users/me/FRaw_Sources/", "/") == "/Users/me/FRaw_Sources/"


def test_refreshing_one_root_keeps_the_other_roots_index(cfg, tmp_path):
    c, raw, fraw = _with_raw(cfg, tmp_path)
    (raw / "健康生活" / "a.md").write_bytes(b"a")
    (fraw / "會議與月報" / "b.pdf").write_bytes(b"b")
    with Ledger(c.ledger_path) as led:
        assert led.refresh_raw_index((raw, fraw), c.raw_skip_dirs) == (2, 0)
        assert led.refresh_raw_index((fraw,), c.raw_skip_dirs) == (0, 0)
        assert led.refresh_raw_index((raw, fraw), c.raw_skip_dirs) == (0, 0)   # 不必重算


def test_same_alert_is_reported_once_a_day(cfg):
    """launchd 每分鐘一輪:收件匣讀不到這類持續性問題,同一則 24 小時內只報一次。"""
    import time as _t

    cfg.onedrive_inbox.rmdir()
    r1 = collect(cfg)
    r2 = collect(cfg)
    assert len(r1.new_alerts) == 1 and r2.new_alerts == []
    assert len(cfg.alerts_path.read_text(encoding="utf-8").splitlines()) == 1

    seen = cfg.state_dir / "alerts_seen.json"
    data = json.loads(seen.read_text(encoding="utf-8"))
    seen.write_text(json.dumps({k: _t.time() - 25 * 3600 for k in data}), encoding="utf-8")
    assert len(collect(cfg).new_alerts) == 1             # 隔天還沒修好,再報一次


def test_network_down_is_not_an_alert(cfg):
    """使用者 2026-10-20:「從家裡帶筆電到公司,連不上網路正常」——連一天一則都不要。
    實際出現過的說法(FUTURES 走 ssh、FWIKI 走 https、寄信、網路切換中、公司擋 22 埠)都不進摘要。"""
    from wiki_feeder.collect import _alert

    futures = ("FUTURES 取件準備失敗:git ls-remote origin refs/heads/main 失敗:ssh: {}\n"
               "fatal: Could not read from remote repository.")
    for msg in [
        "這輪不攝入,待攝入的都不算失敗:git pull --ff-only -q origin master(FWIKI)失敗:fatal: unable to "
        "access 'https://github.com/me/FWIKI.git/': Failed to connect to github.com port 443 "
        "after 75002 ms: Couldn't connect to server",
        "FWIKI 推送 3 次都被拒,commit 留在本機下一輪再推:fatal: unable to access 'https://github.com/me/FWIKI.git/': "
        "Could not resolve host: github.com",
        futures.format("Could not resolve hostname github.com: nodename nor servname provided, or not known"),
        futures.format("connect to host github.com port 22: Operation timed out"),
        futures.format("connect to host github.com port 22: Undefined error: 0"),
        futures.format("connect to host github.com port 22: Can't assign requested address"),
        "FUTURES 取件準備失敗:Connection to 20.27.177.113 port 22 timed out",
        "FUTURES 取件準備失敗:Connection reset by 20.27.177.113 port 22",
        "FUTURES 取件準備失敗:Timeout, server github.com not responding.",
        "寄信失敗:[Errno 8] nodename nor servname provided, or not known",
        "寄信失敗:Connection unexpectedly closed: The read operation timed out",
    ]:
        assert not _alert(cfg, msg), msg
    assert not cfg.alerts_path.exists() or cfg.alerts_path.read_text(encoding="utf-8") == ""


def test_real_problems_are_still_alerts(cfg):
    """金鑰被撤、權限不夠、轉寫逾時、STOP 是要人處理的事,不可被當成斷網吞掉。"""
    from wiki_feeder.collect import _alert

    assert _alert(cfg, "FUTURES 取件準備失敗:git@github.com: Permission denied (publickey).")
    assert _alert(cfg, "會議.m4a 轉寫失敗:doc2md 超過 3600 秒沒跑完")
    assert _alert(cfg, "x.pdf 攝入停止(這筆與之後的攝入、補推都停住,等人檢查):STOP:攝入後 FWIKI 留有沒 commit 的修改;"
                       "推送時 Could not resolve host: github.com")


def test_one_off_unreadable_inbox_is_not_alerted_until_it_persists(cfg):
    """實測踩過:OneDrive 同步中有一輪回 Operation not permitted,前後都正常——不該叫人去查權限。"""
    c = replace(cfg, unavailable_alert_after=3)
    c.onedrive_inbox.rmdir()
    assert collect(c).alerts == []
    assert collect(c).alerts == []
    assert len(collect(c).alerts) == 1                    # 連續第 3 輪才報

    c.onedrive_inbox.mkdir()
    collect(c)                                            # 恢復一輪就歸零
    c.onedrive_inbox.rmdir()
    assert collect(c).alerts == []


def test_interrupted_listing_is_not_alerted_until_it_persists(cfg, monkeypatch):
    """實測踩過(2026-10-25):OneDrive 同步中 listdir 回 EINTR 一輪、下一輪就好——不該寄「預期外的錯誤」。"""
    c = replace(cfg, unavailable_alert_after=3)
    real = inboxes.os.listdir

    def eintr(p="."):
        if Path(p) == c.onedrive_inbox:
            raise InterruptedError(4, "Interrupted system call", str(p))
        return real(p)

    monkeypatch.setattr(inboxes.os, "listdir", eintr)
    assert collect(c).alerts == []
    assert collect(c).alerts == []
    alerts = collect(c).alerts                            # 一直讀不到,連續第 3 輪照樣報
    assert len(alerts) == 1 and "OneDrive 收件匣暫時讀不到" in alerts[0]
