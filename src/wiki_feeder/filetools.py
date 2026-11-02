"""攝入時 claude 能用的寫檔指令:重產講義(make-handout)、把圖片轉成 jpg 放進頁面的 images/(add-image)、
從 index.md 重產各群組的 README.md(group-readme,跟 make-handout 同一套做法,2026-11-02 加)。

和 pagetools 一樣,參數由程式檢查過才動手,claude 只能給「哪一頁」「放到哪」:
- make-handout 跑的是公事庫 **origin 上那一版**的 tools/ 腳本(公事庫 CLAUDE.md 規定講義一律用
  tools/make_handout.py 重產、不手改)。不跑工作目錄那一份:claude 改得到它,改完再跑就等於能執行任意程式。
  origin 那一版 claude 推不上去,攝入 commit 動到 tools/ 一律 STOP(ingest.STOP_GUARDED),驗證過才推,
  所以那一版只有人改得到。產出先寫在庫外的暫存目錄,腳本自己的檢查(assert)都過了才放進 handouts/。
- add-image 只收原件樹與轉寫快取裡的圖,只寫到 `Wiki_Pages/…/images/<頁名>/<檔名>.jpg`、絕不覆蓋
  (公事庫 CLAUDE.md〈圖片管理〉:副檔名一律 .jpg,其他格式用 PIL 轉;改寫既有的圖會讓攝入 STOP)。

2026-10-12～15 的攝入因為沒有這兩個指令,講義沒重產、簡報圖表沒放進 images/,只能寫「未驗」。
"""
from __future__ import annotations

import difflib
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .i18n import L
from .osplat import WINDOWS
from .pagetools import PageToolError, git_text, page_path

HANDOUT_SCRIPT = "make_handout.py"
HANDOUT_TIMEOUT = 120
README_SCRIPT = "make_group_readme.py"
README_NAME = "README.md"
DIFF_MAX_LINES = 200
JPEG_QUALITY = 90
_HANDOUT_OUT = re.compile(r"handouts/[^/]+\.md")
_IMAGE_DEST = re.compile(r"Wiki_Pages/(?:[^/]+/)+images/[^/ ]+/[^/]+\.jpg")
_JPEG = (".jpg", ".jpeg")


