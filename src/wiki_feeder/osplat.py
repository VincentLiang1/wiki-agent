"""Mac 與 Windows 不一樣的幾件事,集中在這裡(朋友的 Windows 版,使用者 2026-10-19):

- 鎖檔:Mac 用 flock(有共享鎖);Windows 用 msvcrt.locking(只有獨佔)。共享鎖只用在 deploy.lock,
  Windows 不 deploy(朋友更新是 git pull),所以 Windows 上 deploy_guard 一律放行
- 逾時砍整組子行程:Mac 開新 session、killpg;Windows 開新行程群組、taskkill /T /F
- 不含睡眠的時鐘:Mac 的 CLOCK_UPTIME_RAW;Windows 沒有 clock_gettime,用 monotonic
- 雲端佔位檔:Mac 看 st_flags 的 SF_DATALESS、用 brctl 要求下載;Windows 看檔案屬性
  RECALL_ON_DATA_ACCESS／RECALL_ON_OPEN／OFFLINE、用 attrib +P(「永遠保留在此裝置上」)要求下載
- 寄信密碼:Mac 鑰匙圈(/usr/bin/security);Windows 認證管理員(keyring)
- Windows 才有的:fsync 要可寫的 handle;排程的 pythonw 底下子行程要 CREATE_NO_WINDOW(否則每個都閃一個視窗)、
  sys.stdin／stdout／stderr 是 None(要補上 devnull,否則一輪都跑不起來)

測試在 Mac 跑:Windows 分支能用參數換掉平台的就換掉測(WINDOWS 旗標),真的要 Windows API 的在 Windows 上測。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

WINDOWS = sys.platform == "win32"

SF_DATALESS = 0x40000000                       # macOS:內容還在雲端(iCloud 佔位檔)
# Windows 雲端檔案(Cloud Files API,iCloud for Windows 與 OneDrive 都用它)的佔位檔屬性
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
WIN_PLACEHOLDER = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


# -- 鎖檔 --------------------------------------------------------------------------

def try_lock(f, shared: bool = False) -> bool:
    """非阻塞地鎖住已開啟的檔;拿不到回 False。行程結束時系統會自動釋放,當掉也不會留下死鎖。"""
    if WINDOWS:
        import msvcrt
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(f, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def unlock(f) -> None:
    if WINDOWS:
        import msvcrt
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl
    fcntl.flock(f, fcntl.LOCK_UN)


# -- 檔案 --------------------------------------------------------------------------

def fsync_path(path) -> None:
    """把已寫好的檔確實落到磁碟。Windows 的 fsync(_commit)要可寫的 handle,唯讀開的會 EBADF
    (2026-10-19 Windows 實測:每一筆取件都失敗、來源保留),所以用 r+b 開;Mac 唯讀開就行。"""
    with open(path, "r+b" if WINDOWS else "rb") as f:
        os.fsync(f.fileno())


# -- 子行程 ------------------------------------------------------------------------

def group_kwargs() -> dict:
    """開新的行程群組:逾時時才砍得掉孫行程(git 底下的 ssh,proc.py)。"""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


CREATE_NEW_CONSOLE, DETACHED_PROCESS, CREATE_NO_WINDOW = 0x10, 0x8, 0x08000000   # Mac 的 subprocess 沒有這些常數


def no_window_flags(flags: int) -> int:
    """子行程的 creationflags 加上 CREATE_NO_WINDOW;本來就要新主控台或不要主控台的不動(兩者不能並用)。"""
    if flags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS):
        return flags
    return flags | CREATE_NO_WINDOW


def hide_child_consoles(windows: bool = WINDOWS) -> bool:
    """排程跑的 pythonw.exe 沒有主控台:它叫的 git、claude、doc2md 每一個都會另開一個看得見的主控台視窗,
    每分鐘閃一次(2026-10-19 Windows 實測,CREATE_NEW_PROCESS_GROUP 也一樣)。自己沒有主控台時,之後所有
    子行程一律加 CREATE_NO_WINDOW——孫行程(claude 底下的 git)跟著沒有視窗。有主控台(手動執行)時不動。
    回傳有沒有套用。"""
    if not windows:
        return False
    import ctypes
    if ctypes.windll.kernel32.GetConsoleWindow():
        return False
    init = subprocess.Popen.__init__
    if getattr(init, "_no_window", False):
        return True

    def _init(self, *args, **kw):
        kw["creationflags"] = no_window_flags(kw.get("creationflags", 0))
        init(self, *args, **kw)

    _init._no_window = True
    subprocess.Popen.__init__ = _init
    return True


def fill_missing_std_streams() -> list[str]:
    """工作排程器跑的 pythonw.exe 沒有 stdin／stdout／stderr(都是 None):`sys.stderr.isatty()` 一呼叫就
    AttributeError,每一輪在開 log 之前就結束(結束碼 1、log 一行都沒有;2026-10-20 Windows 實測)。
    換成 os.devnull;回傳換了哪幾個。Mac 的 launchd 一律有串流,不會換到。"""
    filled = []
    for name, mode in (("stdin", "r"), ("stdout", "w"), ("stderr", "w")):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, mode, encoding="utf-8"))
            filled.append(name)
    return filled


def kill_group(pid: int, graceful: bool = False) -> None:
    """砍整組。graceful:先送 SIGTERM 讓它收尾(只有 Mac;Windows 的 taskkill 一律強制)。"""
    if WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGTERM if graceful else signal.SIGKILL)
    except ProcessLookupError:
        pass


# -- 時鐘 --------------------------------------------------------------------------

def uptime() -> float:
    """不含睡眠的秒數(Mac 的 CLOCK_UPTIME_RAW)。Windows 沒有 clock_gettime:用 monotonic(含睡眠;
    只給看門狗算多久沒心跳,Windows 版不跑看門狗)。"""
    if not hasattr(time, "clock_gettime"):
        return time.monotonic()
    return time.clock_gettime(getattr(time, "CLOCK_UPTIME_RAW", time.CLOCK_MONOTONIC))


# -- 雲端佔位檔 ---------------------------------------------------------------------

def is_placeholder(st: os.stat_result, windows: bool = WINDOWS) -> bool:
    """內容還在雲端、本機只有佔位檔。⚠️ 佔位檔照樣讀得到大小,不先擋的話會被當成一般檔去算雜湊、複製
    (讀它會觸發下載、卡在讀取上)。"""
    if windows:
        return bool(getattr(st, "st_file_attributes", 0) & WIN_PLACEHOLDER)
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


def download_cmd(path: str, windows: bool = WINDOWS) -> list[str]:
    """要求雲端把這個檔下載到本機的指令。Windows:attrib +P 就是檔案總管的「永遠保留在此裝置上」。"""
    if windows:
        return ["attrib", "+P", path]
    return ["brctl", "download", path]


# -- 寄信密碼 ----------------------------------------------------------------------

def secret(service: str, account: str, windows: bool = WINDOWS) -> str | None:
    """Mac:鑰匙圈(由 /usr/bin/security 建立的項目它讀不會跳授權視窗,launchd 底下也讀得到);
    Windows:認證管理員的「一般認證」(keyring,目標名稱 `<account>@<service>`)。找不到回 None。"""
    if windows:
        try:
            import keyring
        except ImportError:
            return None
        return keyring.get_password(service, account) or None
    r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


# -- 解音檔(量長段空白) -------------------------------------------------------------

def decode_cmd(src: str, out_wav: str, rate: int, ffmpeg: str = "", windows: bool = WINDOWS) -> list[str]:
    """把音檔解成單聲道 16-bit WAV。Mac 用系統的 afconvert;Windows 沒有,用 meeting-scribe 自帶的 ffmpeg
    (它的 static-ffmpeg 套件下載到 venv 裡)。"""
    if windows:
        if not ffmpeg:
            raise RuntimeError("沒有 ffmpeg:設定檔 [tools] ffmpeg 填 meeting-scribe 裡的 ffmpeg.exe")
        return [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", str(rate),
                "-acodec", "pcm_s16le", "-f", "wav", out_wav]
    return ["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", src, out_wav]
