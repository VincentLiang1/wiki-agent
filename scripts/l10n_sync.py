#!/usr/bin/env python3
"""譯文檔 src/wiki_feeder/locales/{en,zh-Hans}.json 跟程式對齊(做法照 scribe2md-ios 的 l10n_sync.py)。

1. 用 ast 抽出程式裡所有 `L("…")`、`N_("…")` 的繁中原文(EXTRACT 列的檔)
2. 譯文檔沒有的鍵補進去;程式裡已經沒有的鍵刪掉
3. 簡中:沒有的用 OpenCC(台灣繁體 → 大陸簡體,含用語 tw2sp)自動轉,再套 ZH_HANS_FIX;
   自動轉得不對的(例如寫著「繁體中文」的提示詞)手寫在 scripts/l10n/zh-Hans-overrides.json,一律以它為準
4. 英文:從 --en <json>({繁中原文: 英文},可以給好幾個)補;沒有英文的列出來、回非零(提交前要補齊)

用 meeting-scribe-native 的 venv 跑(要 opencc 套件;wiki-feeder 本身不裝它):
  ~/SOURCE5/Python/meeting-scribe-native/.venv/bin/python scripts/l10n_sync.py [--en 英文.json …] [--check]
--check:只檢查不寫檔(缺英文、缺簡中、或譯文檔跟程式不同步就失敗)。測試(tests/test_i18n.py)也查同樣的事。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "src" / "wiki_feeder" / "locales"
OVERRIDES = REPO / "scripts" / "l10n" / "zh-Hans-overrides.json"
EXTRACT = (sorted((REPO / "src" / "wiki_feeder").glob("*.py"))
           + [REPO / "scripts" / f"{n}.py" for n in ("winsetup", "macsetup", "macsched", "winsched")])

# OpenCC tw2sp 轉不到、或轉得不像大陸說法的。轉完才套,所以左邊寫簡體(與 scribe2md-ios 同一張,再加本程式的詞)
ZH_HANS_FIX = {
    "预设": "默认",
    "脱机": "离线",
    "云碟": "云盘",
    "送出": "发送",
    "资料夹": "文件夹",
    "档案": "文件",
    "个档": "个文件",
    "档名": "文件名",
    # macOS／Windows／Google 簡中介面上的正式名稱(說明要照畫面找得到)
    "完整磁盘取用权限": "完全磁盘访问权限",
    "钥匙圈": "钥匙串",
    "认证管理员": "凭据管理器",
    "应用程序密码": "应用专用密码",
    "系统设定": "系统设置",
    "隐私权与安全性": "隐私与安全性",
    "终端机": "终端",
    "调度": "定时任务",
    "收件匣": "收件箱",
    # 單獨的「檔」大陸說「文件」(設定檔、丟檔、這個檔);放最後,前面的「档案」「个档」「档名」先換掉
    "档": "文件",
}
# 程式寫死、或朋友照著找的名字:簡中也一字不改(資料夾名轉成簡體,程式就找不到它)
KEEP = ("_待處理", "_捨棄候選", "_收件區", "_聲紋同步", "執行記錄", "AI 文件.MD 轉換器",
        "安裝.bat", "更新.bat", "移除排程.bat", "更新.command", "移除排程.command")


def extract(files=EXTRACT) -> dict[str, str]:
    """{繁中原文: 出處};只收第一個參數是字串常數的(隱含串接的字串 ast 會併成一個)。"""
    keys: dict[str, str] = {}
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            name = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
            a = n.args[0]
            if name in ("L", "N_") and isinstance(a, ast.Constant) and isinstance(a.value, str):
                keys.setdefault(a.value, f"{f.relative_to(REPO)}:{n.lineno}")
    return keys


# 公開 repo 的說明文件:繁中 → 簡中(與畫面文字同一套轉換,說明裡引用的畫面字才對得上)
PUBLIC = REPO / "public"
DOCS = {"README.md": "README.zh-Hans.md", "Mac安裝說明.md": "Mac安装说明.md", "Windows安裝說明.md": "Windows安装说明.md"}


def hans_doc(text: str, cc) -> str:
    """頁首的語言切換列換成簡中那份的;連到繁中說明的連結,OpenCC 會順手把檔名轉成簡中那份的檔名。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("**繁體中文** | "):
            hant = next(k for k, v in DOCS.items() if f"]({v})" in ln)
            en = ln.rsplit("[English](", 1)[1].rstrip(")")
            lines[i] = f"@@HEAD@@"
            head = f"[繁體中文]({hant}) | **简体中文** | [English]({en})"
            break
    menu = "語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English"     # 安裝問答第一題:三種寫法並列,不翻
    out = to_hans("\n".join(lines).replace(menu + "(Enter = 繁體中文)", "@@MENU@@"), cc)
    return out.replace("@@HEAD@@", head).replace("@@MENU@@", menu + "(Enter = 简体中文)")


def load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def dump(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def to_hans(text: str, cc) -> str:
    marks = {f"@@KEEP{i}@@": w for i, w in enumerate(KEEP)}   # 不可用 NUL:OpenCC 是 C 字串,碰到就截斷
    for m, w in marks.items():
        text = text.replace(w, m)
    s = cc.convert(text)
    for a, b in ZH_HANS_FIX.items():
        s = s.replace(a, b)
    for m, w in marks.items():
        s = s.replace(m, w)
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", action="append", default=[], help="JSON:{繁中原文: 英文}(可以給好幾個)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--rehans", action="store_true", help="ZH_HANS_FIX／KEEP 改了之後,自動轉的簡中全部重轉")
    ap.add_argument("--docs", action="store_true", help="public/ 的繁中說明重轉成簡中那份(改了繁中說明就跑)")
    a = ap.parse_args(argv)

    if a.docs:
        import opencc
        cc = opencc.OpenCC("tw2sp")
        for src, dst in DOCS.items():
            (PUBLIC / dst).write_text(hans_doc((PUBLIC / src).read_text(encoding="utf-8"), cc), encoding="utf-8")
            print(f"{src} → {dst}")
        return 0
    keys = extract()
    en_path, hans_path = LOCALES / "en.json", LOCALES / "zh-Hans.json"
    en, hans, over = load(en_path), load(hans_path), load(OVERRIDES)
    for p in a.en:
        en.update(load(Path(p)))
    stale = sorted(set(en) - set(keys)) + sorted(set(hans) - set(keys))
    en = {k: v for k, v in en.items() if k in keys}
    hans = {k: v for k, v in hans.items() if k in keys}
    missing_hans = [k for k in keys if k not in hans or (k in over and hans[k] != over[k]) or a.rehans]
    if missing_hans and not a.check:
        import opencc
        cc = opencc.OpenCC("tw2sp")
        for k in missing_hans:
            hans[k] = over.get(k) or to_hans(k, cc)
    missing_en = [k for k in keys if k not in en]
    for k in missing_en:
        print(f"缺英文:{keys[k]}  {k[:80]!r}")
    if a.check:
        for k in missing_hans:
            print(f"缺簡中:{keys[k]}  {k[:80]!r}")
        for k in stale:
            print(f"程式裡已經沒有:{k[:80]!r}")
        return 1 if missing_en or missing_hans or stale else 0
    dump(en_path, en)
    dump(hans_path, hans)
    print(f"{len(keys)} 個鍵;英文缺 {len(missing_en)};簡中自動轉 {len(missing_hans)};刪掉舊鍵 {len(stale)}")
    return 1 if missing_en else 0


if __name__ == "__main__":
    sys.exit(main())
