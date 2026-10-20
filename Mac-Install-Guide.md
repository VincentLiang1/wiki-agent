# wiki-agent Installation Guide for Mac

[繁體中文](Mac安裝說明.md) | **English**

Follow the steps in order; it takes about 30–40 minutes (mostly waiting for downloads). Each step says where to go, what to click and what you should see. If your screen looks different from what is described here, stop and send a photo of the screen to the person helping you install.

> **About the language**: the installer and the summary emails speak Traditional Chinese, and so does scribe2md for now (English and Traditional Chinese editions of scribe2md are planned). Wherever you will see Chinese text on screen, this guide quotes it exactly and gives the English meaning next to it, so you can match what you see; if your scribe2md already shows English, follow the English names given in parentheses. In the installer you can almost always just press Enter to accept the default answer.

## 0. Make sure iCloud Drive is turned on

1.  menu (top left) → **System Settings** → click **your name** at the top → **iCloud** → **iCloud Drive**: the switch must be on (signed in with the same Apple Account as your iPhone)
2. Open **Finder**: if you see **iCloud Drive** in the left sidebar, you're set

## 1. Open Terminal

You'll need it for several steps: press **⌘ + Space** (Spotlight), type `Terminal`, press Enter. A window with plain text on a white (or black) background appears — that's Terminal. **Paste a command with ⌘V and press Enter to run it.**

## 2. Install Claude Code and sign in

1. Paste this line into Terminal and press Enter:
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```
   When it finishes it says the installation succeeded (if it asks you to add a folder to your PATH, paste and run the line it prints)
2. Type `claude` and press Enter. The first time, it asks for a color theme (just press Enter), then a sign-in method — choose **Claude account (subscription)**. Your browser opens the Claude sign-in page; sign in with your own account and click **Authorize**
3. Back in Terminal, when you see a prompt where you can type, you're signed in. Type `/exit` and press Enter to leave

## 3. Install scribe2md (turns recordings and documents into text)

1. In your browser, open <https://github.com/VincentLiang1/scribe2md/releases/latest>. Under **Assets** near the bottom of the page, click **scribe2md-mac.zip** to download it
2. Open your Downloads folder, double-click the zip to extract it, and **drag the extracted app into the Applications folder**
3. Open Applications and **double-click the app once**. The first launch sets up its environment and takes a few minutes (it shows progress). When you see the main window you can quit it (⌘Q)

## 4. (Optional, can be done later) Create a Gmail app password

The daily summary is sent through Gmail. If you don't want the email you can skip this and set it up later by running the one-line command in step 5 again.

1. In your browser, open <https://myaccount.google.com/security> and make sure **2-Step Verification** is on
2. Open <https://myaccount.google.com/apppasswords>, type `wiki-agent` as the name and click **Create**
3. A 16-letter password appears — **keep that page open**; you'll need it in step 5 (it is shown only once)

## 5. Install wiki-agent

Paste this line into Terminal and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
```

### 5-1. Command line developer tools (first time only)

A window pops up: *"The "git" command requires the command line developer tools. Would you like to install the tools now?"*

- Click **Install** (not "Get Xcode") → click **Agree** on the license → wait for the progress bar (about 5–15 minutes) → click **Done**
- Terminal carries on by itself; you don't need to paste the line again

It then installs uv, downloads the program into the `wiki-agent` folder in your home folder and prepares the Python environment (a few minutes the first time).

### 5-2. Answer the questions

Every question ends with `(直接按 Enter = …)` ("press Enter = …", showing the default). **Pressing Enter is almost always the right answer**:

| Question on screen | What to do |
| --- | --- |
| Checking Claude Code | Automatic. It continues only after showing `✓ …(已登入)` ("signed in"); if it says you're not signed in, go back to step 2 |
| `【收件匣】` (inbox) | Enter (the `_WikiBox` folder in iCloud Drive). If asked `還沒有,要建立嗎?` ("doesn't exist yet, create it?"), press Enter again |
| `【知識庫】` (knowledge base) | If you already have a WIKI folder set up following the handout, **drag it from Finder into the Terminal window** and press Enter. If not, just press Enter, and press Enter again when asked whether to create it |
| `【原件資料夾】` (originals folder) | Enter (`Raw_Sources`, next to WIKI) |
| `要照講義請 Claude 建好規則檔嗎?` ("Ask Claude to create the rules file following the handout?") | (Asked only for a new knowledge base) Enter. Claude spends 1–3 minutes writing `CLAUDE.md` and the table of contents `index.md`, using your Claude quota |
| `要在 CLAUDE.md 最後補上「版本紀錄由 wiki-feeder 代管」嗎?` ("Add a 'version history is managed by wiki-feeder' section at the end of CLAUDE.md?") | Enter (yes). Your existing rules are not changed; one section is added at the end |
| `【知識庫名稱】` (knowledge base name) | The name shown in the summary email. Press Enter, or type a name you like |
| `【轉寫】` (transcription) | Automatic: it finds the scribe2md you installed in step 3 and test-converts a small file. When it says `可以用` ("works"), you're through |
| `【摘要信】` (summary email) — the Gmail address to send from | Defaults to the Gmail you signed in to Claude with; type another address to use a different one; type `-` if you don't want emails |
| Gmail app password | Paste the 16 letters from step 4 (**nothing is shown while you type** — just paste and press Enter). A test email is sent; if it arrives on your phone, it worked |
| Can it read the inbox | Automatic. `iCloud	可讀` ("readable") means it's fine |
| Installing the schedule | Automatic. You'll see two lines ending in `:已裝好` ("installed") |

