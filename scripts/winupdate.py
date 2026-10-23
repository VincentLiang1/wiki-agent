"""從 zip 安裝的 Windows 朋友版自己更新(Update.bat 叫;使用者 2026-10-23 選「照 scribe2md 的 zip、Update.bat 自己下載」)。

用法(在程式資料夾,Windows 上;朋友雙擊 Update.bat 就好):
    .venv\\Scripts\\python.exe -X utf8 scripts\\winupdate.py            問 GitHub 最新版,比本機新就下載、換掉
    .venv\\Scripts\\python.exe -X utf8 scripts\\winupdate.py --zip X    用本機的 zip(實測用)

- zip 是 Release 附的 `wiki-agent-win.zip`(scripts/release_win.py 從公開 repo 那一版做的):頂層一個 `wiki-agent/`,
  裡面有 `VERSION`(tag、來源 sha)與 `MANIFEST`(每個檔一行)。**先整包驗過才動任何檔**:少了必要的檔、
  路徑跑出資料夾、清單對不上就整個不換——換到一半的程式可能根本跑不起來
- 舊版 `MANIFEST` 有、新版沒有的檔才刪(程式裡拿掉的檔);其他一律不碰:`.venv`、朋友自己放的東西
- 每個檔先寫暫存名再改名;`VERSION`、`MANIFEST` 最後寫——中途失敗的話下次照舊版本重來
- `uv sync` 不在這裡跑:這支用的就是 `.venv` 的 python,Update.bat 等它結束才 sync
- 用 git clone 裝的(有 `.git`)不走這裡,Update.bat 照舊 `git pull`
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiki_feeder import i18n  # noqa: E402
from wiki_feeder.i18n import L  # noqa: E402

PUBLIC_REPO = "VincentLiang1/wiki-agent"
ASSET = "wiki-agent-win.zip"          # ⚠️ 改名 = 已裝出去的副本找不到新版(release_win.py 用同一個名字)
TOP = "wiki-agent"
API = f"https://api.github.com/repos/{PUBLIC_REPO}/releases/latest"
REQUIRED = ("pyproject.toml", "VERSION", "MANIFEST", "Update.bat", "scripts/winupdate.py", "scripts/winsched.py",
            "src/wiki_feeder/cli.py")
NEVER = (".venv", ".git")             # zip 裡不可以有、也絕不刪的


class UpdateError(Exception):
    pass


def parse_version(text: str) -> dict[str, str]:
    out = {}
    for ln in text.splitlines():
        k, sep, v = ln.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def local_version(root: Path = ROOT) -> dict[str, str]:
    try:
        return parse_version((root / "VERSION").read_text(encoding="utf-8"))
    except OSError:
        return {}


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wiki-agent-update", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest(get=_get) -> dict:
    """{tag, url, digest}:GitHub 的 /releases/latest(不含草稿)。digest 是 GitHub 算的 sha256,沒有就空字串。"""
    info = json.loads(get(API))
    for a in info.get("assets", []):
        if a.get("name") == ASSET:
            return {"tag": info.get("tag_name", ""), "url": a["browser_download_url"],
                    "digest": (a.get("digest") or "").removeprefix("sha256:")}
    raise UpdateError(L("最新版({tag})沒有附 {asset}", tag=info.get("tag_name", "?"), asset=ASSET))


def _rel(name: str) -> str | None:
    """zip 裡的名字 → 程式資料夾裡的相對路徑(/ 分隔);資料夾本身回 None。跑出資料夾、絕對路徑一律擋下。"""
    p = PurePosixPath(name)
    if p.parts[:1] != (TOP,) or "\\" in name or ".." in p.parts or p.is_absolute():
        raise UpdateError(L("zip 裡有不該有的路徑:{name}", name=name))
    if name.endswith("/"):
        return None
    rel = PurePosixPath(*p.parts[1:])
    if not rel.parts or rel.parts[0] in NEVER:
        raise UpdateError(L("zip 裡有不該有的路徑:{name}", name=name))
    return str(rel)


def read_zip(data: bytes) -> dict[str, bytes]:
    """整包驗過才回傳 {相對路徑: 內容};有任何不對就丟 UpdateError,一個檔都不動。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        files = {}
        for info in zf.infolist():
            rel = _rel(info.filename)
            if rel is not None:
                files[rel] = zf.read(info)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise UpdateError(L("下載的 zip 壞了:{e}", e=e)) from e
    missing = [f for f in REQUIRED if f not in files]
    if missing:
        raise UpdateError(L("zip 裡少了 {files}", files=L("、").join(missing)))
    manifest = set(files["MANIFEST"].decode("utf-8").split())
    if manifest != set(files) - {"MANIFEST"}:
        raise UpdateError(L("zip 的檔案清單(MANIFEST)跟裡面的檔對不上"))
    return files


def _write(path: Path, data: bytes) -> bool:
    """內容一樣就不寫(回 False)。"""
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".wf-new")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


