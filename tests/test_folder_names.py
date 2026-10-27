"""原件樹的系統資料夾名(使用者 2026-10-24):新安裝一律英文 _Pending、_Discarded、_Inbox,每種語言同一個名字;
已經有中文舊名(_待處理、_捨棄候選、_收件區)的庫沿用舊名,不改名、不另建英文的。
名稱由安裝程式看磁碟決定、寫進 config.toml;設定檔沒寫(舊版裝的、升級不重寫)= 舊名。spec §5.13。
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import git

from wiki_feeder import i18n
from wiki_feeder.collect import collect
from wiki_feeder.config import (CONFIG_FILE, LEGACY, SYSTEM_DIRS, Config, ConfigError, folder_names)
from wiki_feeder.convert import convert
from wiki_feeder.ingest import ingest

ROOT = Path(__file__).parents[1]
HERE = Path(__file__).parent
NEW = ("_Pending", "_Discarded", "_Inbox")
OLD = ("_待處理", "_捨棄候選", "_收件區")


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ws = _mod("winsetup")


def _install(tmp_path: Path, monkeypatch, lang: str) -> tuple[Config, Path]:
    """安裝問答的知識庫那一題全按 Enter(不叫 claude 建庫),寫出設定檔再讀回來。"""
    i18n.set_lang(lang)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    w, r = ws.ask_wiki(str(tmp_path / "LLMWIKI" / "WIKI"), None, False)
    a = {"lang": lang, "icloud": str(tmp_path / "iCloud" / "_WikiBox"), "wiki": w, "raw": r, "doc2md": "/x/doc2md"}
    return ws.write_config(ws.render_config(a), tmp_path / "state"), Path(r)


def _names(c: Config) -> tuple[str, str, str]:
    return c.pending_name, c.discard_name, c.pending_dir.name


@pytest.mark.parametrize("lang", i18n.LANGS)
def test_new_install_uses_english_folders_in_every_language(tmp_path, monkeypatch, lang):
    c, raw = _install(tmp_path, monkeypatch, lang)

    assert _names(c) == NEW
    assert c.target_pending == raw / "_Pending" and c.discard_dir == raw / "_Discarded"
    assert sorted(p.name for p in raw.iterdir()) == ["_Pending"]          # 一個中文資料夾都沒建


@pytest.mark.parametrize("old", OLD, ids=["pending", "discard", "intake"])   # 中文 id pytest 會轉成跳脫碼
def test_existing_library_keeps_its_chinese_folders_in_english_install(tmp_path, monkeypatch, old):
    """原件樹裡已經有任何一個舊名(就算只有 _捨棄候選):三個都沿用舊名,英文版也不另建 _Pending／_Discarded。"""
    raw = tmp_path / "LLMWIKI" / "Raw_Sources"
    (raw / old).mkdir(parents=True)
    (raw / old / "a.m4a").write_bytes(b"keep")

    c, _ = _install(tmp_path, monkeypatch, "en")

    assert _names(c) == OLD
    assert not any(n in NEW for n in (p.name for p in raw.iterdir()))
    assert (raw / old / "a.m4a").read_bytes() == b"keep"


def test_folder_names_only_look_at_this_raw_tree(tmp_path):
    assert folder_names(tmp_path) == {n: n for n in NEW}
    (tmp_path / "_Pending").mkdir()
    assert folder_names(tmp_path) == {n: n for n in NEW}                  # 新安裝重跑:結果不變
    (tmp_path / "_收件區").mkdir()
    assert folder_names(tmp_path) == LEGACY


def test_config_without_folder_keys_is_an_old_install(tmp_path):
    """升級(Update.bat／Update.command、自動更新)不重寫設定檔:舊版寫的沒有這三個鍵 = 中文舊名,
    就算磁碟上看不到舊資料夾(雲端資料夾某一輪讀不到)也不改用英文、不另建。"""
    state = tmp_path / "state"
    state.mkdir()
    (state / CONFIG_FILE).write_text(
        f"[inbox]\nicloud = '{tmp_path / 'i'}'\n[wiki]\ndir = '{tmp_path / 'W'}'\nraw = '{tmp_path / 'R'}'\n"
        "[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    assert _names(Config.from_file(state / CONFIG_FILE, state)) == OLD
    # 換語言重跑安裝、沿用舊設定檔:只改 language,資料夾名照舊
    text = ws.set_config_lang((state / CONFIG_FILE).read_text(encoding="utf-8"), "en")
    assert _names(ws.write_config(text, state)) == OLD


def test_config_rejects_unknown_folder_names(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / CONFIG_FILE).write_text(
        f"[inbox]\nicloud = '{tmp_path / 'i'}'\n[wiki]\ndir = '{tmp_path / 'W'}'\nraw = '{tmp_path / 'R'}'\n"
        "discard = '捨棄候選'\n[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="discard"):
        Config.from_file(state / CONFIG_FILE, state)


def test_existing_wikis_own_inbox_name_is_accepted_but_not_a_lookalike_of_another_folder(tmp_path):
    """已經有知識庫的朋友,待處理資料夾照他 CLAUDE.md 寫的(使用者 2026-10-27);不能是多層、隱藏、
    或跟收件區、捨棄只差大小寫(磁碟上是同一個資料夾)。自訂的入口也不算原件。"""
    state = tmp_path / "state"
    state.mkdir()

    def load(pending: str, intake: str = "_Inbox", discard: str = "_Discarded") -> Config:
        (state / CONFIG_FILE).write_text(
            f"[inbox]\nicloud = '{tmp_path / 'i'}'\n[wiki]\ndir = '{tmp_path / 'W'}'\nraw = '{tmp_path / 'R'}'\n"
            f"pending = '{pending}'\ndiscard = '{discard}'\nintake = '{intake}'\n[tools]\ndoc2md = 'x'\n", encoding="utf-8")
        return Config.from_file(state / CONFIG_FILE, state)

    c = load("inbox")
    assert c.pending_name == "inbox" and "inbox" in c.raw_skip_dirs and set(SYSTEM_DIRS) <= set(c.raw_skip_dirs)
    assert load("_Pending").raw_skip_dirs == SYSTEM_DIRS
    for bad in ("a/b", ".inbox", "..", ""):
        with pytest.raises(ConfigError, match="pending"):
            load(bad)
    with pytest.raises(ConfigError, match="intake"):
        load("_inbox")
    with pytest.raises(ConfigError, match="discard"):
        load("inbox", discard="trash")                         # 捨棄、收件區仍只認系統名


def test_owner_mac_keeps_the_chinese_names():
    """使用者本人的 FWIKI 與個人 WIKI 都是舊名:明寫在 owner_mac,不靠預設、不看磁碟。"""
    src = (ROOT / "src" / "wiki_feeder" / "owner_mac.py")
    if not src.exists():
        pytest.skip("公開 repo 沒有 owner_mac.py")
    from wiki_feeder import owner_mac
    c = owner_mac.config()
    assert (c.pending_name, c.discard_name, c.pending_dir.name) == ("_待處理", "_捨棄候選", "_待處理")


@pytest.mark.parametrize("d", SYSTEM_DIRS)
def test_every_system_folder_is_skipped_when_indexing_originals(cfg, tmp_path, d):
    """待處理、捨棄、收件區裡的檔不是已歸檔的原件:算進索引的話,同內容新收到的檔被判成重複、刪掉來源。新舊名稱都要跳過。"""
    raw = tmp_path / "Raw_Sources"
    (raw / "健康生活").mkdir(parents=True)
    c = replace(cfg, raw_roots=(raw,))
    (raw / d).mkdir()
    (raw / d / "a.m4a").write_bytes(b"not-an-original")
    (c.icloud_inbox / "a2.m4a").write_bytes(b"not-an-original")

    r = collect(c)

    assert [Path(p).name for p in r.moved] == ["a2.m4a"]


@pytest.fixture
def english(tmp_path, monkeypatch):
    """新安裝的單庫(英文資料夾名);流程比照 test_single_repo 的 single。"""
    root = tmp_path / "LLMWIKI"
    wiki, raw = root / "WIKI", root / "Raw_Sources"
    (wiki / "Wiki_Pages").mkdir(parents=True)
    (wiki / "CLAUDE.md").write_text("# 規則\n", encoding="utf-8")
    (wiki / "Wiki_Pages" / "index.md").write_text("# 索引\n", encoding="utf-8")
    (raw / "會議與月報").mkdir(parents=True)
    (raw / "_Pending").mkdir()
    icloud = tmp_path / "iCloudDrive" / "_WikiBox"
    icloud.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    (state / CONFIG_FILE).write_text(
        f"[inbox]\nicloud = '{icloud}'\n[wiki]\ndir = '{wiki}'\nraw = '{raw}'\n"
        "pending = '_Pending'\ndiscard = '_Discarded'\nintake = '_Inbox'\n"
        f"[mail]\nfrom = ''\nto = ''\n[tools]\ndoc2md = 'x'\n", encoding="utf-8")
    for k, v in {"FAKE_CLAUDE_ARGS": tmp_path / "claude.jsonl", "FAKE_DOC2MD_ARGS": tmp_path / "doc2md.jsonl"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("FAKE_CLAUDE_MODE", raising=False)
    c = replace(Config.from_file(state / CONFIG_FILE, state), stable_wait=0, trigger_icloud_download=False,
                claude_cmd=(sys.executable, str(HERE / "fake_claude.py")),
                doc2md_cmd=(sys.executable, str(HERE / "fake_doc2md.py")),
                ingest_tools_cmd=("/x/python", "-P", "-m", "wiki_feeder"))
    seen = []
    real_run = __import__("subprocess").run

    def spy(cmd, *a, **k):
        if "-p" in cmd:
            seen.append(k.get("input", ""))
        return real_run(cmd, *a, **k)

    monkeypatch.setattr("wiki_feeder.ingest.subprocess.run", spy)
    return {"cfg": c, "wiki": wiki, "raw": raw, "prompts": seen}


def _feed(e, name: str, data: bytes) -> None:
    c = e["cfg"]
    (c.icloud_inbox / name).write_bytes(data)
    assert collect(c).ok and (e["raw"] / "_Inbox" / name).is_file()
    assert convert(c).ok


def _summary(c: Config) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in c.summaries_dir.glob("*.md"))


def test_english_folders_carry_a_file_through_and_the_prompt_names_them(english):
    _feed(english, "a.txt", b"aaa")

    (o,) = ingest(english["cfg"]).outcomes

    assert o.status == "done", o.error
    assert (english["raw"] / "會議與月報" / "a.txt").is_file()
    (prompt,) = english["prompts"]
    assert "不得處理 _Pending 裡的其他檔案" in prompt and "移到 _Discarded 等使用者確認" in prompt
    assert not any(old in prompt for old in OLD)
    assert sorted(p.name for p in english["raw"].iterdir()) == ["_Inbox", "_Pending", "會議與月報"]


def test_discarded_file_goes_to_the_configured_folder_and_summary_says_so(english, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "skip")
    _feed(english, "IMG_證件.jpg", b"id-card")

    (o,) = ingest(english["cfg"]).outcomes

    assert o.status == "discarded"
    assert (english["raw"] / "_Discarded" / "IMG_證件.jpg").is_file()
    assert not (english["raw"] / "_捨棄候選").exists()
    summary = _summary(english["cfg"])
    assert "`_Discarded/`" in summary and "_捨棄候選" not in summary


def test_report_without_a_known_group_says_the_real_pending_folder(english, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_GROUP", "../外面")
    _feed(english, "a.txt", b"aaa")

    (o,) = ingest(english["cfg"]).outcomes

    assert (english["raw"] / "_Pending" / "a.txt").is_file()
    assert any("_Pending/ 待人搬" in n for n in o.notes) and not any("_待處理" in n for n in o.notes)
    assert git("status", "--porcelain", cwd=english["wiki"]) == ""


def test_inbox_without_underscore_carries_a_file_through_and_is_never_a_group(english, monkeypatch):
    """朋友 CLAUDE.md 的入口叫 inbox(沒有 _):它不是群組——不列進回報的群組清單、回報拿它當新群組也不搬,
    裡面還沒攝入的檔也不算原件。"""
    e = english
    (e["raw"] / "_Pending").rmdir()
    (e["raw"] / "inbox").mkdir()
    c = replace(e["cfg"], pending_name="inbox", raw_skip_dirs=SYSTEM_DIRS + ("inbox",))
    e["cfg"] = c
    _feed(e, "a.txt", b"aaa")
    (o,) = ingest(c).outcomes
    assert o.status == "done", o.error
    assert (e["raw"] / "會議與月報" / "a.txt").is_file()
    (prompt,) = e["prompts"]
    assert "不得處理 inbox 裡的其他檔案" in prompt
    assert "先從現有群組挑:會議與月報;" in prompt                         # 群組清單裡沒有入口

    monkeypatch.setenv("FAKE_CLAUDE_GROUP", "Inbox")           # 只差大小寫:磁碟上是同一個資料夾
    _feed(e, "b.txt", b"bbb")
    (o,) = ingest(c).outcomes
    assert (e["raw"] / "inbox" / "b.txt").is_file() and "Inbox" in " ".join(o.notes)
