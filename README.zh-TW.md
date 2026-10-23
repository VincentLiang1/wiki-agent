# wiki-agent

[English](README.md) | **繁體中文** | [简体中文](README.zh-CN.md)

**iPhone 按下記錄,知識庫自己長出一頁。**

wiki-agent 是一支在你電腦上常駐的小程式,替你照 Andrej Karpathy 的「LLM Wiki」做法維護個人知識庫(沒聽過 LLM Wiki?看〈[什麼是 LLM Wiki](What-is-LLM-Wiki.zh-TW.md)〉):

1. 你在 iPhone 上把錄音、白板照片、掃描件、Office 檔丟進 iCloud 雲碟的 `_WikiBox` 資料夾
2. 電腦上的 wiki-agent 每分鐘看一次:把檔案收進原件資料夾 `Raw_Sources`,錄音與文件先轉成文字(用 [scribe2md](https://github.com/VincentLiang1/scribe2md))
3. 用你自己的 Claude Code,照你知識庫裡的 `CLAUDE.md` 規則把它編進 `WIKI/Wiki_Pages/`:新建頁面或補進既有的頁、更新目錄 `index.md`
4. 程式檢查過才記成一個版本(git,由程式代管,你不用學)。每天寄一封摘要信告訴你處理了什麼

你只做兩件事:**丟檔**、**看摘要**。有錯就打開 Claude Code 說是哪一筆要退回。

> **檔案絕不會丟**:搬檔一律先複製、比對內容一致才刪來源;任何一步失敗就留著原檔,下一輪再試。

## 需要什麼

| | Mac | Windows |
| --- | --- | --- |
| 電腦 | Apple 晶片的 Mac(版本需求照 scribe2md 的說明) | Windows 10／11 |
| 手機 | iPhone(用 iCloud 雲碟傳檔) | iPhone + 電腦裝 iCloud for Windows |
| Claude | 自己的 Claude 訂閱(Pro 或 Max),裝好 Claude Code 並登入 | 同左 |
| 轉寫 | [scribe2md](https://github.com/VincentLiang1/scribe2md/releases/latest) 的 Mac 版 | scribe2md 的 Windows 版 |
| 摘要信(可不設) | Gmail + 應用程式密碼 | 同左 |

知識庫照〈LLM Wiki 新手教學講義-桌面版〉的擺法:一個資料夾底下並排 `WIKI/`(裡面有 `CLAUDE.md`)與 `Raw_Sources/`。**還沒有也沒關係**:安裝時直接按 Enter,程式會幫你建好資料夾,並請 Claude 照講義寫好 `CLAUDE.md`;已經有的知識庫照原本的用,不會覆蓋。

## 安裝

- **Mac**:看 [Mac-Install-Guide.zh-TW.md](Mac-Install-Guide.zh-TW.md)。下載 [wiki-agent-mac.zip](https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-mac.zip)、解開,把 wiki-agent 拖進「應用程式」再雙擊(已簽章公證)。備用:打開「終端機」貼上一行:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
  ```
- **Windows**:看 [Windows-Install-Guide.zh-TW.md](Windows-Install-Guide.zh-TW.md)。下載 `Install.bat`,雙擊

安裝會一題一題問(每題都有預設答案,大多直接按 Enter),最後裝好每分鐘自動跑的排程。第一題選語言:繁體中文、簡體中文或 English,之後的問題、摘要信、警示與新建的知識庫都用那個語言。

## 要知道的事

- **你的資料會送到 Anthropic 的 API**:攝入時 Claude 會讀原始檔(含照片)。跟你平常用 Claude 一樣,用的是你自己的帳號與額度;一筆攝入大約 US$0.3～1
- **Claude 的權限給到最小**:只能讀檔、改知識庫裡的頁;不能刪檔、不能搬原件、不能自己 commit 或推送。改完由程式檢查——原件少了、頁面被大量刪減、留下奇怪的檔,就整個停下來寄信等你看
- **版本紀錄由程式代管**:不要自己在知識庫裡執行 git(多一筆程式沒驗證過的 commit,自動攝入就會停住)。手動改的頁直接存檔就好,下次攝入前程式會先存成一筆「手動修改快照」
- 程式的設定與紀錄在 `~/Library/Application Support/wiki-feeder/`(Mac)或 `%LOCALAPPDATA%\wiki-feeder\`(Windows),看 log 就看裡面的 `logs/feeder.log`

## 著作權

Copyright © 2026 Vincent Liang. **All rights reserved.**

這份程式碼公開是為了讓朋友方便安裝,**不是開源軟體**:沒有授予任何複製、修改、散布或商業使用的權利。個人自用請直接照安裝說明裝;其他用途請先聯絡作者。