def apply(root: Path, files: dict[str, bytes]) -> tuple[list[str], list[str]]:
    """把新版寫進程式資料夾;回傳 (內容變了的檔, 刪掉的舊檔)。"""
    try:
        old = set((root / "MANIFEST").read_text(encoding="utf-8").split())
    except OSError:
        old = set()
    changed = [rel for rel, data in files.items() if rel not in ("VERSION", "MANIFEST") and _write(root / rel, data)]
    removed = []
    for rel in sorted(old - set(files)):
        parts = PurePosixPath(rel).parts
        p = (root / rel).resolve()
        if not parts or parts[0] in NEVER or ".." in parts or not p.is_relative_to(root.resolve()):
            continue
        if p.is_file():
            p.unlink()
            removed.append(rel)
    _write(root / "VERSION", files["VERSION"])     # 最後寫:中途失敗的話下次照舊版本重來
    _write(root / "MANIFEST", files["MANIFEST"])
    return changed, removed


def _manifest(root: Path) -> list[str]:
    try:
        return (root / "MANIFEST").read_text(encoding="utf-8").split()
    except OSError:
        return []


def backup(root: Path, dest: Path) -> int:
    """自動更新換版之前:把現在這一版(MANIFEST 列的檔與 VERSION、MANIFEST)整份複製到 dest,失敗時照它還原。"""
    if dest.exists():
        shutil.rmtree(dest)
    n = 0
    for rel in [*_manifest(root), "MANIFEST"]:
        src = root / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
            n += 1
    if not (dest / "MANIFEST").is_file():
        raise UpdateError(L("程式資料夾沒有 MANIFEST,備份不了"))
    return n


def restore(root: Path, src: Path) -> tuple[int, int]:
    """把 backup() 存的那一版寫回去;新版才有的檔刪掉。回傳 (寫回幾個, 刪掉幾個)。"""
    old = _manifest(src)
    if not old:
        raise UpdateError(L("備份裡沒有 MANIFEST,還原不了"))
    keep = set(old) | {"MANIFEST"}
    removed = 0
    for rel in _manifest(root):
        parts = PurePosixPath(rel).parts
        p = (root / rel).resolve()
        if rel not in keep and parts and parts[0] not in NEVER and p.is_relative_to(root.resolve()) and p.is_file():
            p.unlink()
            removed += 1
    written = sum(_write(root / rel, (src / rel).read_bytes()) for rel in [*old, "MANIFEST"] if (src / rel).is_file())
    return written, removed


def update(root: Path = ROOT, zip_path: Path | None = None, get=_get) -> str:
    if (root / ".git").exists():
        raise UpdateError(L("這個資料夾是用 git 裝的,Update.bat 會用 git pull 更新"))
    if zip_path is None:
        rel = latest(get)
        if rel["tag"] and rel["tag"] == local_version(root).get("tag"):
            return L("已經是最新版({tag})", tag=rel["tag"])
        print(L("下載 {tag}…", tag=rel["tag"]), flush=True)
        data = get(rel["url"], timeout=300)
        if rel["digest"] and hashlib.sha256(data).hexdigest() != rel["digest"]:
            raise UpdateError(L("下載的 zip 跟 GitHub 記的 sha256 對不上,沒有更新"))
        expect = rel["tag"]
    else:
        data, expect = zip_path.read_bytes(), ""
    files = read_zip(data)
    ver = parse_version(files["VERSION"].decode("utf-8"))
    if expect and ver.get("tag") != expect:
        raise UpdateError(L("zip 裡的版本({got})不是最新版({want})", got=ver.get("tag", "?"), want=expect))
    changed, removed = apply(root, files)
    return L("已更新到 {tag}(換了 {n} 個檔、拿掉 {m} 個舊檔)", tag=ver.get("tag", "?"), n=len(changed), m=len(removed))


def main(argv: list[str] | None = None) -> int:
    from winsched import config_lang   # 同一個資料夾;語言照設定檔
    i18n.set_lang(config_lang())
    ap = argparse.ArgumentParser(prog="winupdate", description=L("從 GitHub 下載 wiki-agent 的新版、換掉程式資料夾裡的檔"))
    ap.add_argument("--zip", type=Path, help=L("用本機的 zip(實測用)"))
    ap.add_argument("--backup", type=Path, help=L("只把現在這一版備份到這個資料夾(自動更新用)"))
    ap.add_argument("--restore", type=Path, help=L("只把備份的那一版寫回來(自動更新失敗時)"))
    a = ap.parse_args(argv)
    try:
        if a.backup:
            print(L("已備份 {n} 個檔", n=backup(ROOT, a.backup)))
            return 0
        if a.restore:
            n, m = restore(ROOT, a.restore)
            print(L("已還原 {n} 個檔、拿掉 {m} 個新版的檔", n=n, m=m))
            return 0
        print(update(ROOT, a.zip))
    except (UpdateError, OSError, ValueError) as e:
        print(L("更新失敗:{e}", e=e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
