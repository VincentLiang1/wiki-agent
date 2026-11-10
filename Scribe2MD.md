# Scribe2MD

**English** | [繁體中文](Scribe2MD.zh-TW.md) | [简体中文](Scribe2MD.zh-CN.md)

**The engine that turns documents, scans and recordings into Markdown. Runs offline on your own computer and uploads nothing.**

## What it converts

- Documents: PDF, Word, PowerPoint, Excel (including old .doc/.ppt/.xls), Outlook mail (.msg/.eml), .rtf, .mht
- Scans and photos: text recognition (OCR)
- Recordings and video (.m4a, .mp3, .wav, .mp4, .mov and more): a transcript split by speaker

Once in md, files work better with ChatGPT, Claude or a knowledge base than the originals: PDFs cost far fewer tokens, and Office files keep their tables and embedded images.

## How to get it

You don't install Scribe2MD yourself:

- **To convert files yourself, or to use the doc2md skill in Claude Code**: install [Notetaker Desktop](https://github.com/VincentLiang1/notetaker-desktop/releases/latest) (free, for Windows and Mac; see the [Notetaker Desktop guide](https://github.com/VincentLiang1/notetaker-desktop/blob/main/README.md)). Scribe2MD is built in; install the doc2md skill with "🤖 Install Claude Skill…" in Notetaker Desktop
- **If you use Wiki Agent**: the installer offers to download Scribe2MD (optional), and Wiki Agent keeps it up to date. Nothing else to do

The `scribe2md-core` files on Wiki Agent's releases page are a component the Wiki Agent installer downloads on its own; they are not meant to be downloaded by hand.

## The doc2md skill

Once installed, give Claude Code the path to a PDF, Word file, slide deck, scan or recording, and Claude converts it to md with Scribe2MD before reading it.
