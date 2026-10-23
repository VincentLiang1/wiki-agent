# wiki-agent

[繁體中文](README.zh-Hant.md) | **简体中文** | [English](README.md)

**iPhone 按下记录,知识库自己长出一页。**

wiki-agent 是一支在你电脑上常驻的小程序,替你照 Andrej Karpathy 的「LLM Wiki」做法维护个人知识库:

1. 你在 iPhone 上把录音、白板照片、扫描件、Office 文件丢进 iCloud 云盘的 `_WikiBox` 文件夹
2. 电脑上的 wiki-agent 每分钟看一次:把文件收进原件文件夹 `Raw_Sources`,录音与文档先转成文字(用 [scribe2md](https://github.com/VincentLiang1/scribe2md))
3. 用你自己的 Claude Code,照你知识库里的 `CLAUDE.md` 规则把它编进 `WIKI/Wiki_Pages/`:新建页面或补进既有的页、更新目录 `index.md`
4. 程序检查过才记成一个版本(git,由程序代管,你不用学)。每天寄一封摘要信告诉你处理了什么

你只做两件事:**丢文件**、**看摘要**。有错就打开 Claude Code 说是哪一笔要退回。

> **文件绝不会丢**:搬文件一律先拷贝、比对内容一致才删来源;任何一步失败就留着原文件,下一轮再试。

## 需要什么

| | Mac | Windows |
| --- | --- | --- |
| 电脑 | Apple 芯片的 Mac(版本需求照 scribe2md 的说明) | Windows 10／11 |
| 手机 | iPhone(用 iCloud 云盘传文件) | iPhone + 电脑装 iCloud for Windows |
| Claude | 自己的 Claude 订阅(Pro 或 Max),装好 Claude Code 并登录 | 同左 |
| 转写 | [scribe2md](https://github.com/VincentLiang1/scribe2md/releases/latest) 的 Mac 版 | scribe2md 的 Windows 版 |
| 摘要信(可不设) | Gmail + 应用专用密码 | 同左 |

知识库照〈LLM Wiki 新手教学讲义-桌面版〉的摆法:一个文件夹底下并排 `WIKI/`(里面有 `CLAUDE.md`)与 `Raw_Sources/`。**还没有也没关系**:安装时直接按 Enter,程序会帮你建好文件夹,并请 Claude 照讲义写好 `CLAUDE.md`;已经有的知识库照原本的用,不会覆盖。

## 安装

- **Mac**:看 [Mac-Install-Guide.zh-Hans.md](Mac-Install-Guide.zh-Hans.md)。下载 [wiki-agent-mac.zip](https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-mac.zip)、解开,把 wiki-agent 拖进「应用程序」再双击(已签章公证)。备用:打开「终端」粘贴一行:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/VincentLiang1/wiki-agent/main/install.sh | bash
  ```
- **Windows**:看 [Windows-Install-Guide.zh-Hans.md](Windows-Install-Guide.zh-Hans.md)。下载 `Install.bat`,双击

安装会一题一题问(每题都有默认答案,大多直接按 Enter),最后装好每分钟自动跑的定时任务。第一题选语言:繁体中文、简体中文或 English,之后的问题、摘要信、警示与新建的知识库都用那个语言。

## 要知道的事

- **你的数据会送到 Anthropic 的 API**:摄入时 Claude 会读源文件(含照片)。跟你平常用 Claude 一样,用的是你自己的账号与额度;一笔摄入大约 US$0.3～1
- **Claude 的权限给到最小**:只能读文件、改知识库里的页;不能删文件、不能搬原件、不能自己 commit 或推送。改完由程序检查——原件少了、页面被大量删减、留下奇怪的文件,就整个停下来寄信等你看
- **版本记录由程序代管**:不要自己在知识库里运行 git(多一笔程序没验证过的 commit,自动摄入就会停住)。手动改的页直接存盘就好,下次摄入前程序会先存成一笔「手动修改快照」
- 程序的设置与记录在 `~/Library/Application Support/wiki-feeder/`(Mac)或 `%LOCALAPPDATA%\wiki-feeder\`(Windows),看 log 就看里面的 `logs/feeder.log`

## 著作权

Copyright © 2026 Vincent Liang. **All rights reserved.**

这份代码公开是为了让朋友方便安装,**不是开源软件**:没有授予任何拷贝、修改、散布或商业使用的权利。个人自用请直接照安装说明装;其他用途请先联系作者。
