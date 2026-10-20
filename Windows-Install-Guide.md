# wiki-agent Installation Guide for Windows

[繁體中文](Windows安裝說明.md) | **English**

Follow the steps in order; it takes about 30–40 minutes (mostly waiting for downloads). If your screen looks different from what is described here, stop and send a photo of the screen to the person helping you install.

> **About the language**: the installer and the summary emails speak Traditional Chinese, and so does scribe2md for now (English and Traditional Chinese editions of scribe2md are planned). Wherever you will see Chinese text on screen, this guide quotes it exactly and gives the English meaning next to it, so you can match what you see; if your scribe2md already shows English, follow the English names given in parentheses. In the installer you can almost always just press Enter to accept the default answer.

## 1. Install iCloud for Windows

1. Open **Microsoft Store** from the Start menu, search for **iCloud** and install it
2. Open iCloud, sign in with the same Apple Account as your iPhone, check **iCloud Drive** and click **Apply**
3. Open File Explorer: if you see **iCloud Drive** (`C:\Users\<your name>\iCloudDrive`) in the left sidebar, you're set

## 2. Install Claude Code and sign in

1. Type `PowerShell` in the Start menu and open **Windows PowerShell**
2. Paste this line (right-click pastes) and press Enter:
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
3. When it finishes, **close this window and open a new PowerShell**, type `claude` and press Enter. When asked for a sign-in method, choose **Claude account (subscription)**. Your browser opens the Claude sign-in page; sign in with your own account and click **Authorize**
4. Back in PowerShell, when you see a prompt where you can type, you're signed in. Type `/exit` and press Enter to leave

## 3. Install scribe2md (turns recordings and documents into text)

