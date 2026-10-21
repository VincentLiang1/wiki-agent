"""攝入時 claude 能用的寫檔指令:make-handout、add-image(filetools.py)。

make-handout 只跑公事庫 origin 上那一版的 tools/ 腳本;add-image 只從原件樹與轉寫快取拿圖、只寫頁面的 images/、不覆蓋。
"""
from __future__ import annotations

import io

import pytest
from conftest import git
from PIL import Image

from wiki_feeder.filetools import add_image, make_handout
from wiki_feeder.pagetools import PageToolError

# 假的 make_handout.py:照真的那支的樣子——import 同目錄的改寫表、先寫產出再 assert、--drop-source 砍來源列
SCRIPT = '''import argparse
from handout_rewrites import WORD
ap = argparse.ArgumentParser()
ap.add_argument("--src"); ap.add_argument("--out"); ap.add_argument("--drop-source", action="store_true")
a = ap.parse_args()
s = open(a.src, encoding="utf-8").read().replace("本庫", WORD)
if a.drop_source:
    s = "".join(l for l in s.splitlines(keepends=True) if not l.startswith("來源"))
open(a.out, "w", encoding="utf-8", newline="\\r\\n").write(s)
assert "壞掉" not in s, "來源頁已改版、對不到"
'''


@pytest.fixture
def repo(tmp_path):
    remote, r = tmp_path / "FWIKI.git", tmp_path / "FWIKI"
    git("init", "--bare", "-q", "-b", "master", str(remote), cwd=tmp_path)
    git("init", "-q", "-b", "master", str(r), cwd=tmp_path)
    (r / "Wiki_Pages" / "群組").mkdir(parents=True)
    (r / "Wiki_Pages" / "群組" / "頁.md").write_text("# 頁\n來源:FRaw_Sources\\a.pdf\n本庫的判讀\n", encoding="utf-8")
    (r / "tools").mkdir()
    (r / "tools" / "make_handout.py").write_text(SCRIPT, encoding="utf-8")
    (r / "tools" / "handout_rewrites.py").write_text('WORD = "我們"\n', encoding="utf-8")
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "init", cwd=r)
    git("remote", "add", "origin", str(remote), cwd=r)
    git("push", "-q", "-u", "origin", "master", cwd=r)
    return r


def test_handout_is_made_by_the_script_on_origin_not_the_working_copy(repo, tmp_path):
    """工作目錄那份 claude 改得到:改完再跑就等於能執行任意程式。跑的一定是 origin 上那一版。"""
    (repo / "tools" / "make_handout.py").write_text(f"open({str(tmp_path / 'pwned')!r}, 'w')\n", encoding="utf-8")
    git("commit", "-q", "-am", "改腳本", cwd=repo)                     # 本機 commit 了也一樣:還沒推上去
    out = make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", ["--drop-source"])
    assert "新講義" in out
    assert not (tmp_path / "pwned").exists()
    # 同目錄的改寫表也取了;換行跟庫裡追蹤的講義一樣是 LF(腳本寫 CRLF,照寫的話每一行都算改過)
    assert (repo / "handouts" / "頁.md").read_bytes() == "# 頁\n我們的判讀\n".encode()


def test_handout_diff_shows_a_missing_flag(repo):
    """哪一版講義用了哪些參數沒有記在任何地方:參數漏了,差異裡看得到來源列跑回去。"""
    make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", ["--drop-source"])
    out = make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", [])
    assert "+來源:FRaw_Sources\\a.pdf" in out
    assert "沒有變" in make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", [])


def test_failed_handout_script_leaves_the_old_handout(repo):
    """腳本先寫產出才 assert:寫在庫外的暫存目錄,失敗時庫裡的講義不動、也不留半成品。"""
    make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", [])
    before = (repo / "handouts" / "頁.md").read_bytes()
    (repo / "Wiki_Pages" / "群組" / "頁.md").write_text("壞掉\n", encoding="utf-8")
    with pytest.raises(PageToolError, match="對不到"):
        make_handout(repo, "master", "Wiki_Pages/群組/頁.md", "handouts/頁.md", [])
    assert (repo / "handouts" / "頁.md").read_bytes() == before
    assert [p.name for p in (repo / "handouts").iterdir()] == ["頁.md"]


