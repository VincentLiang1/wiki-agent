"""Windows 上讓測試的 `Path.write_text` 照 Mac 寫 LF。

測試是在 Mac 上寫的,頁面一律用 write_text 寫;Windows 預設把 `\\n` 轉成 `\\r\\n`,頁面檢查會把每一行都判成
「控制字元 U+000D」——那是測試環境的差異,不是程式的問題。conftest 與假的 claude／doc2md(另一個行程)都載入它。
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32" and not getattr(Path.write_text, "_lf", False):
    _orig = Path.write_text

    def _write_text_lf(self, data, encoding=None, errors=None, newline="\n"):
        return _orig(self, data, encoding, errors, newline)

    _write_text_lf._lf = True
    Path.write_text = _write_text_lf
