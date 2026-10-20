#!/bin/bash
# wiki-agent 的 Mac 安裝(第一次安裝、重填設定都用這一行)。在「終端機」貼上:
#
#   curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
#
# 做的事:沒有 git 就裝 Apple 的命令列開發工具 → 沒有 uv 就裝 → 下載(或更新)到 ~/wiki-agent →
# 建 Python 環境 → 問答寫設定檔、存寄信密碼、裝排程(scripts/macsetup.py)。
#
# ⚠️ 整支包在 main 裡、最後一行才執行:curl 下載到一半斷線時,bash 不會只跑了前半段。
# ⚠️ 問答要從 /dev/tty 讀鍵盤:`curl … | bash` 的標準輸入是這支腳本本身,直接讀會把腳本吃掉。
# 不用從網頁下載的 .command 當入口:下載的檔帶著隔離標記、失去執行權限,雙擊打不開;git clone 下來的
# 更新.command／移除排程.command 沒有這個問題。

main() {
    set -u
    local repo_url="https://github.com/VincentLiang1/wiki-agent.git"
    local dest="${WIKI_AGENT_DIR:-$HOME/wiki-agent}"

    if [ "$(uname)" != "Darwin" ]; then
        echo "✗ 這一行只給 Mac 用;Windows 請下載 安裝.bat"
        return 1
    fi

    echo "=== 1/4 命令列開發工具(git) ==="
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "需要 Apple 的「命令列開發工具」(裡面有 git)。等一下會跳出視窗:"
        echo "  按「安裝」→「同意」,等它跑完(約 5～15 分鐘),這裡會自己接著做。"
        xcode-select --install >/dev/null 2>&1
        until xcode-select -p >/dev/null 2>&1; do sleep 5; done
    fi
    echo "✓ git:$(git --version)"

    echo "=== 2/4 uv(Python 環境管理工具) ==="
    export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || {
            echo "✗ uv 裝不起來:請檢查網路"
            return 1
        }
        export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "✓ $(uv --version)"

    echo "=== 3/4 下載程式到 $dest ==="
    if [ -d "$dest/.git" ]; then
        git -C "$dest" pull --ff-only || {
            echo "✗ 更新失敗:$dest 裡可能有改過的檔。把這個視窗的內容給幫你裝的人看"
            return 1
        }
    elif [ -e "$dest" ]; then
        echo "✗ $dest 已經有別的東西:搬走或改名後再貼一次這一行"
        return 1
    else
        git clone -q "$repo_url" "$dest" || {
            echo "✗ 下載失敗:請檢查網路"
            return 1
        }
    fi
    uv sync --frozen -q --directory "$dest" || {
        echo "✗ Python 環境建不起來:把這個視窗的內容給幫你裝的人看"
        return 1
    }
    echo "✓ $dest"

    echo "=== 4/4 設定 ==="
    uv run --frozen --directory "$dest" python scripts/macsetup.py "$@" </dev/tty
}

main "$@"
