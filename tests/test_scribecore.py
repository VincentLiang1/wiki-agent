"""Scribe2MD 核心的下載與安裝(scribecore.py,spec §4.9):假的 Release(file:// 資料夾)、假的核心安裝程式。"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from wiki_feeder import scribecore
from wiki_feeder.doc2md import entry_exe

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="假的核心安裝程式是 zsh 腳本;Windows 的是 install.ps1")
FAKE = Path(__file__).with_name("fake_doc2md.py")
INFO = {"name": "Scribe2MD", "version": "1.12.0", "build": "core", "audio": True, "entry_contract": 1}

# 假的 install.command:照真的做三件事的形狀——在 FAKE_CORE_ROOT 建 core/ 與 bin/doc2md、最後印 SCRIBE2MD-INSTALLED
INSTALLER = f'''#!/bin/zsh
[[ "$1" == "--yes" ]] || exit 2
[[ -n "$FAKE_CORE_FAIL" ]] && {{ echo "uv sync failed" >&2; exit 1 }}
mkdir -p "$FAKE_CORE_ROOT/core" "$FAKE_CORE_ROOT/bin"
print -r -- '#!/bin/sh
exec "{sys.executable}" "{FAKE}" "$@"' > "$FAKE_CORE_ROOT/bin/doc2md"
chmod +x "$FAKE_CORE_ROOT/bin/doc2md"
echo "installing…"
echo "SCRIBE2MD-INSTALLED 1.12.0"
'''


def _release(tmp_path: Path, tamper: bool = False) -> str:
    rel = tmp_path / "release"
    rel.mkdir()
    z = rel / "scribe2md-core-mac.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("scribe2md-core/install.command", INSTALLER)
        f.writestr("scribe2md-core/VERSION", "abc1234 2026-11-07\nversion=1.12.0\n")
    data = z.read_bytes()
    sha = hashlib.sha256(data + (b"x" if tamper else b"")).hexdigest()
    (rel / "scribe2md-core-mac.json").write_text(json.dumps({"version": "1.12.0", "stamp": "x", "sha256": sha,
                                                              "size": len(data), "build": "core"}), encoding="utf-8")
    return rel.as_uri() + "/"


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "meeting-scribe"
    monkeypatch.setenv("FAKE_CORE_ROOT", str(root))
    monkeypatch.setenv("FAKE_DOC2MD_VERSION", json.dumps(INFO))
    monkeypatch.delenv("FAKE_CORE_FAIL", raising=False)
    return root


def test_install_downloads_verifies_runs_the_installer_and_cleans_up(tmp_path, env):
    """照 manifest 驗過才裝;裝完問固定入口的版本確認;zip 與暫存都刪掉。"""
    said = []
    work = tmp_path / "state" / "downloads"
    info = scribecore.install(env, work, said.append, base=_release(tmp_path), platform="darwin")
    assert info["version"] == "1.12.0" and entry_exe(env, "darwin").is_file()
    assert list(work.iterdir()) == [] and any("100%" in s for s in said)


def test_tampered_download_is_not_installed(tmp_path, env):
    """大小或 sha256 對不上(下載不完整、被換掉):不解壓、不執行安裝程式、不留 .part。"""
    work = tmp_path / "w"
    with pytest.raises(scribecore.CoreError, match="sha256"):
        scribecore.install(env, work, lambda s: None, base=_release(tmp_path, tamper=True), platform="darwin")
    assert not (env / "core").exists() and list(work.iterdir()) == []


def test_failed_installer_is_reported_as_such(tmp_path, env, monkeypatch):
    """安裝程式離開碼不是 0、或最後一行不是 SCRIBE2MD-INSTALLED:說安裝程式沒裝好,不說成別的。"""
    monkeypatch.setenv("FAKE_CORE_FAIL", "1")
    with pytest.raises(scribecore.CoreError, match="安裝程式沒有裝好"):
        scribecore.install(env, tmp_path / "w", lambda s: None, base=_release(tmp_path), platform="darwin")


def test_broken_manifest_stops_before_downloading(tmp_path, env):
    base = _release(tmp_path)
    (tmp_path / "release" / "scribe2md-core-mac.json").write_text('{"version": "1.12.0"}', encoding="utf-8")
    with pytest.raises(scribecore.CoreError, match="格式不對"):
        scribecore.install(env, tmp_path / "w", lambda s: None, base=base, platform="darwin")


def test_installer_and_assets_per_platform(tmp_path):
    """Windows 用 PowerShell 非互動執行 install.ps1 -Yes;Mac 用 zsh 叫 install.command --yes(不靠執行權限位元)。"""
    assert scribecore.asset_names("win32") == ("scribe2md-core-win.zip", "scribe2md-core-win.json")
    win = scribecore.installer_cmd(tmp_path, "win32")
    assert "-NonInteractive" in win and win[-2:] == [str(tmp_path / "install.ps1"), "-Yes"]
    assert scribecore.installer_cmd(tmp_path, "darwin") == ["/bin/zsh", str(tmp_path / "install.command"), "--yes"]
    assert scribecore.RELEASE.endswith("/wiki-agent/releases/download/scribe2md-core/")


def test_installed_version_reads_version_file_then_pyproject(tmp_path):
    """核心自己那份的版本:VERSION 的 version= 優先,沒有就看 pyproject.toml(第一版的 VERSION 只有一行);
    讀不到回空字串,自動更新就不動(newer 對空字串一律不算新)。"""
    core = tmp_path / "core"
    core.mkdir()
    assert scribecore.installed_version(tmp_path) == ""
    (core / "VERSION").write_text("8b94703 2026-11-07\n", encoding="utf-8")
    (core / "pyproject.toml").write_text('[project]\nname = "meeting-scribe"\nversion = "1.10.1"\n', encoding="utf-8")
    assert scribecore.installed_version(tmp_path) == "1.10.1"
    (core / "VERSION").write_text("8b94703 2026-11-07\nversion=1.11.0\n", encoding="utf-8")
    assert scribecore.installed_version(tmp_path) == "1.11.0"
