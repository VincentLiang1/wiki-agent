#!/bin/bash
# wiki-agent 的 Mac 安裝(第一次安裝、重填設定都用這一行)。在「終端機」貼上:
# (2026-10-22 起主要的裝法是 Release 的 wiki-agent-mac.zip:雙擊 App、權限按「允許」就好;這一行留著當備用)
#
#   curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
#
# 做的事:沒有 git 就裝 Apple 的命令列開發工具 → 沒有 uv 就裝 → 下載(或更新)到 ~/wiki-agent →
# 建 Python 環境 → 問答寫設定檔、存寄信密碼、裝排程(scripts/macsetup.py)。
#
# ⚠️ 整支包在 main 裡、最後一行才執行:curl 下載到一半斷線時,bash 不會只跑了前半段。
# ⚠️ 問答要從 /dev/tty 讀鍵盤:`curl … | bash` 的標準輸入是這支腳本本身,直接讀會把腳本吃掉。
# 不用從網頁下載的 .command 當入口:下載的檔帶著隔離標記、失去執行權限,雙擊打不開;git clone 下來的
# Update.command／Remove-Schedule.command 沒有這個問題。
# 訊息語言(Python 還沒裝好,不能用 i18n.py):一開始就請朋友選(使用者 2026-10-27:「一開始時確認語言後,就只用
# 使用者選定的語言顯示」),直接按 Enter = 設定檔裡的語言,沒有設定檔照系統語言(繁中、簡中、其他一律英文);
# 選的結果用 WIKI_AGENT_LANG 交給問答(macsetup.py),它就不再問一次。

# `defaults read -g AppleLanguages` 的輸出 → zh-Hant／zh-Hans／en(第一個語言就是系統介面語言)
detect_lang() {
    local first
    first=$(printf '%s\n' "$1" | tr -d ' "(),' | grep -v '^$' | head -n 1)
    case "$first" in
        zh-Hant* | zh-TW* | zh-HK* | zh-MO* | zh_TW* | zh_HK*) echo zh-Hant ;;
        zh-Hans* | zh-CN* | zh-SG* | zh_CN* | zh_SG* | zh) echo zh-Hans ;;
        *) echo en ;;
    esac
}

# 設定檔 [general] language(重跑安裝時沿用上次選的);沒有或認不得就空字串
config_lang() {
    local v
    v=$(sed -n 's/^language *= *"\(.*\)".*/\1/p' "$1" 2>/dev/null | head -n 1)
    case "$v" in zh-Hant | zh-Hans | en) echo "$v" ;; esac
}

# 選語言:三種寫法並列(還不知道看得懂哪一種);與 macsetup.py 問的同一行(winsetup.lang_prompt)。
# 鍵盤從 WA_TTY(預設 /dev/tty:curl … | bash 的標準輸入是腳本本身);讀不到就用預設
ask_lang() {
    local name ans=""
    case "$1" in zh-Hant) name="繁體中文" ;; zh-Hans) name="简体中文" ;; *) name="English" ;; esac
    printf '語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English(Enter = %s):' "$name" >&2
    read -r ans 2>/dev/null <"${WA_TTY:-/dev/tty}" || { ans=""; echo >&2; }
    case "$ans" in 1) echo zh-Hant ;; 2) echo zh-Hans ;; 3) echo en ;; *) echo "$1" ;; esac
}

# msg 繁中 簡中 英文:照 WA_LANG 印其中一個
msg() {
    case "${WA_LANG:-en}" in
        zh-Hant) printf '%s\n' "$1" ;;
        zh-Hans) printf '%s\n' "$2" ;;
        *) printf '%s\n' "$3" ;;
    esac
}

