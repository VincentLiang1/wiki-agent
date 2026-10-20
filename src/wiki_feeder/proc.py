"""連網的子行程(git 對 GitHub):一律有逾時,逾時砍整個行程群組。

2026-10-05 實例:FUTURES 的 `git ls-remote` 經 ssh 卡了 44 分鐘——收件整段停擺,
還一直握著 deploy.lock 的共享鎖,發佈等不到獨佔鎖。只給 subprocess.run 加 timeout 不夠:
它只砍 git,孫行程 ssh 還握著輸出管線,讀輸出那一步照樣卡住,所以要開新行程群組、整組砍。
"""
from __future__ import annotations

import subprocess

from .osplat import group_kwargs, kill_group

TIMED_OUT = 124   # 照 timeout(1) 的慣例
NET_TIMEOUT = 300  # 攝入的 git pull／push;FUTURES 用 FuturesConfig.net_timeout


def run_net(cmd: list[str], timeout: float, input: str | None = None, term_grace: float = 0,
            **kw) -> subprocess.CompletedProcess:
    """像 subprocess.run(capture_output=True),但逾時回 returncode 124、不丟例外。

    呼叫端照「失敗」處理就好(收件匣讀不到、推送被拒、整輪略過),不必另外接 TimeoutExpired。
    term_grace:逾時先送 SIGTERM、等這麼多秒讓它收尾,還不走才 SIGKILL。給收到 SIGTERM 要做事的子行程用
    (deploy 收到 SIGTERM 會把常駐程式裝回去;直接 SIGKILL 的話它停在 bootout 之後,收件攝入全停)。
    """
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if input is not None else None, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, **group_kwargs(), **kw)
    try:
        out, err = p.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        if term_grace > 0:
            kill_group(p.pid, graceful=True)
            try:
                p.wait(timeout=term_grace)
            except subprocess.TimeoutExpired:
                pass
        kill_group(p.pid)
        out, err = p.communicate()
        msg = f"{' '.join(cmd[:4])} 逾時 {timeout:g} 秒,已中止"
        err = (err + "\n" + msg) if isinstance(err, str) else msg
        return subprocess.CompletedProcess(cmd, TIMED_OUT, out, err)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)
