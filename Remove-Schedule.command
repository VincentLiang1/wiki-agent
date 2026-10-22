#!/bin/zsh
# 停掉 wiki-agent 的排程(Mac):雙擊就好。設定檔、處理紀錄、知識庫都不動;要再裝回來,重貼安裝那一行。
# 訊息的語言:設定檔的 [general] language(安裝時選的);沒有就照系統語言(繁中／簡中／其他一律英文)
cfg_lang=$(sed -n 's/^language *= *"\(.*\)".*/\1/p' "$HOME/Library/Application Support/wiki-feeder/config.toml" 2>/dev/null | head -n 1)
case "${cfg_lang:-$(defaults read -g AppleLanguages 2>/dev/null | tr -d ' "(),' | grep -v '^$' | head -n 1)}" in
    zh-Hant* | zh-TW* | zh-HK* | zh-MO*) WA_LANG=zh-Hant ;;
    zh-Hans* | zh-CN* | zh-SG* | zh) WA_LANG=zh-Hans ;;
    *) WA_LANG=en ;;
esac
msg() { case $WA_LANG in zh-Hant) print -r -- "$1" ;; zh-Hans) print -r -- "$2" ;; *) print -r -- "$3" ;; esac }
cd "$(dirname "$0")" || {
    msg "找不到程式資料夾:這個檔不要單獨搬走" "找不到程序文件夹:这个文件不要单独搬走" \
        "Can't find the program folder: don't move this file out of it on its own"
    read -r _; exit 1
}
.venv/bin/python scripts/macsched.py uninstall
echo
msg "(按 Enter 關閉這個視窗)" "(按 Enter 关闭这个窗口)" "(Press Enter to close this window)"
read -r _
exit 0
