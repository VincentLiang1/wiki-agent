"""FUTURES 入口:用 tmp_path 裡的假 bare remote,絕不碰真的 FUTURES。"""
from __future__ import annotations

import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder.collect import collect, last_net_down, net_down_path
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


def test_transient_fetch_failure_after_rejected_push_is_retried(cfg, futures_cfg, fake_futures, monkeypatch, backoff):
    """推送被拒後跟上遠端,fetch 一時失敗(斷網、鎖檔):等一下重試、照常推上去,不是放棄這輪。"""
    import subprocess

    from wiki_feeder import inboxes

    fake_futures.write("PROCESS/first.txt", "第一個")
    fake_futures.push()
    real_finish, real_run = FuturesInbox.finish, inboxes.run_net
    failed = []

    def finish_with_race(self):
        fake_futures.write("PROCESS/late.txt", "晚到的")
        fake_futures.push("company pushes during our run")
        real_finish(self)

    def fetch_fails_once(cmd, *a, **k):
        if "fetch" in cmd and not failed:
            failed.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "fatal: Cannot rebase onto multiple branches.")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(FuturesInbox, "finish", finish_with_race)
    monkeypatch.setattr(inboxes, "run_net", fetch_fails_once)
    r = _run(cfg, futures_cfg)

    assert r.ok, r.alerts
    assert failed and backoff == [5]
    files = fake_futures.remote_files()
    assert "PROCESS/late.txt" in files and "PROCESS/first.txt" not in files


def test_new_remote_files_are_fetched_without_pull(cfg, futures_cfg, fake_futures, monkeypatch):
    """遠端有新檔:fetch + merge --ff-only origin/<分支> 跟上,不用 pull(照 FETCH_HEAD 合併,同時有別的 fetch 就失敗)。"""
    from wiki_feeder import inboxes

    _run(cfg, futures_cfg)                       # 先建好本機副本
    fake_futures.write("PROCESS/new.txt", "新來的")
    fake_futures.push()
    cmds = []
    real_run = inboxes.run_net

    def record(cmd, *a, **k):
        cmds.append(cmd)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(inboxes, "run_net", record)
    r = _run(cfg, futures_cfg)

    assert r.ok, r.alerts
    assert [Path(p).name for p in r.moved] == ["new.txt"]
    assert not [c for c in cmds if "pull" in c]


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


# --- publickey 被拒:先查證是不是 GitHub 那端不穩(2026-11-04) ---

DENIED = "git@github.com: Permission denied (publickey)."
TIMED_OUT = "ssh: connect to host github.com port 22: Operation timed out"


def _state(cfg, name):
    return json.loads((cfg.state_dir / name).read_text(encoding="utf-8"))


def _publickey_env(cfg, futures_cfg, monkeypatch, probe, status):
    """ls-remote 一律回 publickey;每次 ssh 連試問 probe(第幾輪, 這輪第幾次):True 認得金鑰／False 被拒／
    None 沒有結論(逾時);githubstatus 回 status(第幾輪)。回傳 (設定, 跑一輪收件, 每次連試的(輪, 次))。"""
    import subprocess

    from wiki_feeder import inboxes

    real_run = inboxes.run_net
    tries, at = [], {"round": 0, "try": 0}

    def ls_remote_denied(cmd, *a, **k):
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(cmd, 128, "", DENIED + "\r\nfatal: Could not read from remote repository.")
        return real_run(cmd, *a, **k)

    def ssh_once(target):
        assert target == "git@github.com"
        at["try"] += 1
        tries.append((at["round"], at["try"]))
        got = probe(at["round"], at["try"])
        return got, ("" if got else DENIED if got is False else TIMED_OUT)

    monkeypatch.setattr(inboxes, "run_net", ls_remote_denied)
    monkeypatch.setattr(inboxes, "ssh_target", lambda remote: "git@github.com")
    monkeypatch.setattr(inboxes, "ssh_once", ssh_once)
    monkeypatch.setattr(inboxes, "git_ops_status", lambda url: status(at["round"]))
    c = replace(cfg, icloud_inbox=None, onedrive_inbox=None, unavailable_alert_after=3,
                futures=replace(futures_cfg, status_url="https://status.invalid/summary.json"))

    def one_round():
        at["round"] += 1
        at["try"] = 0
        return collect(c)

    return c, one_round, tries


