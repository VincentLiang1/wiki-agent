# wiki-agent

**繁體中文** | [**English** ↓](#english)

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

[繁體中文 ↑](#wiki-agent) | **English**

**Record on your iPhone — a new page appears in your knowledge base.**

wiki-agent is a small background program on your computer that maintains a personal knowledge base for you, following Andrej Karpathy's "LLM Wiki" pattern:

1. On your iPhone, drop a voice memo, whiteboard photo, scanned document or Office file into the `_WikiBox` folder on iCloud Drive
2. Every minute, wiki-agent on your computer checks that folder: it moves the file into your originals folder `Raw_Sources`, and turns recordings and documents into text first (using [scribe2md](https://github.com/VincentLiang1/scribe2md))
3. It asks *your own* Claude Code to compile the material into `WIKI/Wiki_Pages/` according to the rules in your wiki's `CLAUDE.md`: creating a new page or adding to an existing one, and updating the table of contents `index.md`
4. Only after the program has checked the result is it recorded as a version (git, managed by the program — you don't need to learn it). A daily summary email tells you what was processed

You do just two things: **drop files** and **read the summary**. If something is wrong, open Claude Code and say which entry to roll back.

> **Your files are never lost**: every move copies first and deletes the source only after the copy's content has been verified identical. If any step fails, the original stays where it is and is retried on the next round.

### Requirements

| | Mac | Windows |
| --- | --- | --- |
| Computer | Apple-silicon Mac (OS version as required by scribe2md) | Windows 10/11 |
| Phone | iPhone (files travel through iCloud Drive) | iPhone + iCloud for Windows on the PC |
| Claude | Your own Claude subscription (Pro or Max), with Claude Code installed and signed in | Same |
| Transcription | Mac version of [scribe2md](https://github.com/VincentLiang1/scribe2md/releases/latest) | Windows version of scribe2md |
| Summary email (optional) | Gmail + an app password | Same |

The knowledge base follows the layout of the "LLM Wiki beginner's handout (desktop edition)": one folder containing `WIKI/` (with a `CLAUDE.md` inside) and `Raw_Sources/` side by side. **Don't have one yet? No problem**: just press Enter during setup and the installer creates the folders and asks Claude to write a `CLAUDE.md` following the handout. An existing knowledge base is used as-is and never overwritten.

### Installation

The step-by-step guides ([Mac安裝說明.md](Mac安裝說明.md), [Windows安裝說明.md](Windows安裝說明.md)) are written in Traditional Chinese. In short:

**Mac** (about 30–40 minutes, mostly downloads)

1. Make sure iCloud Drive is turned on (System Settings → your name → iCloud → iCloud Drive)
2. Install Claude Code and sign in with your Claude account: in Terminal run `curl -fsSL https://claude.ai/install.sh | bash`, then `claude`
3. Download `scribe2md-mac.zip` from the [scribe2md releases](https://github.com/VincentLiang1/scribe2md/releases/latest), drag the app into Applications and open it once so it can set itself up
4. (Optional) Create a Gmail app password at <https://myaccount.google.com/apppasswords> for the summary email
5. Paste this line into Terminal:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
   ```
   If macOS offers to install the command line developer tools, click **Install** (not "Get Xcode"). The installer then sets up uv, downloads the program into `~/wiki-agent` and asks a series of questions — each has a default, so you can mostly just press Enter
6. **Full Disk Access (required)**: the scheduled job runs in the background, and macOS must allow it to read iCloud Drive. The installer opens System Settings → Privacy & Security → Full Disk Access and prints a long path (ending in something like `python3.12`). Click **+**, press ⌘⇧G, paste the path, click **Open**, make sure the switch is on, then press Enter in Terminal so it can test-read the inbox

**Windows**

1. Install iCloud for Windows, Claude Code (signed in) and the Windows version of scribe2md
2. (Optional) Create a Gmail app password for the summary email
3. Download `安裝.bat` (“install”) from this repository and double-click it. If Windows SmartScreen warns you, choose **More info → Run anyway**. It installs Git and uv if needed, puts the program in `C:\wiki-feeder` (no GitHub account needed) and asks the same questions

Both installers finish by setting up a schedule that runs every minute. To check that it works, drop any file into `_WikiBox` from the iPhone's Files app; after a few minutes a new page appears under `WIKI/Wiki_Pages`, the original is filed into a topic folder under `Raw_Sources`, and (if configured) you receive a "wiki-feeder 攝入摘要" (ingest summary) email.

- **Update**: double-click `更新.command` (Mac, in `~/wiki-agent`) or `更新.bat` (Windows, in `C:\wiki-feeder`). If a round is in progress, it waits for it to finish
- **Uninstall**: `移除排程.command` / `移除排程.bat` removes only the schedule; settings, logs and your knowledge base stay. To remove everything, also delete the program folder and the settings folder listed below — your `WIKI` and `Raw_Sources` are not in either and are never deleted

### Things to know

- **Your data is sent to the Anthropic API**: during ingestion Claude reads the original files (including photos). As with your normal Claude use, it runs on your own account and quota; one ingestion costs roughly US$0.3–1
- **Claude gets the minimum permissions**: it can read files and edit pages in the knowledge base, but cannot delete files, move originals, commit or push by itself. The program checks every change afterwards — if an original is missing, a page has been heavily cut, or stray files are left behind, it stops everything and emails you to take a look
- **Version history is managed by the program**: don't run git in the knowledge base yourself (including asking Claude to commit for you). One commit the program hasn't verified will halt automatic ingestion. Pages you edit by hand are fine — just save them; before the next ingestion the program records them as a "manual edit snapshot"
- Settings and logs live in `~/Library/Application Support/wiki-feeder/` (Mac) or `%LOCALAPPDATA%\wiki-feeder\` (Windows); the log is `logs/feeder.log`

### When something goes wrong

- **The email subject starts with "⚠️ 需要處理" (action needed)**: open Terminal (Mac: `cd ~/wiki-agent && claude`) or PowerShell (Windows: `cd C:\wiki-feeder; claude`), paste the whole email into Claude and ask it to handle it according to wiki-agent's rules
- **"Claude Code is not signed in or the sign-in expired"**: run `claude` and sign in again; the next round picks up where it left off
- **Mac can't read the inbox**: usually Full Disk Access is missing or switched off — redo step 6 above

### License

Copyright © 2026 Vincent Liang. **All rights reserved.**

The source code is public only so that friends can install it easily. **It is not open-source software**: no permission is granted to copy, modify, distribute or use it commercially. For personal use, just follow the installation guides; for anything else, please contact the author first.
