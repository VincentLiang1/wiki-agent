# wiki-agent Installation Guide for Windows

**English** | [繁體中文](Windows-Install-Guide.zh-TW.md) | [简体中文](Windows-Install-Guide.zh-CN.md)

Follow the steps in order; it takes about 30–40 minutes (mostly waiting for downloads). If your screen looks different from what is described here, stop and send a photo of the screen to the person helping you install.

> **About the language**: the setup questions, the summary emails and the alerts come in English, Traditional Chinese or Simplified Chinese — the first question asks which one. The screens of `Install.bat` before that question follow your Windows display language (English unless Windows is set to Chinese). scribe2md, the transcription app, is still in Chinese (English and Traditional Chinese editions are planned); for its screens this guide quotes the Chinese text and gives the English meaning in parentheses.

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
3. Open the extracted folder (it contains one more `scribe2md` folder inside) and, as its README says, double-click **Install.bat**, then wait for it to finish. **Remember where this folder is**: in step 5 the installer searches two levels deep under `C:\`, Downloads, Desktop and Documents; if you put it deeper, it won't be found and you'll have to paste the path yourself

## 4. (Optional, can be done later) Create a Gmail app password

The daily summary is sent through Gmail. If you don't want the email you can skip this and set it up later by running `Install.bat` again.

1. In your browser, open <https://myaccount.google.com/security> and make sure **2-Step Verification** is on
2. Open <https://myaccount.google.com/apppasswords>, type `wiki-agent` as the name and click **Create**
3. A 16-letter password appears — **keep that page open**; you'll need it in step 5

## 5. Install wiki-agent

1. In your browser, open <https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-win.zip> to download **wiki-agent-win.zip** (**no GitHub account is required**). If the browser warns that this kind of file may be harmful, choose **Keep**
2. In your Downloads folder, right-click the zip → **Extract All** and change the destination to `C:\`; you get `C:\wiki-agent`. ⚠️ Don't extract it to the Desktop or Documents: those are often synced by OneDrive. Once OneDrive folder backup is on, the Documents and Desktop you see in File Explorer actually live at `C:\Users\<name>\OneDrive\Documents` and `OneDrive\Desktop`; `C:\Users\<name>\Documents` is then a different, local folder — same name, different folder. To check where a folder really is, open it, click the address bar at the top of File Explorer and look for `OneDrive` in the full path
3. Open `C:\wiki-agent` and double-click **Install.bat**. If a blue security warning appears ("Windows protected your PC" or similar), click **More info** → **Run anyway**

**First, pick the language** (before anything is installed; from then on the screens, questions, summary emails, alerts and a newly created knowledge base use only that language, and the questions won't ask again):

```
語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English(Enter = English)
```

Type `3` and press Enter (if Windows is set to English, just press Enter; when you run setup again, Enter keeps the language you chose last time).

4. It then lists `Before you start, please do these three things:` (steps 1–3 above); press any key to continue
5. If Git or uv is missing, it installs them (you may be asked "Do you want to allow this app to make changes?" — click **Yes**; the program uses Git to keep the version history of your knowledge base), then installs the packages it needs
6. While enabling Windows long path support, a **User Account Control** prompt appears — click **Yes** (this is the only step that needs administrator rights; it isn't asked if already enabled)

### 5-1. Answer the questions

Every question ends with `(Enter = …)` showing the default, and yes/no questions end with `(Y/n)` — **pressing Enter is almost always the right answer**:

| Question on screen | What to do |
| --- | --- |
| `=== Checking Claude Code ===` | Automatic. It continues only after showing `✓ … (signed in)`; if it says `✗ Claude Code isn't signed in`, go back to step 2 |
| `[Knowledge base] Do you already have an LLM Wiki (a knowledge base folder with a CLAUDE.md)?` | If you already have one (its folder contains a `CLAUDE.md`): Enter or `y`. If not: `n` |
| `[CLAUDE.md] The CLAUDE.md in your knowledge base (or the knowledge base folder)` | (Asked only if you have one) If the program found it, just press Enter; otherwise copy the knowledge base folder's path from File Explorer's address bar, paste it and press Enter. The program reads `CLAUDE.md` to find the originals folder and where new files go (only if it can't tell does it ask Claude to read it, a few seconds), shows them, and asks you to confirm — press Enter if they're right (new files go to the folder your `CLAUDE.md` names, whatever it's called). If you pick an originals folder or inbox that differs from `CLAUDE.md`, it asks once more, defaulting to the one in `CLAUDE.md` |
| `[Knowledge base] The WIKI folder: the knowledge base itself (…)` | (Asked only for a new one) Just press Enter, and press Enter again when asked whether to create it. `WIKI` is the knowledge base itself: it holds the rules file `CLAUDE.md` and the notes the AI organizes; `Raw_Sources` next to it holds the originals. For what the folders look like, see "What does the knowledge base look like?" in [What is an LLM Wiki?](What-is-LLM-Wiki.md) |
| `[Originals folder] Raw_Sources (…)` | (Asked only for a new one) Enter (`Raw_Sources`, next to WIKI); for a new knowledge base it asks whether to create it — press Enter again |
| `⚠ … is in iCloud Drive` (or OneDrive, Dropbox …) | Only shown when the knowledge base or originals folder is inside a sync folder. **Don't put them in OneDrive, iCloud Drive, Dropbox, Google Drive or similar sync folders** (including a synced Documents / Desktop; with OneDrive backup on they actually live under `C:\Users\<name>\OneDrive\`, which is a different folder from `C:\Users\<name>\Documents` even though both are called Documents. To see where your knowledge base is, click File Explorer's address bar inside its folder and look for `OneDrive` in the full path): files may stay only in the cloud, edits from another device create conflict copies, and the knowledge base's version history breaks when it is synced. Press Enter to pick another place (`LLMWiki` in your home folder is suggested); an existing knowledge base you move yourself, then run the installer again. If you insist: type `2`, read the consequences and type `yes` — the version history (git) is then kept in this computer's wiki-feeder folder instead of the sync folder; conflict copies and cloud-only files still happen |
| `[Inbox] The folder the iPhone drops files into (_WikiBox in iCloud Drive)` | Enter. If asked whether to create it, press Enter again |
| `[scribe2md sync folder] Did you do step 7 of the guide (share voiceprints and the name-correction table between phone and computer)?` | Enter (**n**) unless you did step 7. If you did: **y**, then Enter to accept the suggested `_ScribeSync` next to `_WikiBox`, or paste the folder you created. A folder inside `_WikiBox`, the originals folder or the knowledge base is refused |
| `… has no CLAUDE.md yet. Ask Claude to create the rules file and table of contents?` | (Asked only when there is no `CLAUDE.md` yet) Enter. Claude spends 1–3 minutes writing `CLAUDE.md` and the table of contents `index.md` in the language you picked, then describes in two or three sentences what it created |
| `Add a section at the end of CLAUDE.md saying "version history is managed by wiki-feeder; don't run git yourself"?` | Enter (yes). Your existing rules are not changed; one section is added at the end |
| `[Knowledge base name] Name shown in the summary email` | Press Enter (`Knowledge base`), or type a name you like |
| `[Transcription] Found these meeting-scribe doc2md installs:` | Press Enter to pick the first one. It test-converts a small file; when it says `works`, you're through. If it can't find scribe2md, paste the full path of `.venv\Scripts\doc2md.exe` inside the folder from step 3 |
| `[Summary email] …` then `Sending Gmail address` | Defaults to the Gmail you signed in to Claude with; type `-` if you don't want emails |
| `Recipient address` | Enter (send to yourself) |
| `Enter the Gmail app password (again)?` | Enter |
| `Gmail app password (16 characters, not shown as you type)` | Paste the 16 letters from step 4 and press Enter. A test email is sent |
| `=== Can the inbox be read? ===` | Automatic. `iCloud	readable` means it's fine |
| `=== Installing the schedule (one round per minute) ===` | Automatic |

If you run `Install.bat` again later (for example, to set up the summary email), it asks the language again, shows the current settings and asks `Keep this one (don't fill it in again)?`: type `n` if you want to change them.

When you see `✓ Installation complete.` you can close the window. From then on it runs in the background every minute and **never pops up a window**.

## 6. Check that it really works

1. On the iPhone, open the **Files** app → **iCloud Drive** → **_WikiBox** and drop a file into it
2. Wait a few minutes. Paste `%USERPROFILE%\LLMWiki\WIKI\Wiki_Pages` (or the full path of the knowledge base you chose) into the address bar at the top of File Explorer and press Enter — don't look for it under Documents in the left pane, which may be a different folder inside OneDrive: a new page appears, and the original file is filed into a topic folder under `Raw_Sources`
3. If you set up the summary email, you'll receive one titled `wiki-feeder ingest summary …`

If nothing happens, check the log: paste `%LOCALAPPDATA%\wiki-feeder\logs` into File Explorer's address bar, open `feeder.log` and look at the last few lines.

## 7. (Optional) Share voiceprints and the name-correction table between phone and computer

Speakers you have named in the scribe2md iPhone app or in scribe2md on the PC are then recognized on the other device too. This is a scribe2md feature; wiki-agent needs no setup. Just choose **the same folder in iCloud Drive** on every device.

1. Open **iCloud Drive** in File Explorer and create a folder `_ScribeSync` ("scribe2md sync": voiceprints and, later, the name-correction table) at the top level. ⚠️ **Do not put it inside `_WikiBox`** (files there are sent into the knowledge base, and the voiceprints and real names would go with them)
2. Right-click `_ScribeSync` → **Always keep on this device** (skip this if the option isn't there)
3. On the PC, open scribe2md (`AI 文件.MD 轉換器` on the desktop) → the `聲音→MD` (audio → MD) tab → `名單與聲紋` (names and voiceprints). At the bottom of the middle column `聲紋資料管理` (voiceprint data), under `聲紋同步資料夾` (voiceprint sync folder), click `選擇資料夾…` (choose folder…) and pick the `_ScribeSync` folder. The screen and the folder picker say "a folder in OneDrive", but one in iCloud Drive works too; a folder inside (or containing) `_WikiBox` is refused
4. On the iPhone, open the scribe2md app → `設定` (Settings) → under `聲紋與名單` (voiceprints and names), `聲紋同步資料夾` (voiceprint sync folder) → **iCloud Drive** → `_ScribeSync`. If Settings doesn't have this item, the app is still in "transcripts only" mode: go to `設定 › 模式` (Settings › Mode) and switch to `送進知識庫` ("send to knowledge base")
5. Tell wiki-agent where the folder is: the installer asks `[scribe2md sync folder] Did you do step 7 …?` — answer **y** and accept or paste the folder. If wiki-agent is already installed, run Install.bat again, answer **n** to keeping the current settings, and fill in the questions again. Until the folder is in the settings, no name-correction table is produced

Once set up, `上次同步` ("last synced") at the bottom of that column on the PC, and the area under `立即同步` ("sync now") on the phone, show when the other device last made a change.

Once this is set up, the phone also uses a **name-correction table** when it drafts meeting notes, to fix names, companies and terms that speech recognition got wrong. You don't maintain the table yourself: it builds up bit by bit as you correct Claude, and after each ingest round wiki-agent puts it into `_ScribeSync`, where the phone picks it up when it syncs (you can see it under `設定 › 離線 AI 會議草稿識別 › 名詞對照表` (Settings › offline AI meeting draft › name-correction table)). `_ScribeSync` has to be at the top level of iCloud Drive as in step 1 (you can name it differently; use the same name everywhere), and wiki-agent writes the table only into the folder you gave the installer in step 5.

**When you spot a mistake**: there is no file to edit. When a meeting page has a name, company or term wrong, open the Claude desktop app (on your knowledge base folder) and just tell it, for example:

- "On the 10/21 sales weekly page, 'Jon Smyth' should be 'Jon Smith'"
- "The 'Akme' that kept coming up in yesterday's meeting is our client Acme"
- "'Lin Da' is Linda, but only the sales weekly gets it wrong like this"
- "The 'Manager Chang' correction was wrong, remove it"

Claude fixes the page and also records the correction in the knowledge base's name-correction table (`memory/name-corrections.md`), so later meeting drafts and ingests use the right spelling. Two-character Chinese words are only replaced for the meeting series you name, so that common words are not changed in every meeting. (Claude only knows to record these if you agreed during installation to add the "name-correction table" section to CLAUDE.md; if you didn't, run the installation again)

⚠️ When wiki-agent transcribes recordings automatically it does not apply voiceprints; the transcript says `講者1`, `講者2` ("Speaker 1", "Speaker 2"). If you want names, transcribe and name the speakers in the phone app or scribe2md first, then put the transcript into `_WikiBox`.

## Updating

**Normally you don't need to do anything**: once a day the program checks for a new version and installs the newest version once it has been out for a day — it waits for the round being processed to finish, then test-reads your inbox and knowledge base, and if they can't be read it rolls back to the previous version by itself. Each auto-update sends a separate email (if you set up the summary email):

- `wiki-feeder updated itself to …`: it worked; the email says what changed
- `wiki-feeder … is available: this version needs you to update it yourself`: this version has a step you need to do; double-click Update.bat as below
- `⚠️ Needs attention | wiki-feeder auto-update failed, rolled back to …`: it went back to the previous version and keeps running; no rush

If the daily summary shows the alert "Auto-update hasn't been able to check for days": on the days this computer was on, it couldn't check for new versions (days it was off or offline don't count), so auto-update itself may be broken. Double-click Update.bat as described below to update by hand once.