@pytest.mark.parametrize(("src", "out"), [
    ("Wiki_Pages/群組/頁.md", "Wiki_Pages/群組/頁.md"),        # 蓋掉來源頁
    ("Wiki_Pages/群組/頁.md", "tools/make_handout.py"),        # 蓋掉腳本
    ("Wiki_Pages/群組/頁.md", "handouts/子/頁.md"),
    ("Wiki_Pages/群組/頁.md", "../外面.md"),
    ("tools/handout_rewrites.py", "handouts/頁.md"),           # 來源只收 Wiki_Pages/ 的頁
    ("../外面.md", "handouts/頁.md"),                          # 庫外的檔不能被抄進講義
])
def test_handout_paths_are_confined(repo, tmp_path, src, out):
    (tmp_path / "外面.md").write_text("外面", encoding="utf-8")
    with pytest.raises(PageToolError):
        make_handout(repo, "master", src, out, [])
    assert not (repo / "handouts").exists() and (tmp_path / "外面.md").read_text(encoding="utf-8") == "外面"


def _png(path, mode="RGBA"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, (8, 8), (255, 0, 0, 0) if mode == "RGBA" else (255, 0, 0)).save(path)
    return path


def test_add_image_converts_to_jpg_into_the_page_images_folder(repo, tmp_path):
    raw = tmp_path / "FRaw_Sources"
    src = _png(raw / "群組" / "簡報.assets" / "image1.png")
    dest = "Wiki_Pages/群組/images/頁/架構圖.jpg"
    assert "已放進" in add_image(repo, [raw], str(src), dest)
    with Image.open(repo / dest) as im:
        assert im.format == "JPEG" and im.getpixel((0, 0)) == (255, 255, 255)   # 透明的地方墊白底
    jpg = raw / "群組" / "照片.JPEG"
    jpg.write_bytes(_jpeg_bytes())
    add_image(repo, [raw], str(jpg), "Wiki_Pages/群組/images/頁/照片.jpg")
    assert (repo / "Wiki_Pages/群組/images/頁/照片.jpg").read_bytes() == jpg.read_bytes()   # jpg 原樣放


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, "JPEG")
    return buf.getvalue()


def test_add_image_never_overwrites(repo, tmp_path):
    """改寫既有的圖會讓攝入 STOP(二進位檔被改寫);目的地已經有檔就不做,叫它換檔名。"""
    raw = tmp_path / "FRaw_Sources"
    src = _png(raw / "a.png")
    dest = repo / "Wiki_Pages/群組/images/頁/圖.jpg"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")
    with pytest.raises(PageToolError, match="不覆蓋"):
        add_image(repo, [raw], str(src), "Wiki_Pages/群組/images/頁/圖.jpg")
    assert dest.read_bytes() == b"old"


@pytest.mark.parametrize("dest", ["Wiki_Pages/群組/頁.jpg", "Wiki_Pages/群組/images/有 空格/圖.jpg",
                                  "Wiki_Pages/群組/images/頁/圖.png", "Wiki_Pages/群組/頁.md",
                                  "tools/images/頁/圖.jpg", "../images/頁/圖.jpg", ".git/images/頁/圖.jpg"])
def test_add_image_destination_must_be_a_page_images_folder(repo, tmp_path, dest):
    raw = tmp_path / "FRaw_Sources"
    with pytest.raises(PageToolError):
        add_image(repo, [raw], str(_png(raw / "a.png")), dest)


def test_add_image_source_must_be_an_original_or_cache(repo, tmp_path):
    """別的地方的圖(家目錄、個人 WIKI)不能被抄進公事庫。"""
    raw = tmp_path / "FRaw_Sources"
    raw.mkdir()
    other = _png(tmp_path / "Raw_Sources" / "私人.png")
    for src in (str(other), str(raw / ".." / "Raw_Sources" / "私人.png")):
        with pytest.raises(PageToolError):
            add_image(repo, [raw], src, "Wiki_Pages/群組/images/頁/圖.jpg")
    assert not (repo / "Wiki_Pages/群組/images").exists()


def test_refusals_follow_the_interface_language(repo, tmp_path):
    from wiki_feeder import i18n
    raw = tmp_path / "FRaw_Sources"
    raw.mkdir()
    other = _png(tmp_path / "別處" / "圖.png")
    i18n.set_lang("en")
    with pytest.raises(PageToolError, match="is not a file in the originals tree or the transcription cache"):
        add_image(repo, [raw], str(other), "Wiki_Pages/群組/images/頁/圖.jpg")