### 5-3. Full Disk Access (required)

The schedule runs in the background, and macOS requires you to separately allow it to read iCloud Drive. The installer automatically opens **System Settings → Privacy & Security → Full Disk Access**, and Terminal prints a long path (ending in something like `python3.12`):

1. In Terminal, **select that path and copy it with ⌘C**
2. In System Settings, click **+** below the list (you'll be asked for your Mac password or Touch ID)
3. When the file picker opens, press **⌘ + Shift + G**, paste the path with ⌘V, press Enter, then click **Open**
4. A new entry `python3.12` (or similar) appears in the list — **make sure its switch on the right is on**
5. Go back to Terminal and press Enter. It test-reads the inbox in the background; `✓ launchd 底下讀得到收件匣` ("the inbox is readable under launchd") means you're done. If it says it can't read it, repeat 1–4

When you see `✓ 安裝完成` ("installation complete") you can close Terminal.

## 6. Check that it really works

1. On the iPhone, open the **Files** app → **iCloud Drive** → **_WikiBox** and drop any file into it (for example, share a recording from Voice Memos, or save a photo of a whiteboard here)
2. Wait a few minutes (longer recordings take longer). In Finder, open `SOURCE5/WIKI/Wiki_Pages` in your home folder (or the knowledge base you chose): a new page appears, and the original file is filed into a topic folder under `Raw_Sources`
3. If you set up the summary email, you'll receive one titled `wiki-feeder 攝入摘要` ("wiki-feeder ingest summary")

If nothing happens, check the log: in Finder press **⌘ + Shift + G**, paste `~/Library/Application Support/wiki-feeder/logs`, open `feeder.log` and look at the last few lines.

## 7. (Optional) Share voiceprints between phone and computer

Speakers you have named in the scribe2md iPhone app or in scribe2md on the Mac are then recognized on the other device too. This is a scribe2md feature; wiki-agent needs no setup. Just choose **the same folder in iCloud Drive** on every device.

1. Open **iCloud Drive** in Finder and create a folder `_聲紋同步` ("voiceprint sync") at the top level (right-click → **New Folder**). ⚠️ **Do not put it inside `_WikiBox`** (files there are sent into the knowledge base, and the voiceprints and real names would go with them)
2. Right-click `_聲紋同步` → **Keep Downloaded** (skip this if the option isn't there)
3. On the Mac, open scribe2md (`AI 文件.MD 轉換器` in Applications) → the `聲音→MD` (audio → MD) tab → `名單與聲紋` (names and voiceprints). At the bottom of the middle column `聲紋資料管理` (voiceprint data), under `聲紋同步資料夾` (voiceprint sync folder), click `選擇資料夾…` (choose folder…) and pick the `_聲紋同步` folder. The screen and the folder picker say "a folder in OneDrive", but one in iCloud Drive works too; a folder inside (or containing) `_WikiBox` is refused
4. On the iPhone, open the scribe2md app → `設定` (Settings) → under `聲紋與名單` (voiceprints and names), `聲紋同步資料夾` (voiceprint sync folder) → **iCloud Drive** → `_聲紋同步`. If Settings doesn't have this item, the app is still in "transcripts only" mode: go to `設定 › 模式` (Settings › Mode) and switch to `送進知識庫` ("send to knowledge base") — this needs an activation password; ask the person who set it up for you

Once set up, `上次同步` ("last synced") at the bottom of that column on the Mac, and the area under `立即同步` ("sync now") on the phone, show when the other device last made a change.

⚠️ When wiki-agent transcribes recordings automatically it does not apply voiceprints; the transcript says `講者1`, `講者2` ("Speaker 1", "Speaker 2"). If you want names, transcribe and name the speakers in the phone app or scribe2md first, then put the transcript into `_WikiBox`.

## Updating

In Finder, open the **wiki-agent** folder in your home folder → double-click **更新.command** ("update"; the first time macOS asks whether you're sure you want to open it — click **Open**). If a file is being processed, Terminal says it is waiting for the current round to finish; then it downloads the new version. When you see `✓ 更新好了` ("updated"), press Enter to close. You don't need to reinstall the schedule.

If it says Python changed version and the executable must be added to Full Disk Access again, repeat step 5-3 with the new path it prints.

## Uninstalling

- **Stop automatic processing only**: double-click **移除排程.command** ("remove schedule") in the wiki-agent folder. Settings, logs and your knowledge base are untouched; to turn it back on, paste the line from step 5 again
- **Remove everything**: do the step above, then move the `wiki-agent` folder in your home folder and `~/Library/Application Support/wiki-feeder` (⌘⇧G, paste this path) to the Trash. **Your knowledge base (`WIKI`, `Raw_Sources`) is in neither place and will not be deleted.** You can also remove the Full Disk Access entry in System Settings with **−**

## When something goes wrong

- **The email subject starts with `⚠️ 需要處理` ("action needed")**: open Terminal, type `cd ~/wiki-agent && claude`, paste the whole email into Claude and ask it to handle it according to wiki-agent's rules (you can write to Claude in English)
- **`Claude Code 沒登入或登入過期` ("Claude Code is not signed in or the sign-in expired")**: type `claude` in Terminal and sign in again; the next round picks up where it left off
- **It can't read the inbox**: usually Full Disk Access is missing or switched off — check step 5-3. You can also run `.venv/bin/python scripts/macsched.py check` in the wiki-agent folder to test-read it
- **Don't run git in the knowledge base yourself** (including asking Claude to commit for you): the program only accepts versions it has verified itself; one extra commit makes it stop and wait for a person