def make_handout(repo: Path, branch: str, src: str, out: str, flags: list[str]) -> str:
    """用 origin/<branch> 那一版的 tools/ 腳本,把 Wiki_Pages/ 的來源頁重產成 handouts/ 的講義。

    flags 原樣交給腳本(cli 只收 --drop-source、--drop、--drop-alert、--no-urls、--embed-images)。
    講義原本就有的話,印出新舊差異:哪一版講義用了哪些參數沒有記在任何地方,參數漏了(例如來源列、
    外部網址又跑回去)要看差異才知道。"""
    src_rel, out_rel = page_path(repo, src), page_path(repo, out)
    if not (src_rel.startswith("Wiki_Pages/") and src_rel.endswith(".md") and (repo / src_rel).is_file()):
        raise PageToolError(L("{path} 不是 Wiki_Pages/ 底下的頁面", path=src))
    if not _HANDOUT_OUT.fullmatch(out_rel):
        raise PageToolError(L("{path} 不是 handouts/<頁名>.md", path=out))
    with tempfile.TemporaryDirectory(prefix="wiki-feeder-handout-") as tmp:
        tools = Path(tmp) / "tools"
        tools.mkdir()
        ref = f"origin/{branch}"
        names = [n for n in git_text(repo, "ls-tree", "-z", "--name-only", f"{ref}:tools/").split("\0")
                 if n.endswith(".py") and "/" not in n]
        if HANDOUT_SCRIPT not in names:
            raise PageToolError(L("{ref} 的 tools/ 裡沒有 {script}", ref=ref, script=HANDOUT_SCRIPT))
        for n in names:   # 腳本會 import 同目錄的模組(改寫表),整個 tools/ 的 .py 都取出來
            (tools / n).write_bytes(_blob(repo, f"{ref}:tools/{n}"))
        dst = Path(tmp) / "out.md"
        # -E -s:不吃環境變數與使用者的 site-packages;不加 -P:腳本要 import 同目錄的改寫表(目錄裡只有 origin 那一版)。
        # Windows 另帶 -X utf8:-E 連 PYTHONUTF8 也不吃,腳本會以 cp950 印出錯誤訊息、這裡解成亂碼(2026-10-19 實測)
        utf8 = ["-X", "utf8"] if WINDOWS else []
        try:
            r = subprocess.run([sys.executable, "-E", "-s", *utf8, str(tools / HANDOUT_SCRIPT), "--src",
                                str((repo / src_rel).resolve()), "--out", str(dst), *flags],
                               cwd=tmp, capture_output=True, timeout=HANDOUT_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            raise PageToolError(L("{script} 執行失敗:{e}", script=HANDOUT_SCRIPT, e=e)) from e
        if r.returncode != 0 or not dst.is_file():
            err = (r.stderr or r.stdout).decode("utf-8", "replace").strip()
            raise PageToolError(L("{script} 失敗(講義沒有改):{err}", script=HANDOUT_SCRIPT, err=err[-1500:]))
        # 腳本寫 CRLF(給 Windows 用);庫裡追蹤的講義是 LF(Windows 的 git commit 時轉掉)。Mac 沒有這道轉換,
        # 照寫的話整份講義每一行都算改過(2026-10-15 對真的公事庫試跑:內容沒變,位元組全不同)
        new = dst.read_bytes().replace(b"\r\n", b"\n")
    target = repo / out_rel
    old = target.read_bytes() if target.is_file() else None
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(new)
    if old is None:
        return L("已產生 {path}(新講義)", path=out_rel)
    if old == new:
        return L("{path} 沒有變(來源頁的修改不影響講義)", path=out_rel)
    diff = list(difflib.unified_diff(old.decode("utf-8", "replace").splitlines(),
                                     new.decode("utf-8", "replace").splitlines(), L("舊講義"), L("新講義"),
                                     lineterm=""))
    more = (L("\n⋯(差異共 {n} 行,只印前 {limit} 行)", n=len(diff), limit=DIFF_MAX_LINES)
            if len(diff) > DIFF_MAX_LINES else "")
    return (L("已重產 {path},與舊講義的差異(新出現來源列、外部網址、對內章節的話,是參數跟舊版不同,"
              "補上參數再跑一次):\n", path=out_rel) + "\n".join(diff[:DIFF_MAX_LINES]) + more)


def has_readme_script(repo: Path, branch: str) -> bool:
    """origin/<branch> 的 tools/ 有沒有群組 README 腳本(沒有 tools/ 也算沒有:朋友版、還沒加腳本的庫)。"""
    try:
        names = git_text(repo, "ls-tree", "-z", "--name-only", f"origin/{branch}:tools/").split("\0")
    except PageToolError:
        return False
    return README_SCRIPT in names


def regen_group_readme(repo: Path, branch: str) -> tuple[list[str], list[str], str]:
    """用 origin/<branch> 那一版的 tools/make_group_readme.py,從 Wiki_Pages/index.md 重產各群組的 README.md
    (公事庫、個人庫的 CLAUDE.md 都規定:README 是 index 的切片,動到 index 就重跑)。
    回傳 (改了的檔, 其中新建的檔, 腳本印的訊息),路徑都是庫裡的相對路徑。

    跟 make-handout 一樣在庫外的暫存目錄跑:放進 index.md、每個群組資料夾(空的)與既有的 README.md,
    腳本自己的檢查都過了,才把有變的 README.md 與 index.md(它維護「本組清單」連結行)寫回庫裡;
    其他檔一律不帶回。腳本失敗時庫裡什麼都不動。"""
    wp = repo / "Wiki_Pages"
    if not (wp / "index.md").is_file():
        raise PageToolError(L("{repo} 沒有 Wiki_Pages/index.md", repo=repo.name))
    groups = sorted(d.name for d in wp.iterdir() if d.is_dir() and not d.is_symlink())
    with tempfile.TemporaryDirectory(prefix="wiki-feeder-readme-") as tmp:
        root = Path(tmp)
        ref = f"origin/{branch}"
        if README_SCRIPT not in git_text(repo, "ls-tree", "-z", "--name-only", f"{ref}:tools/").split("\0"):
            raise PageToolError(L("{ref} 的 tools/ 裡沒有 {script}", ref=ref, script=README_SCRIPT))
        (root / "tools").mkdir()
        (root / "tools" / README_SCRIPT).write_bytes(_blob(repo, f"{ref}:tools/{README_SCRIPT}"))
        names = ["index.md", *(f"{g}/{README_NAME}" for g in groups)]
        (root / "Wiki_Pages").mkdir()
        for g in groups:
            (root / "Wiki_Pages" / g).mkdir()
        for n in names:
            if (wp / n).is_file() and not (wp / n).is_symlink():
                (root / "Wiki_Pages" / n).write_bytes((wp / n).read_bytes())
        # 只用標準函式庫,-I:不吃環境變數、使用者的 site-packages,也不把腳本所在目錄放進模組搜尋路徑
        utf8 = ["-X", "utf8"] if WINDOWS else []
        try:
            r = subprocess.run([sys.executable, "-I", *utf8, str(root / "tools" / README_SCRIPT)],
                               cwd=tmp, capture_output=True, timeout=HANDOUT_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            raise PageToolError(L("{script} 執行失敗:{e}", script=README_SCRIPT, e=e)) from e
        msg = (r.stdout or r.stderr).decode("utf-8", "replace").strip()
        if r.returncode != 0:
            raise PageToolError(L("{script} 失敗(README 與 index.md 都沒有改):{err}",
                                  script=README_SCRIPT, err=msg[-1500:]))
        new = {n: (root / "Wiki_Pages" / n).read_bytes() for n in names if (root / "Wiki_Pages" / n).is_file()}
    for n in new:   # 先全部查過才寫:寫到一半才擋,index.md 改了、README 沒改
        if (wp / n).is_symlink():
            raise PageToolError(L("{path} 是捷徑(symlink),不寫", path=f"Wiki_Pages/{n}"))
    changed, created = [], []
    for n, data in new.items():
        target = wp / n
        if not target.is_file() or target.read_bytes() != data:
            changed.append(f"Wiki_Pages/{n}")
            if not target.is_file():
                created.append(f"Wiki_Pages/{n}")
            target.write_bytes(data)
    return changed, created, msg


def group_readme(repo: Path, branch: str) -> str:
    """攝入的 claude 用的 group-readme(公事庫):重產,印出改了哪些檔。"""
    changed, _, msg = regen_group_readme(repo, branch)
    if not changed:
        return L("README 與 index.md 都是最新的,沒有改({msg})", msg=msg)
    return L("已重產 {n} 個檔({msg}),跟頁面一起 commit:\n", n=len(changed), msg=msg) + "\n".join(changed)


def _blob(repo: Path, spec: str) -> bytes:
    try:
        r = subprocess.run(["git", "cat-file", "blob", spec], cwd=repo, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise PageToolError(L("git 執行失敗:{e}", e=e)) from e
    if r.returncode != 0:
        raise PageToolError(r.stderr.decode("utf-8", "replace").strip() or L("讀不到 {spec}", spec=spec))
    return r.stdout


def add_image(repo: Path, sources: list[Path], src: str, dest: str) -> str:
    """把原件樹或轉寫快取裡的一張圖轉成 jpg,放到 Wiki_Pages/…/images/<頁名>/<檔名>.jpg。
    .jpg／.jpeg 原樣複製;其他格式用 PIL 轉(透明的部分墊白底,動畫取第一格)。目的地已經有檔就不做。"""
    p = Path(src).resolve()
    if not any(p.is_relative_to(s.resolve()) for s in sources) or not p.is_file():
        raise PageToolError(L("{path} 不是原件樹或轉寫快取裡的檔", path=src))
    dest_rel = page_path(repo, dest)
    if not _IMAGE_DEST.fullmatch(dest_rel):
        raise PageToolError(L("{path} 不是 Wiki_Pages/<群組>/images/<頁名>/<檔名>.jpg(頁名不得有空格)", path=dest))
    target = repo / dest_rel
    if target.exists():
        raise PageToolError(L("{path} 已經有檔,不覆蓋(換一個檔名)", path=dest_rel))
    if p.suffix.lower() in _JPEG:
        data = p.read_bytes()
    else:
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(p) as im:
                im.seek(0)
                if im.mode in ("RGBA", "LA", "P"):
                    rgba = im.convert("RGBA")
                    rgb = Image.new("RGB", rgba.size, "white")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgb = im.convert("RGB")
                buf = io.BytesIO()
                rgb.save(buf, "JPEG", quality=JPEG_QUALITY)
                data = buf.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as e:
            raise PageToolError(L("{name} 讀不成圖片:{e}", name=p.name, e=e)) from e
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "xb") as f:   # x:目的地在這中間冒出來也不覆蓋
        f.write(data)
    return L("已放進 {path}({kb} KB)", path=dest_rel, kb=len(data) // 1024)
