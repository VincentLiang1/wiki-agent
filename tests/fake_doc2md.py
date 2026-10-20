"""假的 doc2md:照 FAKE_DOC2MD_MODE 產出各種情況,並把收到的參數記在 FAKE_DOC2MD_ARGS。

產出的 md 格式照真的 doc2md(front matter + 內文 + 逐字稿的講者辨識診斷表)。
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import _lf  # noqa: F401 —— Windows 上 write_text 寫 LF(同目錄)

args = sys.argv[1:]
log_args = os.environ.get("FAKE_DOC2MD_ARGS")
if log_args:
    with open(log_args, "a", encoding="utf-8") as f:
        f.write(json.dumps(args, ensure_ascii=False) + "\n")

mode = os.environ.get("FAKE_DOC2MD_MODE", "ok")
if mode == "norun":
    print("error: 系統找不到指定的檔案。 (os error 2)", file=sys.stderr)
    sys.exit(2)

src = Path(args[0])
out_dir = Path(args[args.index("--out-dir") + 1])
print("執行記錄:/tmp/fake-doc2md.log", file=sys.stderr)
if mode == "fail":
    print("轉換失敗:1 個", file=sys.stderr)
    sys.exit(1)

audio = src.suffix.lower() in {".m4a", ".wav", ".mp3", ".mp4", ".mov", ".avi"}
lossy = {"garbled": "[garbled_text_layer]", "ok": "[scanned_page, ocr]" if not audio else "[]"}.get(mode, "[]")
if mode == "empty":
    body = "## 第 1 頁\n\n![第 1 頁(整頁影像)](x.assets/img-0001.png)\n\n〔以下文字由第 1 頁的整頁影像辨識而來,可能有誤〕\n"
elif audio:
    body = ("**講者 1** (00:00:00)\n今天討論預算。\n\n**王小明**〔機器辨識〕 (00:00:14)\n好的。\n\n"
            "## 講者辨識診斷\n\n| 講者 | 發言輪次 | 總時長 | 群內一致性 | 名字來源 |\n"
            "| --- | ---: | ---: | ---: | --- |\n| 講者 1 | 1 | 00:00:02 | 1.00 | 未命名 |\n"
            "| 王小明 | 1 | 00:00:02 | 0.98 | 機器辨識 |\n")
else:
    body = "## 第 1 頁\n\n白板上寫著第四季目標與三項待辦。\n"

h = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
md = out_dir / f"{src.stem}-{h}.md"
md.write_text(
    f"---\nsource_file: {src.name}\nsource_type: {src.suffix[1:]}\nlossy_kinds: {lossy}\n"
    f"ocr_used: {'false' if audio else 'true'}\ntraditionalised: false\n---\n\n# {src.stem}\n\n{body}",
    encoding="utf-8",
)
print("轉換完成:成功 1 個。", file=sys.stderr)
print(md)
