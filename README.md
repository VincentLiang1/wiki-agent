# wiki-agent

**iPhone 按下記錄,知識庫自己長出一頁。**

wiki-agent 是一支在你電腦上常駐的小程式,替你照 Andrej Karpathy 的「LLM Wiki」做法維護個人知識庫:

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

- **Mac**:看 [Mac安裝說明.md](Mac安裝說明.md)。打開「終端機」貼上一行:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
  ```
- **Windows**:看 [Windows安裝說明.md](Windows安裝說明.md)。下載 `安裝.bat`,雙擊

安裝會一題一題問(每題都有預設答案,大多直接按 Enter),最後裝好每分鐘自動跑的排程。

## 要知道的事

- **你的資料會送到 Anthropic 的 API**:攝入時 Claude 會讀原始檔(含照片)。跟你平常用 Claude 一樣,用的是你自己的帳號與額度;一筆攝入大約 US$0.3～1
- **Claude 的權限給到最小**:只能讀檔、改知識庫裡的頁;不能刪檔、不能搬原件、不能自己 commit 或推送。改完由程式檢查——原件少了、頁面被大量刪減、留下奇怪的檔,就整個停下來寄信等你看
- **版本紀錄由程式代管**:不要自己在知識庫裡執行 git(多一筆程式沒驗證過的 commit,自動攝入就會停住)。手動改的頁直接存檔就好,下次攝入前程式會先存成一筆「手動修改快照」
- 程式的設定與紀錄在 `~/Library/Application Support/wiki-feeder/`(Mac)或 `%LOCALAPPDATA%\wiki-feeder\`(Windows),看 log 就看裡面的 `logs/feeder.log`

## 著作權

Copyright © 2026 Vincent Liang. **All rights reserved.**

這份程式碼公開是為了讓朋友方便安裝,**不是開源軟體**:沒有授予任何複製、修改、散布或商業使用的權利。個人自用請直接照安裝說明裝;其他用途請先聯絡作者。

---

## English

**wiki-agent** keeps a personal LLM Wiki (Andrej Karpathy's pattern) up to date in the background. Drop a voice memo, whiteboard photo, scan or Office file into the `_WikiBox` folder on iCloud Drive from your iPhone; every minute the agent picks it up, stores the original under `Raw_Sources/`, transcribes it with [scribe2md](https://github.com/VincentLiang1/scribe2md), and asks *your own* Claude Code to compile it into `WIKI/Wiki_Pages/` following the wiki's own `CLAUDE.md`. The program verifies the result before recording it as a git commit (git is managed for you) and emails a daily summary.

- **Requirements**: an Apple-silicon Mac or Windows 10/11 PC, an iPhone with iCloud Drive, your own Claude subscription with Claude Code signed in, scribe2md for transcription, and optionally a Gmail app password for the summary mail.
- **Install**: Mac — run `curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash` in Terminal (see `Mac安裝說明.md`); Windows — download and double-click `安裝.bat` (see `Windows安裝說明.md`). The guides are in Traditional Chinese.
- **Privacy**: originals (including images) are sent to the Anthropic API under your own account. Claude runs with minimal permissions and every change is checked by the program before it is kept.
- **License**: Copyright © 2026 Vincent Liang. **All rights reserved.** The source is public for convenient installation only; no permission is granted to copy, modify, distribute or use it commercially.
