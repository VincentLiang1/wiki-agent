# wiki-agent

**English** | [繁體中文](README.zh-TW.md) | [简体中文](README.zh-CN.md)



**Record on your iPhone — a new page appears in your knowledge base.**

wiki-agent is a small background program on your computer that maintains a personal knowledge base for you, following Andrej Karpathy's "LLM Wiki" pattern:

1. On your iPhone, drop a voice memo, whiteboard photo, scanned document or Office file into the `_WikiBox` folder on iCloud Drive
2. Every minute, wiki-agent on your computer checks that folder: it moves the file into your originals folder `Raw_Sources`, and turns recordings and documents into text first (using [scribe2md](https://github.com/VincentLiang1/scribe2md))
3. It asks *your own* Claude Code to compile the material into `WIKI/Wiki_Pages/` according to the rules in your wiki's `CLAUDE.md`: creating a new page or adding to an existing one, and updating the table of contents `index.md`
4. Only after the program has checked the result is it recorded as a version (git, managed by the program — you don't need to learn it). A daily summary email tells you what was processed

You do just two things: **drop files** and **read the summary**. If something is wrong, open Claude Code and say which entry to roll back.

> **Your files are never lost**: every move copies first and deletes the source only after the copy's content has been verified identical. If any step fails, the original stays where it is and is retried on the next round.

## Requirements

| | Mac | Windows |
| --- | --- | --- |
| Computer | Apple-silicon Mac (OS version as required by scribe2md) | Windows 10/11 |
| Phone | iPhone (files travel through iCloud Drive) | iPhone + iCloud for Windows on the PC |
| Claude | Your own Claude subscription (Pro or Max), with Claude Code installed and signed in | Same |
| Transcription | Mac version of [scribe2md](https://github.com/VincentLiang1/scribe2md/releases/latest) | Windows version of scribe2md |
| Summary email (optional) | Gmail + an app password | Same |

The knowledge base follows the layout of the "LLM Wiki beginner's handout (desktop edition)": one folder containing `WIKI/` (with a `CLAUDE.md` inside) and `Raw_Sources/` side by side. **Don't have one yet? No problem**: just press Enter during setup and the installer creates the folders and asks Claude to write a `CLAUDE.md` following the handout. An existing knowledge base is used as-is and never overwritten.

## Installation

Full step-by-step guides: **[Mac-Install-Guide.md](Mac-Install-Guide.md)** and **[Windows-Install-Guide.md](Windows-Install-Guide.md)**. The installer's first question picks the language — English, Traditional Chinese or Simplified Chinese — and the questions, summary emails, alerts and a newly created knowledge base all follow it. In short:

**Mac** (about 30–40 minutes, mostly downloads)

1. Make sure iCloud Drive is turned on (System Settings → your name → iCloud → iCloud Drive)
2. Install Claude Code and sign in with your Claude account: in Terminal run `curl -fsSL https://claude.ai/install.sh | bash`, then `claude`
3. Download `scribe2md-mac.zip` from the [scribe2md releases](https://github.com/VincentLiang1/scribe2md/releases/latest), drag the app into Applications and open it once so it can set itself up
4. (Optional) Create a Gmail app password at <https://myaccount.google.com/apppasswords> for the summary email
5. Download [wiki-agent-mac.zip](https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-mac.zip) (signed and notarized), unzip it, drag wiki-agent into Applications and double-click it there. A Terminal window opens: if macOS offers to install the command line developer tools, click **Install** (not "Get Xcode"). The installer then sets up uv, puts the program in `~/wiki-agent` and asks a series of questions — each has a default, so you can mostly just press Enter
6. **Allow reading (required)**: at the end it test-reads in the background and macOS asks whether “wiki-agent” may access files in iCloud Drive (and in Documents/Desktop if your knowledge base is there) — click **Allow**

Alternative to steps 5–6: paste this line into Terminal (then you add an executable to Full Disk Access instead; Terminal shows you how):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
   ```

**Windows**

1. Install iCloud for Windows, Claude Code (signed in) and the Windows version of scribe2md
2. (Optional) Create a Gmail app password for the summary email
3. Download `Install.bat` from this repository and double-click it. If Windows SmartScreen warns you, choose **More info → Run anyway**. It installs Git and uv if needed, puts the program in `C:\wiki-feeder` (no GitHub account needed) and asks the same questions (the screens before the questions follow your Windows display language)

Both installers finish by setting up a schedule that runs every minute. To check that it works, drop any file into `_WikiBox` from the iPhone's Files app; after a few minutes a new page appears under `WIKI/Wiki_Pages`, the original is filed into a topic folder under `Raw_Sources`, and (if configured) you receive a "wiki-feeder ingest summary" email.

- **Update**: double-click `Update.command` (Mac, in `~/wiki-agent`) or `Update.bat` (Windows, in `C:\wiki-feeder`). If a round is in progress, it waits for it to finish
- **Uninstall**: `Remove-Schedule.command` / `Remove-Schedule.bat` removes only the schedule; settings, logs and your knowledge base stay. To remove everything, also delete the program folder and the settings folder listed below — your `WIKI` and `Raw_Sources` are not in either and are never deleted

## Things to know

- **Your data is sent to the Anthropic API**: during ingestion Claude reads the original files (including photos). As with your normal Claude use, it runs on your own account and quota; one ingestion costs roughly US$0.3–1
- **Claude gets the minimum permissions**: it can read files and edit pages in the knowledge base, but cannot delete files, move originals, commit or push by itself. The program checks every change afterwards — if an original is missing, a page has been heavily cut, or stray files are left behind, it stops everything and emails you to take a look
- **Version history is managed by the program**: don't run git in the knowledge base yourself (including asking Claude to commit for you). One commit the program hasn't verified will halt automatic ingestion. Pages you edit by hand are fine — just save them; before the next ingestion the program records them as a "manual edit snapshot"
- Settings and logs live in `~/Library/Application Support/wiki-feeder/` (Mac) or `%LOCALAPPDATA%\wiki-feeder\` (Windows); the log is `logs/feeder.log`

## When something goes wrong

- **The email subject starts with "⚠️ Needs attention"**: open Terminal (Mac: `cd ~/wiki-agent && claude`) or PowerShell (Windows: `cd C:\wiki-feeder; claude`), paste the whole email into Claude and ask it to handle it according to wiki-agent's rules
- **"Claude Code is not signed in or the sign-in expired"**: run `claude` and sign in again; the next round picks up where it left off
- **Mac can't read the inbox**: usually Full Disk Access is missing or switched off — redo step 6 above

## License

Copyright © 2026 Vincent Liang. **All rights reserved.**

The source code is public only so that friends can install it easily. **It is not open-source software**: no permission is granted to copy, modify, distribute or use it commercially. For personal use, just follow the installation guides; for anything else, please contact the author first.