def _watchdog_inbox(c):
    """看門狗看到的 inbox 問題的鍵。看門狗只在 Mac(detect 會 import fcntl):Windows 回 None、不驗,收件端的判斷照驗。"""
    if sys.platform == "win32":
        return None
    from wiki_feeder.watchdog import detect
    return [p.key for p in detect(c, agents_check=lambda: [], resources_too=False) if p.kind == "inbox"]


def _publickey_rounds(cfg, futures_cfg, monkeypatch, ssh_results, status, rounds=5):
    """ssh 連試照 ssh_results 跨輪輪流回(空的 = 一直被拒),githubstatus 一律回 status;跑 rounds 輪收件,
    回傳 (最後一輪的 Report, 看門狗看到的 inbox 問題, 每次連試的紀錄)。"""
    it = itertools.cycle(ssh_results or [False])
    c, one_round, tries = _publickey_env(cfg, futures_cfg, monkeypatch, lambda _r, _t: next(it), lambda _round: status)
    for _ in range(rounds):
        r = one_round()
    return r, _watchdog_inbox(c), tries


def test_publickey_but_ssh_sometimes_works_is_github_not_the_key(cfg, futures_cfg, monkeypatch):
    """2026-11-04:GitHub 出事,ls-remote 連 9 輪 publickey,看門狗寄 🛑「GitHub 拒絕了部署金鑰」叫人去核對——
    其實金鑰在、指紋對,同一把金鑰 ssh 6 次成功 2 次。ssh 有一次成功就是 GitHub 不穩:不列進摘要、不交給修理。"""
    r, found, tries = _publickey_rounds(cfg, futures_cfg, monkeypatch, [False, False, True], "operational")
    assert not r.alerts and not r.new_alerts
    assert found in ([], None)
    assert len(tries) == 5 * 3                              # 每輪試到第一次成功就停
    assert _state(cfg, "inbox_offline.json") == ["FUTURES"]
    assert not net_down_path(cfg).exists()                  # 本機網路是通的:iCloud 探針不該重新計時
    assert not cfg.alerts_path.exists()


def test_publickey_while_githubstatus_degraded_is_github_not_the_key(cfg, futures_cfg, monkeypatch):
    """ssh 每次都被拒、但 githubstatus 的 Git Operations 不是 operational:也是 GitHub 那端,不找人。"""
    r, found, tries = _publickey_rounds(cfg, futures_cfg, monkeypatch, [], "degraded_performance")
    assert not r.alerts and not r.new_alerts
    assert found in ([], None)
    assert len(tries) == 5 * futures_cfg.ssh_probe_tries


@pytest.mark.parametrize("status", ["operational", None])
def test_publickey_with_every_ssh_denied_and_github_fine_still_escalates(cfg, futures_cfg, monkeypatch, status):
    """ssh 每次都被拒、githubstatus 正常(或讀不到):金鑰真的被拒,照舊連續 3 輪後警示、交給修理;警示裡寫明查證了
    什麼,修理的 claude 才分得出這是驗證過的(repair.PROMPT 第 9 條)。讀不讀得到 githubstatus 警示都同一句。"""
    r, found, _ = _publickey_rounds(cfg, futures_cfg, monkeypatch, [], status)
    assert len(r.alerts) == 1 and "publickey" in r.alerts[0]
    assert f"已查證:ssh 連試 {futures_cfg.ssh_probe_tries} 次都被拒、githubstatus 沒有公告 Git Operations 出事" \
        in r.alerts[0]
    assert found in (None, ["inbox:FUTURES"])


