"""搬檔的原語:複製到暫存名 → 比對 SHA-256 → 改成正式名。刪來源不在這裡做。

刪來源由呼叫端在「處理紀錄已 commit」之後才做,見 collect.py。
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .osplat import fsync_path, is_placeholder

_CHUNK = 1024 * 1024


class VerifyError(Exception):
    """複製後的 SHA-256 與來源不一致。"""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def is_dataless(path: Path) -> bool:
    """雲端佔位檔(內容還沒下載):Mac 看 st_flags、Windows 看檔案屬性(osplat)。"""
    return is_placeholder(os.stat(path))


def suffixed(name: str, n: int) -> str:
    """`a.m4a` → `a_2.m4a`;n == 1 時原樣。"""
    if n == 1:
        return name
    p = Path(name)
    return f"{p.stem}_{n}{p.suffix}"


def pick_names(dest_dir: Path, names: list[str], reserved_exts: tuple[str, ...] = (".feeder.json",)) -> list[str]:
    """替同一組檔挑一個共同的後綴,讓整組在 dest_dir 都不撞名(含程式補寫的 sidecar)。"""
    n = 1
    while True:
        cand = [suffixed(x, n) for x in names]
        taken = any(
            (dest_dir / c).exists() or any((dest_dir / (c + ext)).exists() for ext in reserved_exts)
            for c in cand
        )
        if not taken:
            return cand
        n += 1


def copy_verified(src: Path, dest_dir: Path, final_name: str, expected_sha: str) -> Path:
    """複製 src 到 dest_dir/final_name,驗證 SHA-256 一致才落到正式名。

    任何一步失敗都清掉暫存檔並丟例外;來源完全不動。
    正式名用 os.link 落地——目標已存在時會失敗,不會覆蓋別人的檔。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    partial = dest_dir / f".{final_name}.partial"
    final = dest_dir / final_name
    try:
        shutil.copy2(src, partial)
        fsync_path(partial)
        got = sha256_of(partial)
        if got != expected_sha:
            raise VerifyError(f"{src}: 複製後 SHA-256 不符({got[:12]} ≠ {expected_sha[:12]})")
        os.link(partial, final)
    finally:
        partial.unlink(missing_ok=True)
    return final
