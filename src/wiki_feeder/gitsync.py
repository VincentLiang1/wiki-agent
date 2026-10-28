"""推送被拒之後跟上遠端:`git fetch origin <branch>` + `git rebase origin/<branch>`,失敗分兩類。

不用 `git pull --rebase`:它照 FETCH_HEAD 決定 rebase 到哪裡,FETCH_HEAD 裡有好幾筆可合併的來源時
(同時有別的 fetch 在跑)直接失敗、還沒開始 rebase。2026-10-28 13:32 實例:FWIKI 推送被拒後 pull --rebase 回
「fatal: Cannot rebase onto multiple branches.」,沒有任何內容衝突,卻被當成「rebase 失敗、待人處理」,
那筆 commit 卡在 Mac 上寄信找人,事後再 pull --rebase 一次就推上去了。

- 暫時性(`TRANSIENT`):fetch 失敗(斷網、逾時)、rebase 還沒開始就失敗(鎖檔、FETCH_HEAD 之類)——等一下重試,
  次數用完也只是「下一輪再推」
- 真正的衝突(`CONFLICT`):停在 rebase 中、呼叫端的 `finish` 也解不了——中止 rebase、本機回到原本的 commit,等人

絕不 --force、不 reset、不丟任何本機 commit(中止 rebase 會回到 rebase 前的 HEAD)。

**只碰自己開始的 rebase**:開始前在 git 目錄留記號(`MARK`),做完才清。停在 rebase 中卻沒有記號的,是人
(例:桌面的 pull-all 撞到衝突、貼給 Mac 的 Claude 解)正在處理——不中止、不接手,這輪等人做完。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

from .i18n import L

OK, TRANSIENT, CONFLICT = "ok", "transient", "conflict"
PUSH_BACKOFF = (5, 15, 30)   # 暫時性失敗後第 1、2、3 次重試前各等幾秒

Runner = Callable[..., subprocess.CompletedProcess]   # run("fetch", "-q", "origin", "main") → 文字輸出
MARK = "wiki-feeder-rebasing"   # git 目錄裡的記號檔:這個 rebase 是 wiki-feeder 開始的


def _git_path(repo: Path, name: str) -> Path:
    """`.git/<name>` 的實際位置:程式代管的庫用 --separate-git-dir,`.git` 只是指標檔,不可寫死。"""
    r = subprocess.run(["git", "rev-parse", "--git-path", name], cwd=repo, capture_output=True, text=True,
                       encoding="utf-8")
    return repo / r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else repo / ".git" / name


def rebasing(repo: Path) -> bool:
    """停在 rebase 中途(衝突、或上一輪 rebase 做到一半被砍)。"""
    return any(_git_path(repo, x).exists() for x in ("rebase-merge", "rebase-apply"))


def orig_head(repo: Path) -> str | None:
    """停在 rebase 中途時,rebase 之前的 HEAD;讀不到 → None。"""
    for x in ("rebase-merge/orig-head", "rebase-apply/orig-head"):
        try:
            return _git_path(repo, x).read_text(encoding="utf-8").strip() or None
        except OSError:
            continue
    return None


def ours(repo: Path) -> bool:
    """停在 rebase 中的話,是不是 wiki-feeder 自己開始的(上一輪做到一半被砍)。"""
    return _git_path(repo, MARK).exists()


def clear_mark(repo: Path) -> None:
    _git_path(repo, MARK).unlink(missing_ok=True)


def rebase_age(repo: Path) -> float:
    """停在 rebase 中多久了(秒);看不出來回 0。"""
    for x in ("rebase-merge", "rebase-apply"):
        try:
            return max(0.0, time.time() - _git_path(repo, x).stat().st_mtime)
        except OSError:
            continue
    return 0.0


def _err(r: subprocess.CompletedProcess) -> str:
    out = r.stderr or r.stdout or ""
    return (out if isinstance(out, str) else out.decode("utf-8", "replace")).strip()


def abort(repo: Path, run: Runner) -> bool:
    """中止 rebase、回到 rebase 之前的 HEAD;中止之後還停在 rebase 中 → False。"""
    run("rebase", "--abort")
    return not rebasing(repo)


def rebase_onto_remote(repo: Path, branch: str, run: Runner,
                       finish: Callable[[], bool] | None = None) -> tuple[str, str]:
    """推送被拒後跟上遠端。回傳 (OK／TRANSIENT／CONFLICT, 錯誤訊息)。

    finish:停在衝突上時先交給它(知識庫的 index.md 最近異動自動合併);它回 True 表示 rebase 已經做完。
    """
    if rebasing(repo):
        return TRANSIENT, L("已經有別的 rebase 在進行,不碰它")
    r = run("fetch", "-q", "origin", branch)
    if r.returncode != 0:
        return TRANSIENT, _err(r)
    mark = _git_path(repo, MARK)
    mark.write_text("", encoding="utf-8")   # 先留記號再 rebase:做到一半被砍,下一輪認得出是自己的
    r = run("rebase", "-q", f"origin/{branch}")
    if r.returncode == 0:
        clear_mark(repo)
        return OK, ""
    if "already a rebase" in _err(r):       # 剛好有人同時開始 rebase:那是別人的,不中止
        clear_mark(repo)
        return TRANSIENT, _err(r)
    if not rebasing(repo):
        clear_mark(repo)
        return TRANSIENT, _err(r)          # 還沒開始 rebase 就失敗:本機什麼都沒動
    if finish is not None and finish():
        clear_mark(repo)
        return OK, ""
    if abort(repo, run):
        clear_mark(repo)                   # 中止失敗就留著記號:下一輪開頭照自己的收拾
    return CONFLICT, _err(r)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def wait(attempt: int) -> None:
    """第 attempt 次(從 0 起)暫時性失敗之後、下一次重試之前等一下。"""
    _sleep(PUSH_BACKOFF[min(attempt, len(PUSH_BACKOFF) - 1)])
