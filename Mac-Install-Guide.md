# wiki-agent Installation Guide for Mac

**English** | [繁體中文](Mac-Install-Guide.zh-TW.md) | [简体中文](Mac-Install-Guide.zh-CN.md)

Follow the steps in order; it takes about 30–40 minutes (mostly waiting for downloads). Each step says where to go, what to click and what you should see. If your screen looks different from what is described here, stop and send a photo of the screen to the person helping you install.

> **About the language**: the installer, the summary emails and the alerts come in English, Traditional Chinese or Simplified Chinese — the installer's first question asks which one. scribe2md (the transcription app) is in Chinese for now; English and Traditional Chinese editions are planned. For its screens this guide quotes the Chinese text and gives the English meaning in parentheses; if your scribe2md already shows English, follow those English names.

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

The daily summary is sent through Gmail. If you don't want the email you can skip this and set it up later by double-clicking wiki-agent again.

1. In your browser, open <https://myaccount.google.com/security> and make sure **2-Step Verification** is on
2. Open <https://myaccount.google.com/apppasswords>, type `wiki-agent` as the name and click **Create**
3. A 16-letter password appears — **keep that page open**; you'll need it in step 5 (it is shown only once)

## 5. Install wiki-agent

1. In your browser, open <https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-mac.zip>; it downloads **wiki-agent-mac.zip**
2. Open your Downloads folder, double-click the zip to unpack it, and **drag the unpacked wiki-agent into the Applications folder**. ⚠️ Move it first: if you double-click it inside Downloads, it asks you to move it
3. Open Applications and **double-click wiki-agent**. The first time macOS asks whether you're sure you want to open an app downloaded from the internet — click **Open**
4. A Terminal window opens on its own; continue below