def test_github_side_round_resets_the_count_so_one_unlucky_round_is_not_an_alert(cfg, futures_cfg, monkeypatch):
    """GitHub 時好時壞:每輪的查證各看各的,總會碰上一輪 6 次全被拒。查證是 GitHub 不穩的那一輪把連續次數歸零,
    要連續 3 輪都真的被拒才警示——不歸零的話,事故前幾輪累積的次數讓單獨一輪當場越過門檻,寄出「已查證:
    都被拒」,正是第 9 條准修理說是金鑰的那句(2026-11-04 檢討:照當天的成功率,一小時內幾乎一定碰上)。"""
    ssh_ok = {1: False, 2: False, 3: True, 4: False, 5: False, 6: False}   # 第幾輪的 ssh 有沒有成功
    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: ssh_ok[r],
                                     lambda r: "operational")
    reports = [one_round() for _ in range(5)]
    assert [len(r.alerts) for r in reports] == [0, 0, 0, 0, 0]
    assert _state(cfg, "inbox_streak.json") == {"FUTURES": 2}
    assert _watchdog_inbox(c) in ([], None)
    last = one_round()                                       # 連續第 3 輪真的被拒:照舊警示
    assert len(last.new_alerts) == 1 and "已查證" in last.new_alerts[0]
    assert _watchdog_inbox(c) in (["inbox:FUTURES"], None)


def test_key_that_worked_minutes_ago_is_not_blamed(cfg, futures_cfg, monkeypatch):
    """上次連上遠端不到 github_hold:金鑰剛剛還能用,publickey 先當成 GitHub 不穩、不連試(2026-11-04 那 9 輪被拒,
    前後幾分鐘都有連上的輪)。超過 github_hold 才連試,金鑰真的被撤照樣在連續 3 輪後報出來。"""
    import os
    import time

    stamp = cfg.state_dir / "futures_last_check"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    c, one_round, tries = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: False, lambda r: "operational")
    reports = [one_round() for _ in range(4)]
    assert not any(r.alerts for r in reports) and tries == []
    assert _state(cfg, "inbox_offline.json") == ["FUTURES"]
    assert _watchdog_inbox(c) in ([], None)

    old = time.time() - futures_cfg.github_hold - 1
    os.utime(stamp, (old, old))
    reports = [one_round() for _ in range(3)]
    assert [len(r.alerts) for r in reports] == [0, 0, 1]
    assert len(tries) == 3 * futures_cfg.ssh_probe_tries


def test_ssh_probe_without_an_answer_is_not_a_denial(cfg, futures_cfg, monkeypatch):
    """ls-remote 回 publickey,接著 ssh 連試逾時(沒拿到 GitHub 的答覆):那不是被拒的證據,不可寫成「都被拒」;
    停下不再試、比照連不上網路——ssh 的原話是斷網的說法,照斷網記(iCloud 探針才不會誤判卡住)。"""
    c, one_round, tries = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: None, lambda r: "operational")
    reports = [one_round() for _ in range(4)]
    assert not any(r.alerts for r in reports)
    assert len(tries) == 4                                   # 每輪第一次沒結論就停
    assert _state(cfg, "inbox_offline.json") == ["FUTURES"]
    assert last_net_down(cfg) > 0
    assert _watchdog_inbox(c) in ([], None)


def test_net_down_rounds_do_not_count_toward_the_alert(cfg, futures_cfg, monkeypatch):
    """斷網那幾輪不累積次數:斷網兩輪、接著一輪 ssh 全被拒,不可當場越過門檻寄「已查證:都被拒」——跟 GitHub
    不穩那輪歸零同一個道理(2026-11-05 檢討);之後連續 3 輪都真的被拒照樣警示。"""
    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: None if r <= 2 else False,
                                     lambda r: "operational")
    reports = [one_round() for _ in range(5)]
    assert [len(r.alerts) for r in reports] == [0, 0, 0, 0, 1]


