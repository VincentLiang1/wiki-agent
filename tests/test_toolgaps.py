"""攝入工具缺口(toolgaps.py):被權限擋下的指令、claude 回報做不到的檢查,摘要信一天提醒一次。

使用者 2026-10-07 要求:「以後每天要幫忙查一下,是否有可以增加的指令,給我 email 時給我提醒」。
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from wiki_feeder import notify, toolgaps
from wiki_feeder.cli import main
from wiki_feeder.ingest import IngestReport, post_summary

NOW = datetime(2026, 10, 8, 9, 0)


def test_same_kind_of_gap_gets_the_same_key():
    k = toolgaps.key_of
    assert k("denied", "Bash: python3 /tmp/a/sum.py --x") == k("denied", "Bash: python3 /var/b/sum.py") == "Bash: python3 sum.py"
    assert k("denied", "Bash: git log -1") == "Bash: git log"
    assert k("denied", "Bash: LC_ALL=C.UTF-8 grep -rPn x Wiki_Pages/") == "Bash: grep"
    assert k("denied", "Bash: awk '{s+=$1}' a.md") == "Bash: awk"
    assert k("denied", "Write: /etc/x") == "Write"
    assert k("denied", "Bash: git -C /Users/x/FWIKI add Wiki_Pages/ && git -C /Users/x/FWIKI status") == "Bash: git -C"
    assert k("denied", "Bash: rm -f a.md") == "Bash: rm"
    assert k("denied", "Bash: git add a.md && python3 /tmp/sum.py") == "Bash: python3 sum.py"   # 沒放行的那一段
    assert k("denied", "Bash: git commit -q -F - <<'EOF'\ndocs: a; b && c\nEOF") == "Bash: git commit"
    assert k("denied", "Bash: git add 'a.md && rm") == "Bash: rm"              # 引號沒配對(被截短)也拆得開


def test_chained_command_is_keyed_by_the_segment_that_was_forbidden():
    """2026-10-15 兩筆攝入把 git diff 串在放行的 git add／status 後面,整條被擋;
    提醒寫成「被擋下 git add」「被擋下 git status」,看起來像放行的指令不能用、該去查權限。"""
    k = toolgaps.key_of
    assert k("denied", "Bash: git add Wiki_Pages/ && git status --short && git diff --cached --stat") == "Bash: git diff"
    assert k("denied", "Bash: git status --short; git diff --stat") == "Bash: git diff"
    assert k("denied", "Bash: git status --short | git show --stat HEAD") == "Bash: git show"
    assert k("unverified", "同名 docx 未重產:要執行本庫 tools/ 的腳本") == "同名 docx 未重產"
    assert k("unverified", "同名 docx 未重產：營運計畫") == "同名 docx 未重產"      # 全形冒號也算


def test_digest_groups_recent_gaps_and_marks_repeats(cfg):
    toolgaps.record(cfg, "a.pdf", "unverified", ["同名 docx 未重產:要執行本庫 tools/ 的腳本"], NOW - timedelta(days=2))
    toolgaps.record(cfg, "b.pdf", "unverified", ["同名 docx 未重產:營運計畫"], NOW - timedelta(days=1))
    toolgaps.record(cfg, "b.pdf", "denied", ["Bash: python3 /tmp/sum.py"], NOW - timedelta(days=1))
    toolgaps.record(cfg, "old.pdf", "denied", ["Bash: node x.js"], NOW - timedelta(days=8))   # 超過 7 天

    lines = toolgaps.digest(cfg, NOW)

    assert lines[0].startswith("### 🧰 攝入工具缺口")
    assert lines[1] == "- 🔁 未驗「同名 docx 未重產」:2 筆攝入(10/06～10/07),例:同名 docx 未重產:營運計畫"
    assert lines[2] == "- 被擋下「Bash: python3 sum.py」:1 筆攝入(10/07),例:Bash: python3 /tmp/sum.py"
    assert not any("node" in x for x in lines)
    assert "tool-gaps --ignore" in lines[-1]


def test_forbidden_commands_are_labelled_and_listed_last(cfg):
    """權限刻意擋的(DISALLOWED_TOOLS)不是可以補的指令:2026-10-07 八筆 `git -C` 被擋,提醒卻寫成
    「被擋下「Bash: git」」排第一,看起來像該放行 git;它其實要改的是提示(f73f283 已改)。"""
    for n in range(3):
        toolgaps.record(cfg, f"g{n}.pdf", "denied", ["Bash: git -C /Users/x/FWIKI add Wiki_Pages/"], NOW)
    toolgaps.record(cfg, "a.pdf", "denied", ["Bash: python3 /tmp/sum.py"], NOW)

    lines = toolgaps.digest(cfg, NOW)

    assert lines[1].startswith("- 被擋下「Bash: python3 sum.py」")
    assert lines[2].startswith("- 🔁 刻意禁止「Bash: git -C」:3 筆攝入")
    assert any("不會放行" in x for x in lines)


def test_mail_lists_eight_but_the_command_lists_all(cfg, capsys):
    """信最多列 8 項、寫「另有 N 項,tool-gaps 看全部」;指令本身要真的列全部(2026-10-30 指令也只列 8 項)。"""
    now = datetime.now()
    for i in range(10):
        toolgaps.record(cfg, f"{i}.pdf", "unverified", [f"缺口{i}:原因"], now)

    mail = toolgaps.digest(cfg, now)
    assert sum(x.startswith("- 未驗") for x in mail) == toolgaps.MAX_ITEMS
    assert "- 另有 2 項,`wiki-feeder tool-gaps` 看全部" in mail

    assert main(["tool-gaps"], cfg) == 0
    out = capsys.readouterr().out
    assert all(f"「缺口{i}」" in out for i in range(10)) and "另有" not in out


def test_ignored_gaps_drop_out_of_the_reminder(cfg, capsys):
    """確定不做的(例如同名 docx 重產,2026-10-07 使用者決定維持現狀)不要天天提醒。"""
    toolgaps.record(cfg, "a.pdf", "unverified", ["同名 docx 未重產:x"], NOW)
    assert main(["tool-gaps", "--ignore", "docx"], cfg) == 0
    assert "已加進不提醒清單:docx" in capsys.readouterr().out
    assert toolgaps.digest(cfg, NOW) == []


def test_resolved_gaps_drop_out_until_they_happen_again(cfg, capsys):
    """已補好的不再提醒、只列還要改良的(使用者 2026-10-19:「如果程式已改好,可以不要繼續寫在信裡面」);
    但補好之後又出現就是沒補好,照樣列、標「修好後又出現」——不能像 --ignore 永遠藏起來。"""
    toolgaps.record(cfg, "a.pdf", "unverified", ["圖片嵌入:要執行 PIL"], NOW - timedelta(days=3))
    toolgaps.record(cfg, "b.pdf", "denied", ["Bash: git show --stat HEAD"], NOW - timedelta(days=3))
    toolgaps.record(cfg, "c.pdf", "unverified", ["人名字形回原件核對:xlsx 附件"], NOW - timedelta(days=3))
    fix = NOW - timedelta(days=2)
    toolgaps.resolve(cfg, "圖片嵌入", fix)
    toolgaps.resolve(cfg, "git show", fix)
    toolgaps.record(cfg, "d.pdf", "denied", ["Bash: git show HEAD"], NOW - timedelta(days=1))

    lines = toolgaps.digest(cfg, NOW)

    assert not any("圖片嵌入" in x for x in lines)
    assert any(x.startswith("- 未驗「人名字形回原件核對」") for x in lines)
    assert "- 刻意禁止「Bash: git show」:10/06 修好後又出現,1 筆攝入(10/07),例:Bash: git show HEAD" in lines

    assert main(["tool-gaps", "--resolved", "人名字形", "--resolved", "git show"], cfg) == 0
    out = capsys.readouterr().out
    assert "已標成補好:人名字形" in out and "人名字形回原件核對" not in out.split("已標成補好:git show")[1]
    assert not any("git show" in x for x in toolgaps.digest(cfg, datetime.now() + timedelta(seconds=1)))


def _mail(monkeypatch, cfg, fail=False):
    sent = []

    def send(c, subject, body):
        if fail:
            raise notify.MailError("寄信失敗:連不上")
        sent.append(body)

    monkeypatch.setattr(notify, "send", send)
    return replace(cfg, mail_from="me@example.com", mail_to="me@example.com"), sent


def test_reminder_rides_on_the_first_mail_of_the_day(cfg, monkeypatch):
    c, sent = _mail(monkeypatch, cfg)
    toolgaps.record(c, "a.pdf", "denied", ["Bash: python3 /tmp/sum.py"], NOW)

    post_summary(c, IngestReport(alerts=["x"]), NOW)
    post_summary(c, IngestReport(alerts=["y"]), NOW + timedelta(hours=1))
    post_summary(c, IngestReport(alerts=["z"]), NOW + timedelta(days=1))

    assert ["攝入工具缺口" in b for b in sent] == [True, False, True]


def test_reminder_is_not_used_up_by_a_mail_that_failed(cfg, monkeypatch):
    c, _ = _mail(monkeypatch, cfg, fail=True)
    toolgaps.record(c, "a.pdf", "denied", ["Bash: python3 /tmp/sum.py"], NOW)
    post_summary(c, IngestReport(alerts=["x"]), NOW)
    assert not toolgaps.reported_today(c, NOW)

    c, sent = _mail(monkeypatch, cfg)
    post_summary(c, IngestReport(alerts=["x"]), NOW + timedelta(minutes=1))
    assert "攝入工具缺口" in sent[0]


def test_nothing_to_report_adds_nothing(cfg, monkeypatch):
    c, sent = _mail(monkeypatch, cfg)
    post_summary(c, IngestReport(alerts=["x"]), NOW)
    assert "攝入工具缺口" not in sent[0] and not toolgaps.reported_today(c, NOW)