**First, pick the language** (before anything is installed; from then on the screens, questions, summary emails, alerts and a newly created knowledge base use only that language, and the questions won't ask again):

```
語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English(Enter = English)
```

Type `3` and press Enter (if your Mac is set to English, just press Enter; when you run setup again, Enter keeps the language you chose last time).

(Alternative: pasting `curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash` into Terminal installs the same thing with the same questions, but then you also have to add an executable to Full Disk Access; Terminal shows you how.)

### 5-1. Command line developer tools (first time only)

Terminal shows `=== 1/4 Command Line Tools (git) ===` and a window pops up: *"The "git" command requires the command line developer tools. Would you like to install the tools now?"*

- Click **Install** (not "Get Xcode") → click **Agree** on the license → wait for the progress bar (about 5–15 minutes) → click **Done**
- Terminal carries on by itself; you don't need to paste the line again

It then goes through `=== 2/4 uv (Python environment manager) ===` and `=== 3/4 Downloading the program to … ===` (into the `wiki-agent` folder in your home folder) and prepares the Python environment (a few minutes the first time). At `=== 4/4 Settings ===` the questions begin.

### 5-2. Answer the questions

Every question ends with `(Enter = …)` showing the default, and yes/no questions end with `(Y/n)` — **pressing Enter is almost always the right answer**:

| Question on screen | What to do |
| --- | --- |
| `=== Checking Claude Code ===` | Automatic. It continues only after showing `✓ … (signed in)`; if it says `✗ Claude Code isn't signed in`, go back to step 2 |
| `[Knowledge base] Do you already have an LLM Wiki (a knowledge base folder with a CLAUDE.md)?` | If you already have one (its folder contains a `CLAUDE.md`): Enter or `y`. If not: `n` |
| `[CLAUDE.md] The CLAUDE.md in your knowledge base (or the knowledge base folder)` | (Asked only if you have one) If the program found it, just press Enter; otherwise **drag the knowledge base folder (or its `CLAUDE.md`) from Finder into the Terminal window** and press Enter. The program reads `CLAUDE.md` to find the originals folder and where new files go (only if it can't tell does it ask Claude to read it, a few seconds), shows them, and asks you to confirm — press Enter if they're right (new files go to the folder your `CLAUDE.md` names, whatever it's called). If you pick an originals folder or inbox that differs from `CLAUDE.md`, it asks once more, defaulting to the one in `CLAUDE.md` |
| `[Knowledge base] The WIKI folder: the knowledge base itself (…)` | (Asked only for a new one) Just press Enter, and press Enter again when asked whether to create it. `WIKI` is the knowledge base itself: it holds the rules file `CLAUDE.md` and the notes the AI organizes; `Raw_Sources` next to it holds the originals. For what the folders look like, see "What does the knowledge base look like?" in [What is an LLM Wiki?](What-is-LLM-Wiki.md) |
| `[Originals folder] Raw_Sources (…)` | (Asked only for a new one) Enter (`Raw_Sources`, next to WIKI) |
| `⚠ … is in iCloud Drive` (or OneDrive, Dropbox …) | Only shown when the knowledge base or originals folder is inside a sync folder. **Don't put them in OneDrive, iCloud Drive, Dropbox, Google Drive or similar sync folders** (including a synced Documents / Desktop): files may stay only in the cloud, edits from another device create conflict copies, and the knowledge base's version history breaks when it is synced. Press Enter to pick another place (`LLMWiki` in your home folder is suggested); an existing knowledge base you move yourself, then run the installer again. If you insist: type `2`, read the consequences and type `yes` — the version history (git) is then kept in this computer's wiki-feeder folder instead of the sync folder; conflict copies and cloud-only files still happen |
| `[Inbox] The folder the iPhone drops files into (_WikiBox in iCloud Drive)` | Enter. If asked whether to create it, press Enter again |
| `[scribe2md sync folder] Did you do step 7 of the guide (share voiceprints and the name-correction table between phone and computer)?` | Enter (**n**) unless you did step 7. If you did: **y**, then Enter to accept the suggested `_ScribeSync` next to `_WikiBox`, or paste the folder you created. A folder inside `_WikiBox`, the originals folder or the knowledge base is refused |
| `… has no CLAUDE.md yet. Ask Claude to create the rules file and table of contents?` | (Asked only for a new knowledge base) Enter. Claude spends 1–3 minutes writing `CLAUDE.md` and the table of contents `index.md` — in the language you picked — using your Claude quota |
| `Add a section at the end of CLAUDE.md saying "version history is managed by wiki-feeder; don't run git yourself"?` | Enter (yes). Your existing rules are not changed; one section is added at the end |
| `[Knowledge base name] Name shown in the summary email` | Press Enter (`Knowledge base`), or type a name you like |
| `[Transcription] …` | Automatic: it finds the scribe2md you installed in step 3 and test-converts a small file. When it says `works`, you're through |
| `[Summary email] …` then `Sending Gmail address` | Defaults to the Gmail you signed in to Claude with; type another address to use a different one; type `-` if you don't want emails |
| `Gmail app password (16 characters, not shown as you type)` | Paste the 16 letters from step 4 (**nothing is shown while you type** — just paste and press Enter). A test email is sent; if it arrives on your phone, it worked |
| `=== Can the inbox be read? (in Terminal) ===` | Automatic. `iCloud	readable` means it's fine |
| `=== Installing the schedule (one round per minute) ===` | Automatic. You'll see three lines ending in `: installed` (the third is a light watchdog every 3 minutes: it puts a stuck round or a schedule that isn't running into the summary email, and restarts iCloud when it gets stuck) |

### 5-3. Allow reading (required)

The schedule runs in the background, and macOS asks you to allow it to read iCloud Drive. When Terminal says to press Enter when you're ready, press Enter:

1. A window `“wiki-agent” would like to access files in iCloud Drive` appears — click **Allow**. This also lets wiki-agent read iCloud's sync status: every 15 minutes it restarts this Mac's iCloud sync process (a pause of a few seconds) — iCloud on a Mac sometimes gets stuck, the phone has uploaded a file but this Mac never downloads it, and only a restart fixes that
2. If your knowledge base is in Documents or Desktop, it asks once more — click **Allow** again
3. `✓ The inbox can be read under launchd` means you're done. If it can't read, turn the switch on as described under "It can't read the inbox" in *When something goes wrong*, then try again

When you see `✓ Installation complete.` you can close Terminal.

## 6. Check that it really works

1. On the iPhone, open the **Files** app → **iCloud Drive** → **_WikiBox** and drop any file into it (for example, share a recording from Voice Memos, or save a photo of a whiteboard here)
2. Wait a few minutes (longer recordings take longer). In Finder, open `LLMWiki/WIKI/Wiki_Pages` in your home folder (or the knowledge base you chose): a new page appears, and the original file is filed into a topic folder under `Raw_Sources`
3. If you set up the summary email, you'll receive one titled `wiki-feeder ingest summary …`

If nothing happens, check the log: in Finder press **⌘ + Shift + G**, paste `~/Library/Application Support/wiki-feeder/logs`, open `feeder.log` and look at the last few lines.

## 7. (Optional) Share voiceprints and the name-correction table between phone and computer

Speakers you have named in the scribe2md iPhone app or in scribe2md on the Mac are then recognized on the other device too. This is a scribe2md feature; wiki-agent needs no setup. Just choose **the same folder in iCloud Drive** on every device.

1. Open **iCloud Drive** in Finder and create a folder `_ScribeSync` ("scribe2md sync": voiceprints and, later, the name-correction table) at the top level (right-click → **New Folder**). ⚠️ **Do not put it inside `_WikiBox`** (files there are sent into the knowledge base, and the voiceprints and real names would go with them)
2. Right-click `_ScribeSync` → **Keep Downloaded** (skip this if the option isn't there)
3. On the Mac, open scribe2md (`AI 文件.MD 轉換器` in Applications) → the `聲音→MD` (audio → MD) tab → `名單與聲紋` (names and voiceprints). At the bottom of the middle column `聲紋資料管理` (voiceprint data), under `聲紋同步資料夾` (voiceprint sync folder), click `選擇資料夾…` (choose folder…) and pick the `_ScribeSync` folder. The screen and the folder picker say "a folder in OneDrive", but one in iCloud Drive works too; a folder inside (or containing) `_WikiBox` is refused
4. On the iPhone, open the scribe2md app → `設定` (Settings) → under `聲紋與名單` (voiceprints and names), `聲紋同步資料夾` (voiceprint sync folder) → **iCloud Drive** → `_ScribeSync`. If Settings doesn't have this item, the app is still in "transcripts only" mode: go to `設定 › 模式` (Settings › Mode) and switch to `送進知識庫` ("send to knowledge base")
5. Tell wiki-agent where the folder is: the installer asks `[scribe2md sync folder] Did you do step 7 …?` — answer **y** and accept or paste the folder. If wiki-agent is already installed, run the installer again the same way you installed it, answer **n** to keeping the current settings, and fill in the questions again. Until the folder is in the settings, no name-correction table is produced

Once set up, `上次同步` ("last synced") at the bottom of that column on the Mac, and the area under `立即同步` ("sync now") on the phone, show when the other device last made a change.

Once this is set up, the phone also uses a **name-correction table** when it drafts meeting notes, to fix names, companies and terms that speech recognition got wrong. You don't maintain the table yourself: it builds up bit by bit as you correct Claude, and after each ingest round wiki-agent puts it into `_ScribeSync`, where the phone picks it up when it syncs (you can see it under `設定 › 離線 AI 會議草稿識別 › 名詞對照表` (Settings › offline AI meeting draft › name-correction table)). `_ScribeSync` has to be at the top level of iCloud Drive as in step 1 (you can name it differently; use the same name everywhere), and wiki-agent writes the table only into the folder you gave the installer in step 5.

**When you spot a mistake**: there is no file to edit. When a meeting page has a name, company or term wrong, open the Claude desktop app (on your knowledge base folder) and just tell it, for example:

- "On the 10/21 sales weekly page, 'Jon Smyth' should be 'Jon Smith'"
- "The 'Akme' that kept coming up in yesterday's meeting is our client Acme"
- "'Lin Da' is Linda, but only the sales weekly gets it wrong like this"
- "The 'Manager Chang' correction was wrong, remove it"

Claude fixes the page and also records the correction in the knowledge base's name-correction table (`memory/name-corrections.md`), so later meeting drafts and ingests use the right spelling. Two-character Chinese words are only replaced for the meeting series you name, so that common words are not changed in every meeting. (Claude only knows to record these if you agreed during installation to add the "name-correction table" section to CLAUDE.md; if you didn't, run the installation again)

⚠️ When wiki-agent transcribes recordings automatically it does not apply voiceprints; the transcript says `講者1`, `講者2` ("Speaker 1", "Speaker 2"). If you want names, transcribe and name the speakers in the phone app or scribe2md first, then put the transcript into `_WikiBox`.

## Updating

**Normally you don't need to do anything**: once a day the program checks for a new version and installs the newest version once it has been out for a day — it downloads the new wiki-agent and only switches if it is signed by the same developer and notarized by Apple; it waits for the round being processed to finish, then test-reads your inbox and knowledge base in the background, and if they can't be read it switches back to the previous version by itself. The old version is kept as a hidden `.wiki-agent-previous.app` in Applications as a fallback; you can ignore it. Each auto-update sends a separate email (if you set up the summary email):

- `wiki-feeder updated itself to …`: it worked; the email says what changed
- `wiki-feeder … is available: this version needs you to update it yourself`: this version has a step you need to do; update by hand as below
- `⚠️ Needs attention | wiki-feeder auto-update failed, rolled back to …`: it went back to the previous version and keeps running; no rush

If the daily summary shows the alert "Auto-update hasn't been able to check for days": on the days this computer was on, it couldn't check for new versions (days it was off or offline don't count), so auto-update itself may be broken. Update by hand once as below.

The log is `~/Library/Application Support/wiki-feeder/logs/update.log`. **To turn auto-update off**: open Terminal, paste `open -e ~/Library/Application\ Support/wiki-feeder/config.toml` and press Enter, add the line `auto_update = false` under `[general]`, and save.

To update right away (or when an email asks you to): repeat steps 1–3 of step 5: download the new zip, drag wiki-agent into Applications (click **Replace** if asked) and double-click it. Terminal puts the new program in place; when it asks whether to keep the current settings, press Enter. The schedule is replaced automatically; if a new version needs one more permission, a window appears during the final test read — click **Allow**. Permissions you already allowed don't need to be redone.

(If you installed with the Terminal command: it updates itself too; to update by hand, open the **wiki-agent** folder in your home folder in Finder → double-click **Update.command**. A version that changes the Python version is not installed automatically — you get an email asking you to update by hand. If it says Python changed version, add the new path it prints to Full Disk Access again.)

## Uninstalling

- **Stop automatic processing only**: in Finder, open the **wiki-agent** folder in your home folder and double-click **Remove-Schedule.command**. Settings, logs and your knowledge base are untouched; to turn it back on, double-click wiki-agent in Applications
- **Remove everything**: do the step above, then move wiki-agent in Applications, the `wiki-agent` folder in your home folder and `~/Library/Application Support/wiki-feeder` (⌘⇧G, paste this path) to the Trash. **Your knowledge base (`WIKI`, `Raw_Sources`) is in none of these places and will not be deleted.** Exception: if you chose to keep a sync folder during install, the knowledge base's version history is in `wiki-git` inside the `wiki-feeder` folder — deleting it loses the history, so move it out first if you want to keep it.

## When something goes wrong

- **The email subject starts with `⚠️ Needs attention`**: open Terminal, type `cd ~/wiki-agent && claude`, paste the whole email into Claude and ask it to handle it according to wiki-agent's rules (you can write to Claude in English)
- **The email says Claude Code is not signed in or the sign-in expired**: type `claude` in Terminal and sign in again; the next round picks up where it left off
- **It can't read the inbox**: usually "Don't Allow" was clicked: Apple menu  → **System Settings** → **Privacy & Security** → **Files and Folders** → **wiki-agent**, turn on iCloud Drive (and Documents/Desktop), then double-click wiki-agent again to re-check (if you installed with the Terminal command, Full Disk Access is missing or switched off)
- **You don't want wiki-agent to restart iCloud sync**: open `~/Library/Application Support/wiki-feeder/config.toml` in TextEdit, add the line `icloud_restart = false` under `[inbox]`, save, and double-click wiki-agent once. The log is `logs/icloud.log` in the same folder
- **Don't run git in the knowledge base yourself** (including asking Claude to commit for you): the program only accepts versions it has verified itself; one extra commit makes it stop and wait for a person
