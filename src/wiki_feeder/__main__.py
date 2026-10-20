"""`python -m wiki_feeder`:launchd 直接用 venv 的 python 執行(不經 uv)。

完整磁碟取用權限授權給固定的 python 執行檔;經 uv 啟動的話權限要給 uv,
而 Homebrew 每次升級 uv 路徑就變、權限跟著失效。
"""
import sys

from .cli import main

sys.exit(main())
