# Scribe2MD

[English](Scribe2MD.md) | [繁體中文](Scribe2MD.zh-TW.md) | **简体中文**

**把文档、扫描件、录音转成 Markdown 的转换核心。在自己的电脑上离线转换，不上传任何内容。**

## 能转什么

- 文档:PDF、Word、PowerPoint、Excel(含旧版 .doc/.ppt/.xls)、Outlook 邮件(.msg/.eml)、.rtf、.mht
- 扫描件与照片：做文字识别(OCR)
- 录音与视频(.m4a、.mp3、.wav、.mp4、.mov 等):转成分说话人的逐字稿

转成 md 之后，丢给 ChatGPT、Claude 或放进知识库都比原文件好用:PDF 省下大量 token,Office 文件保住表格与内嵌图。

## 怎么取得

Scribe2MD 不用自己装:

- **要自己转文件、或在 Claude Code 用 doc2md 技能**:装[会议助手电脑版](https://github.com/VincentLiang1/notetaker-desktop/releases/latest)(免费,Windows 与 Mac 都有;说明看〈[会议助手电脑版使用手册](https://github.com/VincentLiang1/notetaker-desktop/blob/main/README.zh-CN.md)〉)。它已经包含 Scribe2MD;doc2md 技能用电脑版的「🤖 安装 Claude Skill…」装
- **用 Wiki Agent 的**:安装程序会问要不要下载 Scribe2MD(选装),之后由 Wiki Agent 自动更新，什么都不必做

Wiki Agent 发布页上的 `scribe2md-core` 是 Wiki Agent 安装程序自己下载的组件，不是给人直接下载的。

## doc2md 技能

装好之后，在 Claude Code 给它 PDF、Word、演示文稿、扫描件或录音的路径,Claude 会先用 Scribe2MD 转成 md 再读。
