"""知識庫、原件資料夾是不是在雲端同步資料夾裡(安裝時提醒用,使用者 2026-10-27,spec §5.15)。

`sync_kind` 是純函式:平台、家目錄、環境變數與系統查得到的東西(`Probe`)都當參數傳,Windows 的判斷在 Mac 上也測得到;
`probe` 才真的去問系統(Mac 的 Finder 設定、Windows 的 Known Folder、Dropbox 的 info.json、磁碟標籤)。
路徑由呼叫的人先 resolve(含符號連結),這裡只比字面:Windows 不分大小寫。收件匣 `_WikiBox` 本來就在 iCloud 雲碟,不查它。
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from .i18n import N_

ONEDRIVE, ICLOUD, DROPBOX, GDRIVE, BOX, OTHER = (N_("OneDrive"), N_("iCloud 雲碟"), N_("Dropbox"),
                                                 N_("Google Drive"), N_("Box"), N_("雲端同步資料夾"))
ICLOUD_DESKTOP = N_("被 iCloud 同步的「文件／桌面」")
ONEDRIVE_DESKTOP = N_("被 OneDrive 接管的「文件／桌面」")
# Mac「系統設定 → iCloud → iCloud 雲碟 → 桌面與文件檔案夾」打開時,Finder 設定裡這兩個是 1(2026-10-27 這台關著,實測是 0)
FINDER_KEYS = ("FXICloudDriveDesktop", "FXICloudDriveDocuments")
ONEDRIVE_ENV = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
GDRIVE_PARTS = ("my drive", "我的雲端硬碟", "我的云端硬盘")


@dataclass(frozen=True)
class Probe:
    """系統查得到的東西。finder:Mac 的 FINDER_KEYS → "1"/"0"/None(讀不到);known:Windows「文件」「桌面」的實際位置;
    dropbox:Dropbox 自己記的資料夾;labels:Windows 磁碟機代號("G:")→ 磁碟標籤。"""
    finder: dict[str, str | None] = field(default_factory=dict)
    known: dict[str, str] = field(default_factory=dict)
    dropbox: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)


def _pure(platform: str, p) -> PurePath:
    return PureWindowsPath(str(p)) if platform == "win32" else PurePosixPath(str(p))


def _parts(platform: str, p) -> tuple[str, ...]:
    parts = _pure(platform, p).parts
    return tuple(x.casefold() for x in parts) if platform == "win32" else parts


def _under(platform: str, p, root) -> bool:
    a, b = _parts(platform, p), _parts(platform, root)
    return len(b) > 1 and a[:len(b)] == b


def _cloudstorage(name: str) -> str:
    """~/Library/CloudStorage/ 底下的資料夾名:OneDrive-個人、Dropbox、GoogleDrive-帳號、Box-Box……"""
    n = name.casefold()
    for prefix, kind in (("onedrive", ONEDRIVE), ("dropbox", DROPBOX), ("googledrive", GDRIVE), ("box", BOX)):
        if n.startswith(prefix):
            return kind
    return OTHER


def sync_kind(path, platform: str, home, env: dict[str, str], probe: Probe) -> str | None:
    """path 在哪一種雲端同步資料夾裡(回傳 N_ 登記過的名稱,用的時候再 L());不在就 None。"""
    pp = _parts(platform, path)
    home = _pure(platform, home)
    if platform == "darwin":
        lib = home / "Library"
        storage = _parts(platform, lib / "CloudStorage")
        if pp[:len(storage)] == storage and len(pp) > len(storage):
            return _cloudstorage(pp[len(storage)])
        if _under(platform, path, lib / "Mobile Documents"):
            return ICLOUD
        for name, kind in (("Dropbox", DROPBOX), ("Google Drive", GDRIVE), ("OneDrive", ONEDRIVE), ("Box", BOX)):
            if _under(platform, path, home / name):       # 舊版直接放在家目錄的
                return kind
        for name, key in (("Desktop", "FXICloudDriveDesktop"), ("Documents", "FXICloudDriveDocuments")):
            # 讀不到設定也提醒(使用者 2026-10-27:查不準寧可提醒);明確是 0 才不提醒
            if _under(platform, path, home / name) and probe.finder.get(key) != "0":
                return ICLOUD_DESKTOP
        return None
    if platform == "win32":
        # Windows 的環境變數不分大小寫,dict(os.environ) 的鍵卻是全大寫(ONEDRIVE)
        env = {k.casefold(): v for k, v in env.items()}
        for k in ONEDRIVE_ENV:
            if env.get(k.casefold()) and _under(platform, path, env[k.casefold()]):
                return ONEDRIVE
        for name in ("Desktop", "Documents"):
            real = probe.known.get(name)
            # 被 OneDrive 接管:實際位置在 OneDrive 底下,只比實際位置。字面上的 %USERPROFILE%\Documents 這時是
            # 另一個本機資料夾、不會被同步(2026-10-28 在 Windows 11 實測,不是 junction);若是指過去的連結,
            # 呼叫的人 resolve 之後本來就落在實際位置
            if real and any(x.startswith("onedrive") for x in _parts(platform, real)) and _under(platform, path, real):
                return ONEDRIVE_DESKTOP
        if any(_under(platform, path, home / n) for n in ("iCloudDrive", "iCloud Drive")):
            return ICLOUD
        if any(_under(platform, path, d) for d in (*probe.dropbox, home / "Dropbox")):
            return DROPBOX
        drive = _pure(platform, path).drive.upper()
        if (_under(platform, path, home / "Google Drive") or any(x in GDRIVE_PARTS for x in pp)
                or probe.labels.get(drive, "").casefold() == "google drive"):
            return GDRIVE
        if _under(platform, path, home / "Box"):
            return BOX
        return None
    return None


# -- 真的去問系統 ----------------------------------------------------------------------

def _finder(key: str, run=subprocess.run) -> str | None:
    try:
        r = run(["/usr/bin/defaults", "read", "com.apple.finder", key], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _known_folders() -> dict[str, str]:
    """SHGetKnownFolderPath:「桌面」「文件」的實際位置(被 OneDrive 接管時在 OneDrive 底下)。"""
    import ctypes
    from ctypes import wintypes
    import uuid

    ids = {"Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7"}
    out = {}
    for name, guid in ids.items():
        g = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
        p = wintypes.LPWSTR()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            out[name] = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
    return out


def _drive_labels() -> dict[str, str]:
    """只看本機磁碟(DRIVE_FIXED、RAMDISK;Google Drive 的虛擬磁碟也是本機):抽取式的沒放片子會跳「磁碟機中沒有磁片」,
    斷線的網路磁碟會卡住。錯誤視窗另外用 SetErrorMode 關掉。"""
    import ctypes
    import string

    k = ctypes.windll.kernel32
    k.SetErrorMode(0x0001)                     # SEM_FAILCRITICALERRORS
    mask, out = k.GetLogicalDrives(), {}
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask >> i & 1 or k.GetDriveTypeW(f"{letter}:\\") not in (3, 6):
            continue
        buf = ctypes.create_unicode_buffer(261)
        if k.GetVolumeInformationW(f"{letter}:\\", buf, 261, None, None, None, None, 0):
            out[f"{letter}:"] = buf.value
    return out


def _dropbox(env: dict[str, str]) -> tuple[str, ...]:
    """Dropbox 把資料夾位置記在 info.json(個人、商務各一個 path)。"""
    found = []
    for base in (env.get("APPDATA"), env.get("LOCALAPPDATA")):
        try:
            data = json.loads(Path(base, "Dropbox", "info.json").read_text(encoding="utf-8")) if base else {}
        except (OSError, ValueError):
            continue
        found += [v["path"] for v in data.values() if isinstance(v, dict) and v.get("path")]
    return tuple(found)


def probe(platform: str, env: dict[str, str] | None = None, home: Path | None = None) -> Probe:
    """查一次系統;查不到的就留空(Mac 的 Finder 設定留 None = 照「讀不到」提醒)。只是提醒用:查的時候出任何錯都不可讓安裝當掉。"""
    env = dict(os.environ) if env is None else env
    home = Path.home() if home is None else home
    if platform == "darwin":
        finder = {k: _finder(k) for k in FINDER_KEYS}
        # 第二個訊號:打開「桌面與文件」時 iCloud 雲碟裡會有 Desktop、Documents(設定讀成 0 卻是開著的,也照樣提醒)
        drive = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        for key, name in zip(FINDER_KEYS, ("Desktop", "Documents")):
            if (drive / name).is_dir():
                finder[key] = "1"
        return Probe(finder=finder)
    if platform == "win32":
        known, labels = {}, {}
        try:
            known = _known_folders()
        except Exception:  # noqa: BLE001 —— 查不到就不提醒這一種,不讓安裝當掉
            pass
        try:
            labels = _drive_labels()
        except Exception:  # noqa: BLE001
            pass
        return Probe(known=known, dropbox=_dropbox(env), labels=labels)
    return Probe()