def test_ssh_without_an_answer_is_net_down_whatever_ssh_says(cfg, futures_cfg, monkeypatch):
    """ssh 沒有結論就記斷網,不看 ssh 印了什麼:它的說法千奇百怪(kex_exchange_identification…),認不得的話
    net_down.json 沒記,iCloud 探針會把這段斷網誤判成 iCloud 卡住。"""
    from wiki_feeder import inboxes

    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: None, lambda r: "operational")
    monkeypatch.setattr(inboxes, "ssh_once",
                        lambda target: (None, "kex_exchange_identification: Connection closed by remote host"))
    r = one_round()
    assert not r.alerts and last_net_down(cfg) > 0
    assert _state(cfg, "inbox_offline.json") == ["FUTURES"]


def test_probe_that_crashes_falls_back_to_the_normal_alert(cfg, futures_cfg, monkeypatch):
    """查證本身出錯(例如找不到 ssh):當成沒查到,照舊連續 3 輪才警示、警示照樣是 publickey 那則;不可讓例外
    蓋掉原本的錯誤、第一輪就以「預期外的錯誤」報出來,上一輪留下的 inbox_offline.json 也要照常更新。"""
    def boom(_round, _try):
        raise FileNotFoundError(2, "No such file or directory", "ssh")

    (cfg.state_dir / "inbox_offline.json").parent.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "inbox_offline.json").write_text('["FUTURES"]', encoding="utf-8")   # 上一輪是 GitHub 不穩
    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, boom, lambda r: "operational")
    reports = [one_round() for _ in range(3)]
    assert [len(r.alerts) for r in reports] == [0, 0, 1]
    assert "publickey" in reports[-1].alerts[0] and "沒能查證" in reports[-1].alerts[0]
    assert _state(cfg, "inbox_offline.json") == []


def test_escalation_text_does_not_depend_on_githubstatus_being_readable(cfg, futures_cfg, monkeypatch):
    """金鑰真的被撤:githubstatus 這輪讀得到、下輪讀不到,警示全文都一樣——警示以全文去重(§7.2),
    文字一變就是新的一則、一天多寄一封。讀到什麼只寫 log。"""
    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: False,
                                     lambda r: "operational" if r % 2 else None)
    reports = [one_round() for _ in range(6)]
    assert [len(r.alerts) for r in reports] == [0, 0, 1, 1, 1, 1]
    assert len({r.alerts[0] for r in reports[2:]}) == 1
    assert sum(len(r.new_alerts) for r in reports) == 1


def test_probe_goes_where_git_actually_goes(cfg, futures_cfg, monkeypatch, fake_futures):
    """查證連的是 clone 實際的 origin,不是設定裡的 remote:clone 之後設定改了(換別名、換金鑰)而舊的被撤,
    照設定去連會連上新的,永遠被當成 GitHub 不穩、不警示。"""
    from wiki_feeder import inboxes

    c, one_round, _ = _publickey_env(cfg, futures_cfg, monkeypatch, lambda r, t: False, lambda r: "operational")
    seen = []
    monkeypatch.setattr(inboxes, "ssh_target", lambda remote: seen.append(remote) or "git@github.com")
    one_round()                                              # 第一輪照設定 clone
    collect(replace(c, futures=replace(c.futures, remote="git@github.com:owner/renamed.git")))
    assert seen == [fake_futures.remote.as_uri()] * 2


def test_repair_prompt_knows_how_to_read_the_check(cfg, futures_cfg, monkeypatch):
    """修理的 claude 不能跑 ssh、不能連外部網站:提示要它照警示裡「已查證」那句判斷。那句由 checked_sentence 產生,
    警示與提示用同一個函式、同一個語系:字不同步的話它找不到那句,金鑰真的被撤也只會寫「沒驗證到」。"""
    import subprocess

    from wiki_feeder import inboxes, repair

    monkeypatch.setattr(inboxes, "ssh_once", lambda target: (False, DENIED))
    monkeypatch.setattr(inboxes, "git_ops_status", lambda url: "operational")
    offline, why = inboxes.github_side(futures_cfg, "git@github.com:owner/repo.git")
    n = futures_cfg.ssh_probe_tries
    assert offline is None and why == inboxes.checked_sentence(inboxes.L(inboxes.DENIED_ALL, n=n))

    seen = []

    def claude(cmd, *a, **k):
        seen.append(k.get("input", ""))
        return subprocess.CompletedProcess(cmd, 0, "{}", "")
    monkeypatch.setattr(repair, "run_net", claude)
    monkeypatch.setattr(repair, "facts", lambda c, problems: "")
    repair.run_agent(cfg, [])
    assert "沒驗證到" in seen[0]
    assert inboxes.checked_sentence(inboxes.L(inboxes.DENIED_ALL, n="N")) in seen[0]


