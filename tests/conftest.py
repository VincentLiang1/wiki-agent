"""測試絕不碰真實收件匣、真實 Raw_Sources 與真實 repo:一律用 tmp_path。

兩道防線:(1) Config 全部由 tmp_path 組成;(2) HOME 指到 tmp,萬一有程式碼
誤用 Path.home() / Config.default(),碰到的也是假的家目錄。
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import _lf  # noqa: F401 —— Windows 上 write_text 寫 LF
import pytest

from wiki_feeder.config import Config, FuturesConfig

# 假 claude／doc2md 是 sys.executable 跑的 Python:Windows 上沒有 UTF-8 模式會用 cp950 讀提示而當掉
# (pytest 帶 -X utf8 不會傳給子行程;2026-10-20 環境裡沒有 PYTHONUTF8 時 84 個紅)。
# 在這裡設、不用 monkeypatch:有些測試中途 monkeypatch.undo() 會連 fixture 設的一起撤掉
os.environ["PYTHONUTF8"] = "1"


@pytest.fixture(autouse=True)
def _fake_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    # 測試裡的 git 不讀使用者的全域設定(簽章、hooks、別名都可能讓結果不同)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig-none"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(k, "t")
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "t@t")
    yield


@pytest.fixture(autouse=True)
def _source_language():
    """介面語言是整個行程一份(i18n.set_lang):每個測試從繁中原文開始,測英文的自己設、結束還原。"""
    from wiki_feeder import i18n
    i18n.set_lang(i18n.SOURCE)
    yield
    i18n.set_lang(i18n.SOURCE)


@pytest.fixture(autouse=True)
def _isolate_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def git(*args: str, cwd: Path) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


class FakeFutures:
    """假的 FUTURES:bare remote + 一個「公司電腦」的工作副本。"""

    def __init__(self, root: Path):
        self.remote = root / "remote.git"
        self.company = root / "company"
        root.mkdir(parents=True)
        git("init", "--bare", "-q", str(self.remote), cwd=root)
        git("config", "uploadpack.allowFilter", "true", cwd=self.remote)
        git("clone", "-q", str(self.remote), str(self.company), cwd=root)
        self.write("PROCESS/_.txt", "placeholder")
        self.write("公司工作檔/機密.txt", "不可被 Mac 取出")
        self.write("根目錄檔.txt", "不可被 Mac 取出")
        self.push("init")

    def write(self, rel: str, text: str) -> None:
        p = self.company / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def push(self, msg: str = "company sync") -> None:
        git("add", "-A", cwd=self.company)
        git("commit", "-q", "-m", msg, cwd=self.company)
        git("push", "-q", "origin", "HEAD:main", cwd=self.company)

    def remote_files(self) -> set[str]:
        out = git("-c", "core.quotePath=off", "ls-tree", "-r", "--name-only", "main", cwd=self.remote)
        return set(out.split("\n")) - {""}


@pytest.fixture
def fake_futures(tmp_path) -> FakeFutures:
    return FakeFutures(tmp_path / "futures")


@pytest.fixture
def cfg(tmp_path) -> Config:
    icloud = tmp_path / "icloud" / "_WikiBox"
    onedrive = tmp_path / "onedrive" / "_WikiBox"
    icloud.mkdir(parents=True)
    onedrive.mkdir(parents=True)
    return Config(
        pending_dir=tmp_path / "Raw_Sources" / "_待處理",
        state_dir=tmp_path / "state",
        icloud_inbox=icloud,
        onedrive_inbox=onedrive,
        futures=None,
        stable_wait=0,
        trigger_icloud_download=False,
        unavailable_alert_after=1,   # 連續幾輪才報另有專門測試
    )


@pytest.fixture
def futures_cfg(tmp_path, fake_futures) -> FuturesConfig:
    # file:// 才會走真正的傳輸協定、--filter=blob:none 才有作用(純路徑會被 git 當本機複製)
    return FuturesConfig(repo_dir=tmp_path / "FUTURES-process", remote=fake_futures.remote.as_uri(),
                         check_interval=0)   # 節流另有專門測試;其餘測試每輪都要真的去查