The log is `%LOCALAPPDATA%\wiki-feeder\logs\update.log`. **To turn auto-update off**: open `%LOCALAPPDATA%\wiki-feeder\config.toml` in Notepad, add the line `auto_update = false` under `[general]`, and save.

To update right away (or when an email asks you to): double-click **Update.bat** in `C:\wiki-agent`. It downloads the new version from GitHub and replaces the files in the program folder; if a file is being processed, it waits for that round to finish before updating and never cuts it off midway. Settings, logs and your knowledge base are untouched.

(If you installed with an older version of this guide — only Install.bat, into `C:\wiki-feeder` — double-click the Update.bat there; it updates with Git. Read `C:\wiki-feeder` wherever this guide says `C:\wiki-agent`.)

## Uninstalling

- **Stop automatic processing only**: double-click **Remove-Schedule.bat** in `C:\wiki-agent`. Settings, logs and your knowledge base are untouched; to turn it back on, run **Install.bat** again
- **Remove everything**: do the step above, then delete `C:\wiki-agent` and `%LOCALAPPDATA%\wiki-feeder`. **Your knowledge base (`WIKI`, `Raw_Sources`) is in neither place and will not be deleted**. Exception: if you chose to keep a sync folder during install, the knowledge base's version history is in `wiki-git` inside the `wiki-feeder` folder — deleting it loses the history, so move it out first if you want to keep it.

## When something goes wrong

- **The email subject starts with `⚠️ Needs attention`**: open PowerShell, type `cd C:\wiki-agent; claude`, paste the whole email into Claude and ask it to handle it according to wiki-agent's rules (you can write to Claude in English)
- **The email says Claude Code is not signed in or the sign-in expired**: type `claude` in PowerShell and sign in again; the next round picks up where it left off
- **Don't run git in the knowledge base yourself** (including asking Claude to commit for you): the program only accepts versions it has verified itself; one extra commit makes it stop and wait for a person
