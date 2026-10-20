#!/bin/zsh
# 更新 wiki-agent(Mac):雙擊就好。等正在跑的一輪做完 → git pull → uv sync;排程不必重裝。
cd "$(dirname "$0")" || { echo "找不到程式資料夾:這個檔不要單獨搬走"; read -r _; exit 1; }
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
.venv/bin/python scripts/macsched.py update
echo
echo "(按 Enter 關閉這個視窗)"
read -r _
# read 碰到 EOF 回 1:不明寫 exit 0 的話,更新成功了也回報失敗
exit 0
