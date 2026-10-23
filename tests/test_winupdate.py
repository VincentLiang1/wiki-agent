"""從 zip 安裝的 Windows 朋友版自己更新(scripts/winupdate.py):不碰網路、不碰真的程式資料夾。"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _mod():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("winupdate_script", SCRIPTS / "winupdate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BASE = {"pyproject.toml": b"[project]\n", "Update.bat": b"@echo off\r\n", "scripts/winupdate.py": b"# u\n",
        "scripts/winsched.py": b"# s\n", "src/wiki_feeder/cli.py": b"# cli\n"}


def _zip(files: dict[str, bytes], tag="20261023-abc1234", manifest=None, top="wiki-agent", extra=()) -> bytes:
    files = {**files, "VERSION": f"tag={tag}\nsource=abc1234\n".encode()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, data in files.items():
            zf.writestr(f"{top}/{rel}", data)
        # 多塞的檔也列進清單:測的是路徑檢查本身,不是清單比對
        names = manifest if manifest is not None else sorted(files) + [n.split("/", 1)[1] for n, _ in extra]
        zf.writestr(f"{top}/MANIFEST", "".join(f"{n}\n" for n in names))
        for name, data in extra:
            zf.writestr(name, data)
    return buf.getvalue()


def _installed(tmp_path, files, tag="20261022-old0000"):
    root = tmp_path / "wiki-agent"
    for rel, data in {**files, "VERSION": f"tag={tag}\n".encode()}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    (root / "MANIFEST").write_text("".join(f"{r}\n" for r in sorted([*files, "VERSION"])), encoding="utf-8")
    return root


def test_update_replaces_changed_files_removes_dropped_ones_and_keeps_the_rest(tmp_path):
    """舊版 MANIFEST 有、新版沒有的才刪;.venv、朋友自己放的檔一律不碰。"""
    m = _mod()
    root = _installed(tmp_path, {**BASE, "src/wiki_feeder/old.py": b"# gone\n"})
    (root / ".venv" / "Lib").mkdir(parents=True)
    (root / ".venv" / "Lib" / "x.py").write_text("venv")
    (root / "my-notes.txt").write_text("朋友的")
    new = {**BASE, "src/wiki_feeder/cli.py": b"# cli v2\n", "src/wiki_feeder/new.py": b"# new\n"}
    z = tmp_path / "new.zip"
    z.write_bytes(_zip(new))
    msg = m.update(root, z)
    assert "20261023-abc1234" in msg
    assert (root / "src/wiki_feeder/cli.py").read_bytes() == b"# cli v2\n"
    assert (root / "src/wiki_feeder/new.py").exists() and not (root / "src/wiki_feeder/old.py").exists()
    assert (root / ".venv/Lib/x.py").read_text() == "venv" and (root / "my-notes.txt").exists()
    assert m.local_version(root)["tag"] == "20261023-abc1234"
    assert not list(root.rglob("*.wf-new"))


@pytest.mark.parametrize("bad", ["missing", "manifest", "escape", "venv"])
def test_a_bad_zip_changes_nothing(tmp_path, bad):
    """換到一半的程式可能根本跑不起來:整包驗過才動檔,有一點不對就一個檔都不換。"""
    m = _mod()
    root = _installed(tmp_path, BASE)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    new = {**BASE, "src/wiki_feeder/cli.py": b"# v2\n"}
    data = {"missing": lambda: _zip({k: v for k, v in new.items() if k != "scripts/winsched.py"}),
            "manifest": lambda: _zip(new, manifest=["pyproject.toml"]),
            "escape": lambda: _zip(new, extra=[("wiki-agent/../evil.txt", b"x")]),
            "venv": lambda: _zip(new, extra=[("wiki-agent/.venv/pyvenv.cfg", b"x")])}[bad]()
    z = tmp_path / "bad.zip"
    z.write_bytes(data)
    with pytest.raises(m.UpdateError):
        m.update(root, z)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def _fake_github(zip_bytes, tag, digest=None):
    calls = []

    def get(url, timeout=60):
        calls.append(url)
        if url == _mod().API:
            asset = {"name": "wiki-agent-win.zip", "browser_download_url": "https://dl/x.zip"}
            if digest is not False:
                asset["digest"] = "sha256:" + (digest or hashlib.sha256(zip_bytes).hexdigest())
            return json.dumps({"tag_name": tag, "assets": [asset]}).encode()
        return zip_bytes
    return get, calls


def test_already_latest_does_not_download(tmp_path):
    m = _mod()
    root = _installed(tmp_path, BASE, tag="20261023-abc1234")
    get, calls = _fake_github(b"", "20261023-abc1234")
    assert "已經是最新版" in m.update(root, get=get) and calls == [m.API]


def test_download_is_checked_against_githubs_sha256_and_the_tag(tmp_path):
    m = _mod()
    root = _installed(tmp_path, BASE)
    data = _zip({**BASE, "src/wiki_feeder/cli.py": b"# v2\n"})
    get, _ = _fake_github(data, "20261023-abc1234", digest="0" * 64)
    with pytest.raises(m.UpdateError, match="sha256"):
        m.update(root, get=get)
    get, _ = _fake_github(data, "20261024-zzz9999")
    with pytest.raises(m.UpdateError, match="不是最新版"):
        m.update(root, get=get)
    assert (root / "src/wiki_feeder/cli.py").read_bytes() == b"# cli\n"
    get, _ = _fake_github(data, "20261023-abc1234")
    m.update(root, get=get)
    assert (root / "src/wiki_feeder/cli.py").read_bytes() == b"# v2\n"


def test_git_installs_are_left_to_git_pull(tmp_path):
    m = _mod()
    root = _installed(tmp_path, BASE)
    (root / ".git").mkdir()
    with pytest.raises(m.UpdateError, match="git pull"):
        m.update(root, get=lambda *a, **k: pytest.fail("不可以下載"))


def test_backup_and_restore_bring_the_old_version_back(tmp_path):
    """自動更新換版失敗要退回:備份現在這一版,還原時新版多的檔刪掉、改過的寫回,其他(.venv、朋友的檔)不碰。"""
    m = _mod()
    root = _installed(tmp_path, {**BASE, "src/wiki_feeder/old.py": b"# old\n"})
    (root / "my-notes.txt").write_text("朋友的")
    bak = tmp_path / "bak"
    m.backup(root, bak)
    z = tmp_path / "new.zip"
    z.write_bytes(_zip({**BASE, "src/wiki_feeder/cli.py": b"# v2\n", "src/wiki_feeder/new.py": b"# new\n"}))
    m.update(root, z)
    assert not (root / "src/wiki_feeder/old.py").exists()
    m.restore(root, bak)
    assert (root / "src/wiki_feeder/cli.py").read_bytes() == b"# cli\n"
    assert (root / "src/wiki_feeder/old.py").exists() and not (root / "src/wiki_feeder/new.py").exists()
    assert m.local_version(root)["tag"] == "20261022-old0000" and (root / "my-notes.txt").exists()
