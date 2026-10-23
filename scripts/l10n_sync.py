#!/usr/bin/env python3
"""譯文檔 src/wiki_feeder/locales/{en,zh-Hans}.json 跟程式對齊(做法照 scribe2md-ios 的 l10n_sync.py)。

1. 用 ast 抽出程式裡所有 `L("…")`、`N_("…")` 的繁中原文(EXTRACT 列的檔)
2. 譯文檔沒有的鍵補進去;程式裡已經沒有的鍵刪掉
3. 簡中:沒有的用 OpenCC(台灣繁體 → 大陸簡體,含用語 tw2sp)自動轉,再套 ZH_HANS_FIX;
   自動轉得不對的(例如寫著「繁體中文」的提示詞)手寫在 scripts/l10n/zh-Hans-overrides.json,一律以它為準
4. 英文:從 --en <json>({繁中原文: 英文},可以給好幾個)補;沒有英文的列出來、回非零(提交前要補齊)
5. 三個 .bat 的 `call :msg／:pick` 簡中那一欄照繁中重轉(英文直接寫在 .bat 裡)

用 meeting-scribe-native 的 venv 跑(要 opencc 套件;wiki-feeder 本身不裝它):
  ~/SOURCE5/Python/meeting-scribe-native/.venv/bin/python scripts/l10n_sync.py [--en 英文.json …] [--check]
  (Windows:C:/SOURCE5/Python/meeting-scribe-native/.venv/Scripts/python.exe -X utf8 scripts/l10n_sync.py)
--check:只檢查不寫檔(缺英文、缺簡中、或譯文檔跟程式不同步就失敗)。測試(tests/test_i18n.py)也查同樣的事。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "src" / "wiki_feeder" / "locales"
OVERRIDES = REPO / "scripts" / "l10n" / "zh-Hans-overrides.json"
EXTRACT = (sorted((REPO / "src" / "wiki_feeder").glob("*.py"))
           + [REPO / "scripts" / f"{n}.py" for n in ("winsetup", "macsetup", "macsched", "winsched", "winupdate")])

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
    "签章": "签名",
    # macOS／Windows／Google 簡中介面上的正式名稱(說明要照畫面找得到)
    "完整磁盘取用权限": "完全磁盘访问权限",
    "钥匙圈": "钥匙串",
    "认证管理员": "凭据管理器",
    "工作调度器": "任务计划程序",   # 「工作排程器」:Windows 簡中介面的正式名稱;要在下面的「调度」之前
    "应用程序密码": "应用专用密码",
    "系统设定": "系统设置",
    "隐私权与安全性": "隐私与安全性",
    "文件与文件夹": "文件和文件夹",     # 「檔案與檔案夾」:隱私與安全性底下那一項
    "终端机": "终端",
    "调度": "定时任务",
    "收件匣": "收件箱",
    "纪录": "记录",       # 處理紀錄、版本紀錄:大陸寫「记录」(「纪录」是比賽紀錄)
    "帐号": "账号",       # 「用户帐户控制」是 Windows 簡中介面的正式名稱,只換「帐号」
    # 單獨的「檔」大陸說「文件」(設定檔、丟檔、這個檔);放最後,前面的「档案」「个档」「档名」先換掉
    "档": "文件",
    # OpenCC 把「文件」(文件資料夾、錄音與文件)正確轉成「文档」,上一條又把它改成「文文件」:改回來
    "文文件": "文档",
}
# 程式寫死、或朋友照著找的名字:簡中也一字不改(資料夾名轉成簡體,程式就找不到它)
KEEP = ("_待處理", "_捨棄候選", "_收件區", "_聲紋同步", "執行記錄", "AI 文件.MD 轉換器")


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
# 檔名與頁首比照 scribe2md(使用者 2026-10-23):X.md 英文、X.zh-TW.md 繁中、X.zh-CN.md 簡中;頁首 English | 繁體中文 | 简体中文
DOCS = {"README.zh-TW.md": "README.zh-CN.md", "Mac-Install-Guide.zh-TW.md": "Mac-Install-Guide.zh-CN.md", "Windows-Install-Guide.zh-TW.md": "Windows-Install-Guide.zh-CN.md"}


def hans_doc(text: str, cc) -> str:
    """頁首的語言切換列換成簡中那份的;連到繁中說明的連結換成簡中那份(檔名 2026-10-22 起是英文,
    OpenCC 不會再順手轉)。`README.md` 是英文那份、不換。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("[English](") and " | **繁體中文** | " in ln:
            hant = next(k for k, v in DOCS.items() if f"]({v})" in ln)
            en = ln.split("[English](", 1)[1].split(")", 1)[0]
            lines[i] = f"@@HEAD@@"
            head = f"[English]({en}) | [繁體中文]({hant}) | **简体中文**"
            break
    menu = "語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English"     # 安裝問答第一題:三種寫法並列,不翻
    out = to_hans("\n".join(lines).replace(menu + "(Enter = 繁體中文)", "@@MENU@@"), cc)
    for hant_name, hans_name in DOCS.items():
        out = out.replace(hant_name, hans_name)
    return out.replace("@@HEAD@@", head).replace("@@MENU@@", menu + "(Enter = 简体中文)")


# 三個 .bat(UTF-8、CRLF):`call :msg "繁中" "簡中" "English"`、`call :pick 變數 "繁中" "簡中" "English"`
# 的簡中那一欄照繁中重轉(.bat 在 Python 之前跑,用不了譯文檔;docs/dev/Windows安裝.md)
BATS = ("Install.bat", "Update.bat", "Remove-Schedule.bat")
BAT_MSG = re.compile(r'(call :(?:msg|pick \w+) )"([^"]*)" "([^"]*)" "([^"]*)"')


def hans_bat(text: str, hans) -> str:
    """每一行 :msg／:pick 的第二欄換成 hans(第一欄);rem 註解與其他字一個不動。"""
    return "".join(ln if ln.lstrip().lower().startswith("rem ")
                   else BAT_MSG.sub(lambda m: f'{m[1]}"{m[2]}" "{hans(m[2])}" "{m[4]}"', ln)
                   for ln in text.splitlines(keepends=True))


def sync_bats(cc, over: dict[str, str], root: Path = REPO) -> int:
    changed = 0
    for name in BATS:
        p = root / name
        old = p.read_bytes().decode("utf-8")
        new = hans_bat(old, lambda s: over.get(s) or to_hans(s, cc))
        if new != old:
            p.write_bytes(new.encode("utf-8"))
            changed += 1
    return changed


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
    import opencc
    bats = sync_bats(opencc.OpenCC("tw2sp"), over)
    print(f"{len(keys)} 個鍵;英文缺 {len(missing_en)};簡中自動轉 {len(missing_hans)};刪掉舊鍵 {len(stale)};"
          f".bat 改了 {bats} 個")
    return 1 if missing_en else 0


if __name__ == "__main__":
    sys.exit(main())