main() {
    set -u
    WA_LANG=$(config_lang "$HOME/Library/Application Support/wiki-feeder/config.toml")
    [ -n "$WA_LANG" ] || WA_LANG=$(detect_lang "$(defaults read -g AppleLanguages 2>/dev/null)")
    WA_LANG=$(ask_lang "$WA_LANG")
    export WIKI_AGENT_LANG="$WA_LANG"
    local repo_url="https://github.com/VincentLiang1/wiki-agent.git"
    local dest="${WIKI_AGENT_DIR:-$HOME/wiki-agent}"

    if [ "$(uname)" != "Darwin" ]; then
        msg "✗ 這一行只給 Mac 用;Windows 請下載 Install.bat" "✗ 这一行只给 Mac 用;Windows 请下载 Install.bat" "✗ This command is for Mac only; on Windows, download Install.bat"
        return 1
    fi

    msg "=== 1/4 命令列開發工具(git) ===" "=== 1/4 命令行开发工具(git) ===" "=== 1/4 Command Line Tools (git) ==="
    if ! xcode-select -p >/dev/null 2>&1; then
        msg "需要 Apple 的「命令列開發工具」(裡面有 git)。等一下會跳出視窗:" \
            "需要 Apple 的「命令行开发工具」(里面有 git)。等一下会弹出窗口:" \
            "Apple's Command Line Tools (which include git) are needed. A window will pop up shortly:"
        msg "  按「安裝」→「同意」,等它跑完(約 5～15 分鐘),這裡會自己接著做。" \
            "  按「安装」→「同意」,等它跑完(约 5～15 分钟),这里会自己接着做。" \
            "  Click \"Install\" → \"Agree\" and wait for it to finish (about 5-15 minutes); this script will continue on its own."
        xcode-select --install >/dev/null 2>&1
        until xcode-select -p >/dev/null 2>&1; do sleep 5; done
    fi
    msg "✓ git:$(git --version)" "✓ git:$(git --version)" "✓ git: $(git --version)"

    msg "=== 2/4 uv(Python 環境管理工具) ===" "=== 2/4 uv(Python 环境管理工具) ===" "=== 2/4 uv (Python environment manager) ==="
    export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || {
            msg "✗ uv 裝不起來:請檢查網路" "✗ uv 装不起来:请检查网络" "✗ Could not install uv: please check your network"
            return 1
        }
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "✓ $(uv --version)"

    msg "=== 3/4 下載程式到 $dest ===" "=== 3/4 下载程序到 $dest ===" "=== 3/4 Downloading the program to $dest ==="
    if [ -d "$dest/.git" ]; then
        git -C "$dest" pull --ff-only || {
            msg "✗ 更新失敗:$dest 裡可能有改過的檔。把這個視窗的內容給幫你裝的人看" \
                "✗ 更新失败:$dest 里可能有改过的文件。把这个窗口的内容给帮你装的人看" \
                "✗ Update failed: $dest may contain modified files. Show this window to the person who set this up for you"
            return 1
        }
    elif [ -e "$dest" ]; then
        msg "✗ $dest 已經有別的東西:搬走或改名後再貼一次這一行" \
            "✗ $dest 已经有别的东西:搬走或改名后再贴一次这一行" \
            "✗ $dest already contains something else: move or rename it, then paste this command again"
        return 1
    else
        git clone -q "$repo_url" "$dest" || {
            msg "✗ 下載失敗:請檢查網路" "✗ 下载失败:请检查网络" "✗ Download failed: please check your network"
            return 1
        }
    fi
    uv sync --frozen -q --directory "$dest" || {
        msg "✗ Python 環境建不起來:把這個視窗的內容給幫你裝的人看" \
            "✗ Python 环境建不起来:把这个窗口的内容给帮你装的人看" \
            "✗ Could not set up the Python environment: show this window to the person who set this up for you"
        return 1
    }
    echo "✓ $dest"

    msg "=== 4/4 設定 ===" "=== 4/4 设置 ===" "=== 4/4 Settings ==="
    uv run --frozen --directory "$dest" python scripts/macsetup.py "$@" </dev/tty
}

main "$@"