@pytest.mark.parametrize("code,out,want", [
    (1, "Hi owner/repo! You've successfully authenticated, but GitHub does not provide shell access.\n", True),
    (255, DENIED + "\r\n", False),
    (255, TIMED_OUT + "\r\n", None),
    (255, "kex_exchange_identification: Connection closed by remote host\r\n", None),
    (124, "ssh -o BatchMode=yes -o 逾時 30 秒,已中止", None),
])
def test_ssh_once_reads_what_github_says_not_the_exit_code(monkeypatch, code, out, want):
    """GitHub 認得金鑰時 ssh -T 的結束碼是 1(800f6e4 踩到的坑):看「successfully authenticated」字樣;只有印著
    publickey 才算被拒,逾時、斷線都是沒有結論。真的 ssh_once 只有這裡跑得到(其他測試都換成假的)。"""
    import subprocess

    from wiki_feeder import inboxes

    calls = []

    def fake_run(cmd, timeout, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, "", out)

    monkeypatch.setattr(inboxes, "run_net", fake_run)
    got, last = inboxes.ssh_once("git@github.com")
    assert got is want
    assert calls[0][0] == "ssh" and calls[0][-2:] == ["-T", "git@github.com"] and "BatchMode=yes" in calls[0]
    assert last == ("" if want else out.strip().splitlines()[-1].strip())


def test_ssh_target_parses_remote_forms():
    from wiki_feeder.inboxes import ssh_target

    assert ssh_target("git@github.com:owner/repo.git") == "git@github.com"
    assert ssh_target("github.com:owner/repo.git") == "github.com"                  # 使用者寫在 ~/.ssh/config
    assert ssh_target("ssh://git@github.com/owner/repo.git") == "ssh://git@github.com"
    assert ssh_target("ssh://git@github.com:443/owner/repo.git") == "ssh://git@github.com:443"   # 埠號不能丟
    assert ssh_target("git+ssh://git@github.com/owner/repo.git") == "ssh://git@github.com"
    assert ssh_target("file:///tmp/x/FUTURES.git") is None
    assert ssh_target("https://github.com/owner/repo.git") is None
    assert ssh_target("C:/x/FUTURES.git") is None
    assert ssh_target("/tmp/x/FUTURES.git") is None


def test_git_ops_status_reads_the_component(tmp_path):
    """githubstatus summary.json 的格式:components[].name／status;讀不到、找不到、格式不對一律 None
    (格式不對不可變成「是 GitHub 那端」:金鑰真的被撤時會一直不報)。"""
    from wiki_feeder.inboxes import git_ops_status

    f = tmp_path / "summary.json"
    f.write_text(json.dumps({"components": [{"name": "API Requests", "status": "operational"},
                                            {"name": "Git Operations", "status": "degraded_performance"}]}))
    assert git_ops_status(f.as_uri()) == "degraded_performance"
    f.write_text(json.dumps({"components": []}))
    assert git_ops_status(f.as_uri()) is None
    assert git_ops_status((tmp_path / "沒有.json").as_uri()) is None
    for comp in ({"name": "Git Operations", "status": None}, {"name": "Git Operations"},
                 {"name": "Git Operations", "status": ""}, {"name": "Git Operations", "status": {"x": 1}}):
        f.write_text(json.dumps({"components": [comp]}))
        assert git_ops_status(f.as_uri()) is None, comp
