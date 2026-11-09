# 會議助手全套服務架構

[English](How-Notetaker-Fits-Together.md) | **繁體中文** | [简体中文](How-Notetaker-Fits-Together.zh-CN.md)

**從手機上的會議助手 App 開始,加上會議助手電腦版,再由 Wiki Agent 串起來,最後做到 LLM Wiki 自動化。分三層,要多少裝多少。**

```mermaid
flowchart TD
    App["會議助手 App<br/>iPhone · Android"]
    Desktop["會議助手電腦版<br/>Windows · Mac<br/>(內含同一顆 Scribe2MD 核心)"]
    Box["_WikiBox<br/>iCloud 雲碟的收件資料夾"]
    Agent["Wiki Agent + Scribe2MD<br/>轉文字、整理成筆記"]
    Wiki["LLM Wiki<br/>你電腦上的知識庫"]

    App <-->|"聲紋、名單同步"| Desktop
    App -->|"按「送出」"| Box
    Desktop -.->|"手動把 md 丟進去"| Box
    Box -->|"電腦每分鐘收件"| Agent
    Agent -->|"寫頁、互相連結"| Wiki
```

## 第 1 層:只要手機

- 錄音、分出講者、產生逐字稿
- 不上網 AI 整理成會議紀錄草稿
- 分享給同事,或交給 ChatGPT、Claude

## 第 2 層:加上電腦版

- 在電腦上錄線上會議、轉現成錄音
- Word、PDF、簡報轉成 AI 好讀的 md
- 聲紋與名單跟手機同步

免費下載,Windows 與 Mac 都有:看〈[會議助手電腦版使用手冊](https://github.com/VincentLiang1/notetaker-desktop/blob/main/README.zh-TW.md)〉(開頭就是下載連結)。

## 第 3 層:自動進知識庫

- 手機按「送出」,電腦上的 Wiki Agent 收件
- 錄音轉文字,整理進你的 LLM Wiki
- 跟舊資料連起來,越用越完整

要一台常開的電腦與 Claude 付費帳號(Pro 以上)。目前收件資料夾 `_WikiBox` 在 iCloud 雲碟裡:手機是 iPhone;電腦是 Windows 的話要裝 iCloud for Windows。Wiki Agent 每分鐘看一次收件資料夾。

- 沒聽過 LLM Wiki?看〈[什麼是 LLM Wiki](What-is-LLM-Wiki.zh-TW.md)〉
- Wiki Agent 介紹與安裝:[README](README.zh-TW.md)、[Mac 安裝說明](Mac-Install-Guide.zh-TW.md)、[Windows 安裝說明](Windows-Install-Guide.zh-TW.md)

## Scribe2MD 是什麼

- 電腦版裡負責轉文字的核心
- 只要轉檔、或在 Claude Code 用 doc2md 技能,可以單獨裝
- 裝了電腦版就不用另裝

Wiki Agent 的安裝程式會問要不要下載 Scribe2MD(約 1 GB,選裝)。沒裝時文件與照片由 Claude 直接讀,錄音與影片要裝了才處理。
