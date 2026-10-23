# wiki-agent Windows 安装说明

[繁體中文](Windows-Install-Guide.zh-Hant.md) | **简体中文** | [English](Windows-Install-Guide.md)

照顺序做,大约 30～40 分钟(大多是等下载)。画面跟这里写的不一样,就停下来把画面拍给帮你装的人看。

## 1. 装 iCloud for Windows

1. 开始功能表打开 **Microsoft Store**,搜索 **iCloud**,安装
2. 打开 iCloud,登录和 iPhone 同一个 Apple 账号,勾选 **iCloud 云盘**,按**套用**
3. 打开文件总管,左边栏看得到 **iCloud 云盘**(`C:\Users\<你的名字>\iCloudDrive`)就对了

## 2. 装 Claude Code 并登录

1. 开始功能表打 `PowerShell`,打开 **Windows PowerShell**
2. 粘贴这一行(右键就是粘贴),按 Enter:
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
3. 跑完后**关掉这个窗口、重开一个新的 PowerShell**,打 `claude` 按 Enter。选登录方式时选 **Claude 账号(订阅)**,浏览器会打开 Claude 的登录页,登录你自己的账号、按**授权**
4. 回到 PowerShell,看到可以打字的提示就是登录好了。打 `/exit` 按 Enter 离开

## 3. 装 scribe2md(把录音、文档转成文字)

