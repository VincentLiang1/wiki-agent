# Scribe2MD

[English](Scribe2MD.md) | **繁體中文** | [简体中文](Scribe2MD.zh-CN.md)

**把文件、掃描件、錄音轉成 Markdown 的轉檔核心。在自己的電腦上離線轉換，不上傳任何內容。**

## 能轉什麼

- 文件:PDF、Word、PowerPoint、Excel(含舊版 .doc/.ppt/.xls)、Outlook 郵件(.msg/.eml)、.rtf、.mht
- 掃描件與照片：做文字辨識(OCR)
- 錄音與影片(.m4a、.mp3、.wav、.mp4、.mov 等):轉成分講者的逐字稿

轉成 md 之後，丟給 ChatGPT、Claude 或放進知識庫都比原檔好用:PDF 省下大量 token,Office 檔保住表格與內嵌圖。

## 怎麼取得

Scribe2MD 不用自己裝:

- **要自己轉檔、或在 Claude Code 用 doc2md 技能**:裝[會議助手電腦版](https://github.com/VincentLiang1/notetaker-desktop/releases/latest)(免費,Windows 與 Mac 都有;說明看〈[會議助手電腦版使用手冊](https://github.com/VincentLiang1/notetaker-desktop/blob/main/README.zh-TW.md)〉)。它已經包含 Scribe2MD;doc2md 技能用電腦版的「🤖 安裝 Claude Skill…」裝
- **用 Wiki Agent 的**:安裝程式會問要不要下載 Scribe2MD(選裝),之後由 Wiki Agent 自動更新，什麼都不必做

Wiki Agent 發佈頁上的 `scribe2md-core` 是 Wiki Agent 安裝程式自己下載的元件，不是給人直接下載的。

## doc2md 技能

裝好之後，在 Claude Code 給它 PDF、Word、簡報、掃描件或錄音的路徑,Claude 會先用 Scribe2MD 轉成 md 再讀。
