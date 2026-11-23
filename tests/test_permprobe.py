"""換版自動實測(permprobe,spec §6.6):判定三態、跟攝入同一組旗標、看門狗只在換版時跑、失守才寄信。"""
import dataclasses
import json
import sys
from pathlib import Path

import pytest

from wiki_feeder import ingest, permprobe, repair, selfcheck, watchdog

FAKE = Path(__file__).parent / "fake_probe_claude.py"


@pytest.fixture
def pcfg(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PROBE_ARGS", str(tmp_path / "probe-args.json"))
    return dataclasses.replace(cfg, claude_cmd=(sys.executable, str(FAKE)), permprobe=True)


def _run(pcfg, monkeypatch, mode):
    monkeypatch.setenv("FAKE_PROBE_MODE", mode)
    return permprobe.run(pcfg)


def _verdicts(rep):
    return {t.key: v for t, v in rep.rows}


def test_all_as_expected_passes(pcfg, monkeypatch):
    rep = _run(pcfg, monkeypatch, "ok")
    assert rep.status == permprobe.PASS, rep.text()
    assert len(rep.rows) == len(permprobe.TASKS)


def test_a_write_outside_is_a_breach(pcfg, monkeypatch):
    """該擋的真的做成了(檔案寫進去):不管它回報什麼,看檔案系統就是失守。"""
    rep = _run(pcfg, monkeypatch, "breach")
    assert rep.status == permprobe.FAIL
    assert _verdicts(rep)["write_other"] == "失守"


def test_ingest_tools_being_blocked_is_also_a_difference(pcfg, monkeypatch):
    """另一個方向:攝入要用的被擋下,攝入會每筆失敗,也要寄信。"""
    rep = _run(pcfg, monkeypatch, "blocked")
    assert rep.status == permprobe.FAIL
    assert _verdicts(rep)["write_work"] == "被擋"


def test_not_trying_is_not_counted_as_blocked(pcfg, monkeypatch):
    """haiku 沒試那幾項:檔案當然沒變,但不可算成擋下——那樣它偷懶就永遠綠燈。"""
    rep = _run(pcfg, monkeypatch, "lazy")
    assert rep.status == permprobe.UNKNOWN
    assert _verdicts(rep)["write_realwiki"] == permprobe.UNSURE


def test_a_failure_that_is_not_a_permission_block_is_not_a_difference(pcfg, monkeypatch):
    """該放行的呼叫失敗了、但不是權限擋的(沒列在 permission_denials):判定不了,不可一次定案寄 🛑。"""
    rep = _run(pcfg, monkeypatch, "otherfail")
    assert rep.status == permprobe.UNKNOWN
    assert _verdicts(rep)["write_work"] == permprobe.UNSURE


def test_passphrase_missing_means_the_setup_did_not_load(pcfg, monkeypatch):
    """CLAUDE.md 的密語沒說出來:假庫的設定沒載入(例如放到 /tmp 底下),結果不算數。"""
    rep = _run(pcfg, monkeypatch, "nopass")
    assert rep.status == permprobe.UNKNOWN


@pytest.mark.parametrize("mode", ["apidown", "silent"])
def test_api_down_or_crash_is_environment(pcfg, monkeypatch, mode):
    assert _run(pcfg, monkeypatch, mode).status == permprobe.ENV


def test_flags_are_the_ingest_ones(pcfg, monkeypatch, tmp_path):
    """旗標跟攝入同一支產生:改了攝入的權限,實測跟著測新的那組(另抄一份的話換版綠燈不代表攝入安全)。"""
    _run(pcfg, monkeypatch, "ok")
    args = json.loads((tmp_path / "probe-args.json").read_text(encoding="utf-8"))
    joined = " ".join(args)
    assert "--setting-sources user,project" in joined
    allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
    denied = args[args.index("--disallowedTools") + 1:]
    assert set(ingest.ALLOWED_TOOLS) <= set(allowed)
    assert "Write" not in allowed and "Edit" not in allowed          # Write／Edit 只列 --tools
    assert set(ingest.DISALLOWED_TOOLS + ingest.SETTINGS_DENY) <= set(denied)
    assert any("realwiki" in d for d in denied)                     # 真的個人庫那條禁止規則
    root = pcfg.state_dir / permprobe.PROBE_DIR
    assert args[args.index("--add-dir") + 1] == str(root / "stage")
    assert not str(root).startswith(("/tmp", "/private/tmp"))  # 放 /tmp 底下 CLAUDE.md 不載入


def test_setup_only_touches_its_own_folder(pcfg, tmp_path):
    keep = pcfg.state_dir / "ledger.sqlite3"
    keep.parent.mkdir(parents=True)
    keep.write_text("x")
    permprobe.setup(pcfg.state_dir / permprobe.PROBE_DIR)
    permprobe.setup(pcfg.state_dir / permprobe.PROBE_DIR)   # 第二次重建
    assert keep.read_text() == "x"


# -- 什麼時候跑 -----------------------------------------------------------------------

def _rep(status):
    return permprobe.Report(status, note=status)


def test_state_machine(pcfg):
    v, t0 = "2.0.0", 1_000_000.0
    assert permprobe.due(pcfg, v, t0)                                  # 沒有紀錄 = 要跑(第一次 deploy 補測現行版)
    assert permprobe.record(pcfg, v, _rep(permprobe.UNKNOWN), t0) == permprobe.UNKNOWN
    assert not permprobe.due(pcfg, v, t0 + 60)                         # 判定不了:一小時內不再試(不擋就每 3 分鐘花錢)
    assert permprobe.due(pcfg, v, t0 + permprobe.RETRY_GAP)
    assert permprobe.record(pcfg, v, _rep(permprobe.ENV), t0 + permprobe.RETRY_GAP) == permprobe.ENV
    t = t0 + 2 * permprobe.RETRY_GAP
    assert permprobe.record(pcfg, v, _rep(permprobe.UNKNOWN), t) == permprobe.UNKNOWN   # 連不上不算次數:這是第 2 次
    assert permprobe.record(pcfg, v, _rep(permprobe.UNKNOWN), t + permprobe.RETRY_GAP) == "giveup"
    assert not permprobe.due(pcfg, v, t + 99 * permprobe.RETRY_GAP)   # 放棄了就不再試
    assert permprobe.record(pcfg, "2.0.1", _rep(permprobe.PASS), t) == permprobe.PASS
    assert not permprobe.due(pcfg, "2.0.1", t + 99 * permprobe.RETRY_GAP)
    assert permprobe.record(pcfg, "2.0.2", _rep(permprobe.FAIL), t) == permprobe.FAIL
    assert not permprobe.due(pcfg, "2.0.2", t + 99 * permprobe.RETRY_GAP)


class Box:
    def __init__(self):
        self.mail, self.runs = [], []


def _deps(box, status, version="3.0.0", online=True):
    def run(cfg):
        box.runs.append(1)
        return _rep(status)
    return repair.Deps(online=lambda: online, mail=lambda c, s, b: box.mail.append((s, b)),
                       claude_version=lambda c: version, permprobe=run)


def test_watchdog_pass_only_logs(pcfg):
    box = Box()
    assert repair._check_permprobe(pcfg, _deps(box, permprobe.PASS), 1e6) == permprobe.PASS
    assert box.mail == []
    repair._check_permprobe(pcfg, _deps(box, permprobe.PASS), 1e6 + 9e5)
    assert len(box.runs) == 1                                          # 同一版不再跑


def test_watchdog_difference_mails_once(pcfg):
    box = Box()
    repair._check_permprobe(pcfg, _deps(box, permprobe.FAIL), 1e6)
    assert len(box.mail) == 1 and box.mail[0][0].startswith("🛑") and "3.0.0" in box.mail[0][0]
    assert "攝入照常在跑" in box.mail[0][1]
    repair._check_permprobe(pcfg, _deps(box, permprobe.FAIL), 1e6 + 9e5)
    assert len(box.runs) == 1 and len(box.mail) == 1
    repair._check_permprobe(pcfg, _deps(box, permprobe.PASS, version="3.0.1"), 1e6 + 9e5)   # 下一版照樣測
    assert len(box.runs) == 2


def test_watchdog_gives_up_after_tries(pcfg):
    box = Box()
    for i in range(permprobe.MAX_TRIES):
        repair._check_permprobe(pcfg, _deps(box, permprobe.UNKNOWN), 1e6 + i * permprobe.RETRY_GAP)
    assert len(box.runs) == permprobe.MAX_TRIES
    assert len(box.mail) == 1 and "判定不了" in box.mail[0][0]


def test_watchdog_off_for_friends_and_offline(pcfg):
    """朋友那台預設關(會花對方的錢);斷網不跑、不算次數。"""
    box = Box()
    repair._check_permprobe(dataclasses.replace(pcfg, permprobe=False), _deps(box, permprobe.FAIL), 1e6)
    repair._check_permprobe(pcfg, _deps(box, permprobe.FAIL, online=False), 1e6)
    repair._check_permprobe(pcfg, _deps(box, permprobe.FAIL, version=""), 1e6)   # 問不到版本
    assert box.runs == [] and box.mail == []


def test_selfcheck_says_it_is_automatic(pcfg, monkeypatch):
    monkeypatch.setattr(selfcheck, "CHECKS", {n: (lambda c: (True, "")) for n in selfcheck.ITEMS})
    monkeypatch.setenv("FAKE_PROBE_VERSION", "1.0.0")
    selfcheck.run(pcfg)
    monkeypatch.setenv("FAKE_PROBE_VERSION", "1.0.1")
    _, lines = selfcheck.run(pcfg)
    assert any("看門狗會自動重跑" in ln for ln in lines)


def test_watchdog_retries_the_mail_without_rerunning(pcfg):
    """失守的信寄不出去(SMTP 閃一下):這一版已定案、不再跑實測,但下一輪要用存下的結果再寄。"""
    box = Box()
    deps = _deps(box, permprobe.FAIL)

    def flaky(c, s, b):
        if not box.mail:
            box.mail.append("failed")
            raise OSError("smtp down")
        box.mail.append((s, b))
    deps.mail = flaky
    repair._check_permprobe(pcfg, deps, 1e6)
    repair._check_permprobe(pcfg, deps, 1e6 + 180)
    assert len(box.runs) == 1
    assert len(box.mail) == 2 and box.mail[1][0].startswith("🛑")
    repair._check_permprobe(pcfg, deps, 1e6 + 2 * 86400)   # 寄成功過就不再寄(不是一天一封)
    assert len(box.mail) == 2


def test_watchdog_probe_crash_is_throttled_and_eventually_mailed(pcfg):
    """實測自己出錯:當成判定不了記下,一小時內不重來,3 次後寄信。"""
    box = Box()

    def boom(cfg):
        box.runs.append(1)
        raise RuntimeError("setup failed")
    deps = _deps(box, permprobe.PASS)
    deps.permprobe = boom
    repair._check_permprobe(pcfg, deps, 1e6)
    repair._check_permprobe(pcfg, deps, 1e6 + 180)
    assert len(box.runs) == 1
    for i in (1, 2):
        repair._check_permprobe(pcfg, deps, 1e6 + i * permprobe.RETRY_GAP)
    assert len(box.runs) == permprobe.MAX_TRIES
    assert len(box.mail) == 1 and "RuntimeError" in box.mail[0][1]


# -- 失守就暫停攝入(使用者 2026-11-23)---------------------------------------------------

def _task(key):
    return next(t for t in permprobe.TASKS if t.key == key)


def _breach_deps(box, verdicts, version="3.0.0"):
    def run(cfg):
        box.runs.append(1)
        return permprobe.Report(permprobe.FAIL, [(_task(k), v) for k, v in verdicts.items()])
    return repair.Deps(online=lambda: True, mail=lambda c, s, b: box.mail.append((s, b)),
                       claude_version=lambda c: version, permprobe=run)


def _stop_kind(cfg):
    return json.loads(cfg.ingest_stop_path.read_text(encoding="utf-8"))["種類"]


def test_breach_pauses_ingest_until_resume(pcfg):
    """失守:寫停止檔(攝入、補推都停),信說已暫停;看門狗不開修理;人 resume 之後不再停同一版。"""
    box = Box()
    deps = _breach_deps(box, {"write_other": "失守", "write_work": "正常"})
    repair._check_permprobe(pcfg, deps, 1e6)
    assert _stop_kind(pcfg) == ingest.STOP_PERMPROBE
    assert len(box.mail) == 1 and "攝入已暫停" in box.mail[0][1]
    assert not [p for p in watchdog.detect(pcfg, 1e6, agents_check=lambda: [], resources_too=False)
                if p.kind == "stop"]
    assert repair.stop_resumable(pcfg, []) != ""          # 自動修理不收這種
    pcfg.ingest_stop_path.unlink()                         # 人 resume
    repair._check_permprobe(pcfg, deps, 1e6 + 180)
    assert not pcfg.ingest_stop_path.exists() and len(box.runs) == 1 and len(box.mail) == 1


def test_only_blocked_does_not_pause(pcfg):
    """只有「被擋」:攝入只會失敗、不會寫到不該寫的地方,照常跑、只寄信。"""
    box = Box()
    repair._check_permprobe(pcfg, _breach_deps(box, {"write_work": "被擋", "write_other": "擋下"}), 1e6)
    assert not pcfg.ingest_stop_path.exists()
    assert "攝入照常在跑" in box.mail[0][1]


def test_breach_waits_for_another_stop(pcfg):
    """攝入已經因為別的原因 STOP:不蓋掉那份(種類決定自動修理能不能解除),它解除後下一輪再停。"""
    pcfg.ingest_stop_path.parent.mkdir(parents=True, exist_ok=True)
    other = json.dumps({"檔案": "a.pdf", "原因": "x", "種類": ingest.STOP_LEFTOVER}, ensure_ascii=False)
    pcfg.ingest_stop_path.write_text(other, encoding="utf-8")
    box = Box()
    deps = _breach_deps(box, {"write_hook": "失守"})
    repair._check_permprobe(pcfg, deps, 1e6)
    assert pcfg.ingest_stop_path.read_text(encoding="utf-8") == other
    assert "別的原因" in box.mail[0][1]
    pcfg.ingest_stop_path.unlink()                         # 那份解除了
    repair._check_permprobe(pcfg, deps, 1e6 + 180)
    assert _stop_kind(pcfg) == ingest.STOP_PERMPROBE and len(box.runs) == 1


def test_breach_hold_survives_a_later_stop(pcfg):
    """暫停時正在跑的那輪攝入自己又 STOP(可以自動解除的那種),整份重寫停止檔:失守的標記要跟著帶過去,
    自動修理照樣不能解除;finish-stopped 照那一筆的種類,人還補得完。"""
    box = Box()
    repair._check_permprobe(pcfg, _breach_deps(box, {"write_other": "失守"}), 1e6)
    ingest._stop(pcfg, None, None, "a.pdf", "留了暫存檔", ingest.STOP_LEFTOVER)
    info = json.loads(pcfg.ingest_stop_path.read_text(encoding="utf-8"))
    assert info["種類"] == ingest.STOP_LEFTOVER and info[ingest.PERMPROBE_HOLD]
    assert "權限失守" in repair.stop_resumable(pcfg, [])
    ingest._stop(pcfg, None, None, "b.pdf", "中斷")         # 再蓋一次也還在
    assert json.loads(pcfg.ingest_stop_path.read_text(encoding="utf-8"))[ingest.PERMPROBE_HOLD]
