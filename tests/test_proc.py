"""連網子行程的逾時:2026-10-05 FUTURES 的 git ls-remote 經 ssh 卡 44 分鐘,收件與發佈都停擺。"""
from __future__ import annotations

import sys
import time

import pytest

from wiki_feeder.proc import TIMED_OUT, run_net

posix_sh = pytest.mark.skipif(sys.platform == "win32", reason="用 sh -c 起孫行程;Windows 的同一件事在 test_osplat 用 taskkill 測")


@posix_sh
def test_timeout_kills_grandchild_holding_the_pipe():
    """git 底下的 ssh 是孫行程、握著輸出管線:只砍 git 的話讀輸出照樣卡到 ssh 結束。"""
    t = time.monotonic()
    r = run_net(["sh", "-c", "sleep 30 & sleep 30"], 1, text=True)
    assert time.monotonic() - t < 10
    assert r.returncode == TIMED_OUT and "逾時" in r.stderr


@posix_sh
def test_normal_command_passes_through():
    r = run_net(["sh", "-c", "echo out; echo err >&2; exit 3"], 10, text=True)
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err\n")


def test_env_reaches_the_child():
    """呼叫端給的 env 要原樣交給子行程(攝入的 git 靠它帶設定;2026-10-30 審查)。"""
    import os
    r = run_net([sys.executable, "-c", "import os; print(os.environ.get('WIKI_FEEDER_ENV_PROBE', ''))"], 30,
                text=True, env={**os.environ, "WIKI_FEEDER_ENV_PROBE": "1"})
    assert (r.returncode, r.stdout.strip()) == (0, "1")



@pytest.mark.skipif(sys.platform == "win32", reason="Windows 的 taskkill /F 一律強制、沒有 SIGTERM 收尾(平台差異表);要它的 deploy 只在 Mac")
def test_timeout_can_give_the_child_time_to_clean_up(tmp_path):
    """deploy 收到 SIGTERM 會在 finally 把常駐程式裝回去:逾時直接 SIGKILL 就跳過了。"""
    import sys
    done = tmp_path / "cleaned"
    script = tmp_path / "child.py"
    script.write_text(
        "import signal, sys, time\n"
        f"def bye(*a):\n    open({str(done)!r}, 'w').write('x')\n    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, bye)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n")
    r = run_net([sys.executable, str(script)], 2, text=True, term_grace=10)
    assert r.returncode == TIMED_OUT and done.exists()
