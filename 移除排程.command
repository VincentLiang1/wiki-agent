#!/bin/zsh
# 停掉 wiki-agent 的排程(Mac):雙擊就好。設定檔、處理紀錄、知識庫都不動;要再裝回來,重貼安裝那一行。
cd "$(dirname "$0")" || { echo "找不到程式資料夾:這個檔不要單獨搬走"; read -r _; exit 1; }
.venv/bin/python scripts/macsched.py uninstall
echo
echo "(按 Enter 關閉這個視窗)"
read -r _
exit 0