1. In your browser, open <https://github.com/VincentLiang1/scribe2md/releases/latest>. Under **Assets** near the bottom of the page, click **scribe2md-win.zip** to download it
2. In your Downloads folder, right-click the zip → **Extract All**, and extract it somewhere easy to remember (for example `C:\scribe2md`)
3. Open the extracted folder (it contains one more `scribe2md` folder inside) and, as its README says, double-click **安裝.bat** ("install"), then wait for it to finish. **Remember where this folder is**: in step 5 the installer searches two levels deep under `C:\`, Downloads, Desktop and Documents; if you put it deeper, it won't be found and you'll have to paste the path yourself

## 4. (Optional, can be done later) Create a Gmail app password

The daily summary is sent through Gmail. If you don't want the email you can skip this and set it up later by running `安裝.bat` again.

1. In your browser, open <https://myaccount.google.com/security> and make sure **2-Step Verification** is on
2. Open <https://myaccount.google.com/apppasswords>, type `wiki-agent` as the name and click **Create**
3. A 16-letter password appears — **keep that page open**; you'll need it in step 5

## 5. Install wiki-agent

1. In your browser, open <https://github.com/VincentLiang1/wiki-agent>, click **安裝.bat** ("install") in the file list, then click the **Download raw file** icon at the top right and save it to your Downloads folder. If the browser warns that this kind of file may be harmful, choose **Keep**
2. Double-click the downloaded **安裝.bat**. If a blue security warning appears ("Windows protected your PC" or similar), click **More info** → **Run anyway**
3. The black window first lists `開始之前請先做好這三件事` ("before you start, please do these three things" — steps 1–3 above); press any key to continue
4. If Git or uv is missing, it installs them (you may be asked "Do you want to allow this app to make changes?" — click **Yes**)
5. When asked `程式要放在哪個資料夾?` ("which folder should the program go in?"), just press Enter (`C:\wiki-feeder`). It downloads the program from GitHub and installs what it needs; **no GitHub account is required**
6. While enabling Windows long path support, a **User Account Control** prompt appears — click **Yes** (this is the only step that needs administrator rights; it isn't asked if already enabled)

### 5-1. Answer the questions

Every question ends with `(直接按 Enter = …)` ("press Enter = …", showing the default). **Pressing Enter is almost always the right answer**:

| Question on screen | What to do |
| --- | --- |
| Checking Claude Code | Automatic. It continues only after showing `✓ …(已登入)` ("signed in"); if it says you're not signed in, go back to step 2 |
| `【收件匣】` (inbox) | Enter (the `_WikiBox` folder in iCloud Drive). If asked `還沒有,要建立嗎?` ("doesn't exist yet, create it?"), press Enter again |
| `【知識庫】` (knowledge base) | If you already have a WIKI folder set up following the handout, copy its path from File Explorer's address bar, paste it and press Enter. If not, just press Enter, and press Enter again when asked whether to create it |
| `【原件資料夾】` (originals folder) | Enter (`Raw_Sources`, next to WIKI); for a new knowledge base it asks `還沒有,要建立嗎?` ("create it?") — press Enter again |
| `要照講義請 Claude 建好規則檔與目錄索引嗎?` ("Ask Claude to create the rules file and table of contents following the handout?") | (Asked only when there is no `CLAUDE.md` yet) Enter. Claude spends 1–3 minutes writing `CLAUDE.md` and the table of contents `index.md`, then describes in two or three sentences what it created |
| `要在 CLAUDE.md 最後補上「版本紀錄由 wiki-feeder 代管」嗎?` ("Add a 'version history is managed by wiki-feeder' section at the end of CLAUDE.md?") | Enter (yes). Your existing rules are not changed; one section is added at the end |
| `【知識庫名稱】` (knowledge base name) | Press Enter, or type a name you like |
| `【轉寫】` (transcription) | It lists the doc2md it found; press Enter to pick the first one. It test-converts a small file; when it says `可以用` ("works"), you're through. If it says `找不到 meeting-scribe` ("meeting-scribe not found"), paste the full path of `.venv\Scripts\doc2md.exe` inside the folder from step 3 |
| `【摘要信】` (summary email) — the Gmail address to send from | Defaults to the Gmail you signed in to Claude with; type `-` if you don't want emails |
| Recipient address | Enter (send to yourself) |
| `要(重新)輸入 Gmail 應用程式密碼嗎?` ("enter (again) the Gmail app password?") | Enter |
| Gmail app password | Paste the 16 letters from step 4 (nothing is shown while you type) and press Enter. A test email is sent |
| Can it read the inbox | Automatic. `iCloud	可讀` ("readable") means it's fine |
| Installing the schedule | Automatic |

If you run `安裝.bat` again later (for example, to set up the summary email), it first shows the current settings and asks `沿用這份(不重填)?` ("keep these settings (don't re-enter)?"): type `n` if you want to change them.

When you see `✓ 安裝完成` ("installation complete") you can close the window. From then on it runs in the background every minute and **never pops up a window**.

## 6. Check that it really works

1. On the iPhone, open the **Files** app → **iCloud Drive** → **_WikiBox** and drop a file into it
2. Wait a few minutes. Open your knowledge base `WIKI\Wiki_Pages` in File Explorer: a new page appears, and the original file is filed into a topic folder under `Raw_Sources`
3. If you set up the summary email, you'll receive one titled `wiki-feeder 攝入摘要` ("wiki-feeder ingest summary")

If nothing happens, check the log: paste `%LOCALAPPDATA%\wiki-feeder\logs` into File Explorer's address bar, open `feeder.log` and look at the last few lines.

## 7. (Optional) Share voiceprints between phone and computer

Speakers you have named in the scribe2md iPhone app or in scribe2md on the PC are then recognized on the other device too. This is a scribe2md feature; wiki-agent needs no setup. Just choose **the same folder in iCloud Drive** on every device.

1. Open **iCloud Drive** in File Explorer and create a folder `_聲紋同步` ("voiceprint sync") at the top level. ⚠️ **Do not put it inside `_WikiBox`** (files there are sent into the knowledge base, and the voiceprints and real names would go with them)
2. Right-click `_聲紋同步` → **Always keep on this device** (skip this if the option isn't there)
3. On the PC, open scribe2md (`AI 文件.MD 轉換器` on the desktop) → the `聲音→MD` (audio → MD) tab → `名單與聲紋` (names and voiceprints). At the bottom of the middle column `聲紋資料管理` (voiceprint data), under `聲紋同步資料夾` (voiceprint sync folder), click `選擇資料夾…` (choose folder…) and pick the `_聲紋同步` folder. The screen and the folder picker say "a folder in OneDrive", but one in iCloud Drive works too; a folder inside (or containing) `_WikiBox` is refused
4. On the iPhone, open the scribe2md app → `設定` (Settings) → under `聲紋與名單` (voiceprints and names), `聲紋同步資料夾` (voiceprint sync folder) → **iCloud Drive** → `_聲紋同步`. If Settings doesn't have this item, the app is still in "transcripts only" mode: go to `設定 › 模式` (Settings › Mode) and switch to `送進知識庫` ("send to knowledge base") — this needs an activation password; ask the person who set it up for you

Once set up, `上次同步` ("last synced") at the bottom of that column on the PC, and the area under `立即同步` ("sync now") on the phone, show when the other device last made a change.

⚠️ When wiki-agent transcribes recordings automatically it does not apply voiceprints; the transcript says `講者1`, `講者2` ("Speaker 1", "Speaker 2"). If you want names, transcribe and name the speakers in the phone app or scribe2md first, then put the transcript into `_WikiBox`.

## Updating

Double-click **更新.bat** ("update") in `C:\wiki-feeder`. If a file is being processed, it waits for that round to finish before updating; it never cuts it off midway.

## Uninstalling

- **Stop automatic processing only**: double-click **移除排程.bat** ("remove schedule") in `C:\wiki-feeder`. Settings, logs and your knowledge base are untouched; to turn it back on, run **安裝.bat** again
- **Remove everything**: do the step above, then delete `C:\wiki-feeder` and `%LOCALAPPDATA%\wiki-feeder`. **Your knowledge base (`WIKI`, `Raw_Sources`) is in neither place and will not be deleted**

## When something goes wrong

- **The email subject starts with `⚠️ 需要處理` ("action needed")**: open PowerShell, type `cd C:\wiki-feeder; claude`, paste the whole email into Claude and ask it to handle it according to wiki-agent's rules (you can write to Claude in English)
- **`Claude Code 沒登入或登入過期` ("Claude Code is not signed in or the sign-in expired")**: type `claude` in PowerShell and sign in again; the next round picks up where it left off
- **Don't run git in the knowledge base yourself** (including asking Claude to commit for you): the program only accepts versions it has verified itself; one extra commit makes it stop and wait for a person
