# How Notetaker Fits Together

**English** | [繁體中文](How-Notetaker-Fits-Together.zh-TW.md) | [简体中文](How-Notetaker-Fits-Together.zh-CN.md)

**Start with the Notetaker app on your phone, add Notetaker Desktop, and let Wiki Agent tie them together into an automated LLM Wiki. Three levels: install only as much as you need.**

![How Notetaker Fits Together: the Notetaker app and Notetaker Desktop sync voiceprints and lists; tapping Send on the phone, or clicking Send to LLM Wiki in Notetaker Desktop, puts files in the _WikiBox folder in a cloud drive; Wiki Agent + Scribe2MD checks it every minute, transcribes, and writes linked pages into the LLM Wiki on your computer](How-Notetaker-Fits-Together.svg)

## Level 1: Phone only

- Record, tell speakers apart, get a transcript
- Offline AI drafts the meeting notes
- Share with colleagues, or hand to ChatGPT or Claude

## Level 2: Add Notetaker Desktop

- Record online meetings, transcribe existing audio
- Turn Word, PDF and slides into AI-ready md
- Voiceprints and lists sync with your phone

Free for Windows and Mac: see the [Notetaker Desktop guide](https://github.com/VincentLiang1/notetaker-desktop/blob/main/README.md) (download links at the top).

## Level 3: Automatic knowledge base

- Tap Send; Wiki Agent on your computer picks it up
- Audio becomes text, filed into your LLM Wiki
- Links to what you already have, grows over time
- Can run on the Level 2 computer, or on a separate always-on one

Needs an always-on computer (it can be the one running Notetaker Desktop; with just a phone and no Notetaker Desktop it works too) and a paid Claude plan (Pro or higher). The `_WikiBox` inbox folder lives in a cloud drive, depending on what sends the files: iPhone uses iCloud Drive, Android uses Google Drive; Notetaker Desktop prefers OneDrive on Windows and iCloud Drive on Mac (the other two also work). The installer asks which ones to watch; the others are ignored. Wiki Agent checks the inbox every minute.

- New to LLM Wiki? See [What is an LLM Wiki?](What-is-LLM-Wiki.md)
- About Wiki Agent & setup: [README](README.md), [Mac install guide](Mac-Install-Guide.md), [Windows install guide](Windows-Install-Guide.md)

## What is Scribe2MD

- The transcription engine inside Notetaker Desktop
- Built into Notetaker Desktop: install that to convert files, or for the doc2md skill in Claude Code
- Wiki Agent installs and updates it for you; no separate install

The Wiki Agent installer offers to download Scribe2MD (about 1 GB, optional). Without it Claude reads documents and photos directly, and recordings and video wait until it is installed.

- What it converts and how to get it: see [Scribe2MD](Scribe2MD.md)