1. 浏览器打开 <https://github.com/VincentLiang1/scribe2md/releases/latest>,在页面下方 **Assets** 点 **scribe2md-win.zip** 下载
2. 在「下载」文件夹对 zip 按右键 → **全部解压缩**,解到一个好记的地方(例如 `C:\scribe2md`)
3. 打开解出来的文件夹(里面还有一层 `scribe2md` 文件夹),照它的 README 双击 **Install.bat**,等它跑完。**记住这个文件夹在哪里**:第 5 步会在 `C:\`、「下载」「桌面」「文档」底下往下两层自动找,放更深的地方就找不到、要自己粘贴路径

## 4. (可以先跳过)准备 Gmail 的应用专用密码

摘要信要用 Gmail 寄。不想收信可以跳过,之后再跑一次 `Install.bat` 设置。

1. 浏览器打开 <https://myaccount.google.com/security>,确认**两步骤验证**是开的
2. 打开 <https://myaccount.google.com/apppasswords>,名称打 `wiki-agent`,按**创建**
3. 画面会出现一组 16 个字母的密码——**先留着这个画面**,第 5 步会用到

## 5. 安装 wiki-agent

1. 浏览器打开 <https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-win.zip>,下载 **wiki-agent-win.zip**(**不需要 GitHub 账号**)。浏览器说这类文件可能有害的话,选**保留**
2. 在「下载」文件夹对 zip 按右键 →「**全部解压缩**」,目的地改成 `C:\`,解出来就是 `C:\wiki-agent`。⚠️ 不要解到桌面或「文档」:这两个地方常被 OneDrive 同步
3. 打开 `C:\wiki-agent`,双击 **Install.bat**。跳出蓝色的安全性警告(「Windows 已保护您的电脑」之类)的话,按**其他信息** → **仍要运行**
4. 黑色窗口先列出「开始之前请先做好这三件事」(就是上面第 1～3 步),按任意键继续
5. 没有 Git、uv 的话它会自己装(可能跳出「是否允许变更」,按**是**;程序要用 Git 帮你的知识库留版本记录),接着装好需要的套件
6. 「打开 Windows 长路径支持」时会跳出**用户帐户控制**,按**是**(只有这一步需要系统管理员;已经开过就不会问)

### 5-1. 回答问题

第一题选语言(之后的问题、摘要信、警示、新建的知识库都用这个语言):

```
語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English(Enter = 简体中文)
```

直接按 Enter 用电脑界面的语言;要换就输入编号(简体中文 2、English 3)。接下来每一题后面都有「(直接按 Enter = …)」,**大多直接按 Enter 就好**:

| 题目 | 怎么答 |
| --- | --- |
| 检查 Claude Code | 自动。看到 `✓ …(已登录)` 才会继续;说没登录就回第 2 步 |
| 【收件箱】 | Enter(iCloud 云盘里的 `_WikiBox`);问「还没有,要创建吗?」再 Enter |
| 【知识库】 | 已经有照讲义建的 WIKI 文件夹:在文件总管的网址列拷贝它的路径、粘贴再按 Enter。还没有:直接 Enter,问要不要创建再 Enter |
| 【原件文件夹】 | Enter(WIKI 旁边的 `Raw_Sources`);新的知识库会问「还没有,要创建吗?」再 Enter |
| 要照讲义请 Claude 建好规则文件与目录索引吗? | (还没有 `CLAUDE.md` 才会问)Enter。Claude 会花 1～3 分钟写好 `CLAUDE.md` 与目录 `index.md`,好了会用两三句话说它建了什么 |
| 要在 CLAUDE.md 最后补上「版本记录由 wiki-feeder 代管」吗? | Enter(要)。原本的规则不会被改,只在最后加一节 |
| 【知识库名称】 | Enter 或打一个你喜欢的 |
| 【转写】 | 列出找到的 doc2md,Enter 选第 1 个;它会试转一个小文件,看到「可以用」就过了。说「找不到 meeting-scribe」时,粘贴第 3 步文件夹里 `.venv\Scripts\doc2md.exe` 的完整路径 |
| 【摘要信】寄件的 Gmail | 默认是你 Claude 登录的 Gmail;不寄信就输入 `-` |
| 收件信箱 | Enter(寄给自己) |
| 要(重新)输入 Gmail 应用专用密码吗? | Enter |
| Gmail 的应用专用密码 | 粘贴第 4 步那 16 个字(打字时不会显示),按 Enter。会寄一封测试信 |
| 读得到收件箱吗 | 自动。看到 `iCloud	可读` 就对了 |
| 装定时任务 | 自动 |

之后重跑 `Install.bat`(例如要补设摘要信)会先列出现在的设置、问「沿用这份(不重填)?」:要改就输入 `n`。

看到 `✓ 安装完成` 就可以关掉窗口。之后每分钟会在背景跑一次,**不会跳出任何窗口**。

## 6. 确认真的在动

1. 在 iPhone 打开 **文件** App → **iCloud 云盘** → **_WikiBox**,丢一个文件进去
2. 等几分钟。文件总管打开你的知识库 `WIKI\Wiki_Pages`,会多出一页;原文件被归到 `Raw_Sources` 底下的主题文件夹
3. 有设摘要信的话,会收到一封「wiki-feeder 摄入摘要」

没动静的话看记录:文件总管网址列粘贴 `%LOCALAPPDATA%\wiki-feeder\logs`,打开 `feeder.log` 看最后几行。

## 7. (选做)手机与电脑共用声纹

在手机 scribe2md App、电脑 scribe2md 命名过的人,另一台也认得。这是 scribe2md 自己的功能,wiki-agent 不用设置;每一台都选**同一个 iCloud 云盘里的文件夹**就好。

1. 文件总管打开 **iCloud 云盘**,在最上层添加文件夹 `_聲紋同步`。⚠️ **不可以放在 `_WikiBox` 里面**(那里的文件会被送进知识库,声纹与真名就跟着进去)
2. 对 `_聲紋同步` 按右键 → **永远保留在此设备上**(没有这一项就跳过)
3. 电脑打开 scribe2md(桌面上的「**AI 文件.MD 轉換器**」)→ **声音→MD** → **名单与声纹**,中间「声纹数据管理」那栏最底下的「声纹同步文件夹」按**选择文件夹…**,选刚刚的 `_聲紋同步`。画面与选文件夹窗口写的是「OneDrive 里的文件夹」,选 iCloud 云盘里的也可以;选到 `_WikiBox` 里面(或包着它)的文件夹会被挡下来
4. 手机打开 scribe2md App → **设置** →「声纹与名单」的**声纹同步文件夹** → **iCloud 云盘** → `_聲紋同步`。设置里没有这一项,是 App 还在「只要逐字稿」模式:到**设置 › 模式**切成「送进知识库」(要开通密码,问帮你装的人)

设好之后,电脑那栏底下的「上次同步」、手机的「立即同步」底下会列出另一台最后一次改动的时间。

⚠️ wiki-agent 自动转写录音时不会套用声纹,逐字稿里是「讲者1」「讲者2」。要名字的话,先在手机 App 或 scribe2md 里转好、命名,再把逐字稿送进 `_WikiBox`。

## 更新

**平常不必自己动手**:程序一天查一次新版,最新版发布满 1 天就自己换上——等正在处理的那一轮做完才换,换完先试读收件箱与知识库,读不到就自己退回原本的版本。每次自动更新另外寄一封信(有设摘要信的话):

- 「wiki-feeder 已自动更新到 …」:成功,信里写这次改了什么
- 「wiki-feeder 有新版 …:这一版要你动手更新」:这一版有要你自己做的步骤,照下面双击 Update.bat
- 「⚠️ 需要处理｜wiki-feeder 自动更新失败,已退回 …」:已经退回原本的版本、照常在跑,不急着处理

当日摘要的警示出现「自动更新好几天没有查成功」:开机的这几天都没能查新版(关机、没网络的日子不算),可能是自动更新本身出了问题,照下面双击 Update.bat 手动更新一次。

记录在 `%LOCALAPPDATA%\wiki-feeder\logs\update.log`。**不想自动更新**:用记事本打开 `%LOCALAPPDATA%\wiki-feeder\config.toml`,在 `[general]` 那段加一行 `auto_update = false`,存盘。

要马上更新(或信里请你动手时):双击 `C:\wiki-agent` 里的 **Update.bat**。它会到 GitHub 下载新版、换掉程序文件夹里的文件;如果刚好在处理文件,它会等那一轮做完才更新,不会中途砍掉。设置、记录、知识库都不动。

(以前照旧版说明、只下载 Install.bat 一个文件装在 `C:\wiki-feeder` 的,一样双击那里的 Update.bat,它会用 Git 更新。以下的 `C:\wiki-agent` 都换成 `C:\wiki-feeder`。)

## 移除

- **只停掉自动处理**:双击 `C:\wiki-agent` 里的 **Remove-Schedule.bat**。设置、记录、知识库都不动;要再开,重跑 **Install.bat**
- **整个拿掉**:先做上面那步,再删掉 `C:\wiki-agent` 与 `%LOCALAPPDATA%\wiki-feeder`。**你的知识库(`WIKI`、`Raw_Sources`)不在这两个地方,不会被删**

## 出状况时

- **信的主旨开头是「⚠️ 需要处理」**:打开 PowerShell,打 `cd C:\wiki-agent; claude`,把那封信整封贴给 Claude,请它照 wiki-agent 的规则处理
- **「Claude Code 没登录或登录过期」**:PowerShell 打 `claude` 重新登录,下一轮就会自己接着做
- **不要自己在知识库里运行 git**(包括请 Claude 帮你 commit):程序只接受它自己验证过的版本,多一笔就会停下来等人
