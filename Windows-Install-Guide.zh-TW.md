# wiki-agent Windows 安裝說明

[English](Windows-Install-Guide.md) | **繁體中文** | [简体中文](Windows-Install-Guide.zh-CN.md)

照順序做,大約 30～40 分鐘(大多是等下載)。畫面跟這裡寫的不一樣,就停下來把畫面拍給幫你裝的人看。

## 1. 裝 iCloud for Windows

1. 開始功能表打開 **Microsoft Store**,搜尋 **iCloud**,安裝
2. 打開 iCloud,登入和 iPhone 同一個 Apple 帳號,勾選 **iCloud 雲碟**,按**套用**
3. 打開檔案總管,左邊欄看得到 **iCloud 雲碟**(`C:\Users\<你的名字>\iCloudDrive`)就對了

## 2. 裝 Claude Code 並登入

1. 開始功能表打 `PowerShell`,打開 **Windows PowerShell**
2. 貼上這一行(右鍵就是貼上),按 Enter:
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
3. 跑完後**關掉這個視窗、重開一個新的 PowerShell**,打 `claude` 按 Enter。選登入方式時選 **Claude 帳號(訂閱)**,瀏覽器會打開 Claude 的登入頁,登入你自己的帳號、按**授權**
4. 回到 PowerShell,看到可以打字的提示就是登入好了。打 `/exit` 按 Enter 離開

## 3. 裝 scribe2md(把錄音、文件轉成文字)

1. 瀏覽器打開 <https://github.com/VincentLiang1/scribe2md/releases/latest>,在頁面下方 **Assets** 點 **scribe2md-win.zip** 下載
2. 在「下載」資料夾對 zip 按右鍵 → **全部解壓縮**,解到一個好記的地方(例如 `C:\scribe2md`)
3. 打開解出來的資料夾(裡面還有一層 `scribe2md` 資料夾),照它的 README 雙擊 **Install.bat**,等它跑完。**記住這個資料夾在哪裡**:第 5 步會在 `C:\`、「下載」「桌面」「文件」底下往下兩層自動找,放更深的地方就找不到、要自己貼上路徑

## 4. (可以先跳過)準備 Gmail 的應用程式密碼

摘要信要用 Gmail 寄。不想收信可以跳過,之後再跑一次 `Install.bat` 設定。

1. 瀏覽器打開 <https://myaccount.google.com/security>,確認**兩步驟驗證**是開的
2. 打開 <https://myaccount.google.com/apppasswords>,名稱打 `wiki-agent`,按**建立**
3. 畫面會出現一組 16 個字母的密碼——**先留著這個畫面**,第 5 步會用到

## 5. 安裝 wiki-agent

1. 瀏覽器打開 <https://github.com/VincentLiang1/wiki-agent/releases/latest/download/wiki-agent-win.zip>,下載 **wiki-agent-win.zip**(**不需要 GitHub 帳號**)。瀏覽器說這類檔案可能有害的話,選**保留**
2. 在「下載」資料夾對 zip 按右鍵 →「**全部解壓縮**」,目的地改成 `C:\`,解出來就是 `C:\wiki-agent`。⚠️ 不要解到桌面或「文件」:這兩個地方常被 OneDrive 同步。開了 OneDrive 的資料夾備份之後,檔案總管裡的「文件」「桌面」實際位置是 `C:\Users\<帳號>\OneDrive\文件`、`OneDrive\Desktop` 這類(資料夾名依 Windows 的語言而不同);`C:\Users\<帳號>\Documents` 這時是另一個本機資料夾,看起來一樣、其實不同。要確認某個資料夾在哪裡,打開它、點檔案總管上方的網址列,看完整路徑裡有沒有 `OneDrive`
3. 打開 `C:\wiki-agent`,雙擊 **Install.bat**。跳出藍色的安全性警告(「Windows 已保護您的電腦」之類)的話,按**其他資訊** → **仍要執行**

**一打開先選語言**(在裝任何東西之前;之後的畫面、問題、摘要信、警示、新建的知識庫都只用這個語言,問答不會再問一次):

```
語言 / 语言 / Language:1 繁體中文  2 简体中文  3 English(Enter = 繁體中文)
```

直接按 Enter 用電腦介面的語言(重跑安裝時是上次選的);要換就輸入編號(簡體中文 2、English 3)。

4. 接著列出「開始之前請先做好這三件事」(就是上面第 1～3 步),按任意鍵繼續
5. 沒有 Git、uv 的話它會自己裝(可能跳出「是否允許變更」,按**是**;程式要用 Git 幫你的知識庫留版本紀錄),接著裝好需要的套件
6. 「開啟 Windows 長路徑支援」時會跳出**使用者帳戶控制**,按**是**(只有這一步需要系統管理員;已經開過就不會問)

### 5-1. 回答問題

每一題後面都有「(直接按 Enter = …)」,**大多直接按 Enter 就好**:

| 題目 | 怎麼答 |
| --- | --- |
| 檢查 Claude Code | 自動。看到 `✓ …(已登入)` 才會繼續;說沒登入就回第 2 步 |
| 【知識庫】你已經有 LLM Wiki 了嗎? | 已經有(資料夾裡有 `CLAUDE.md`):Enter 或 `y`。還沒有:`n` |
| 【CLAUDE.md】 | (已經有才會問)程式找到的話直接 Enter;不然在檔案總管的網址列複製知識庫資料夾的路徑、貼上再按 Enter。程式照 `CLAUDE.md` 找出原件資料夾與新檔入口(看不出來才請 Claude 讀一次,十幾秒),列出來讓你確認,對就 Enter(新檔入口用你 `CLAUDE.md` 寫的資料夾,名字不限)。你改的原件資料夾或入口跟 `CLAUDE.md` 寫的不同時會再問一次,預設用 `CLAUDE.md` 的 |
| 【知識庫】 | (還沒有才會問)直接 Enter,問要不要建立再 Enter |
| 【原件資料夾】 | (還沒有才會問)Enter(WIKI 旁邊的 `Raw_Sources`);新的知識庫會問「還沒有,要建立嗎?」再 Enter |
| ⚠ ……在 iCloud 雲碟(或 OneDrive、Dropbox……)裡 | 知識庫或原件資料夾放在同步資料夾裡才會出現。**不要放在 OneDrive、iCloud 雲碟、Dropbox、Google Drive 這類同步資料夾**(含被同步的「文件」「桌面」;開了 OneDrive 備份時它們的實際位置在 `C:\Users\<帳號>\OneDrive\` 底下,跟 `C:\Users\<帳號>\Documents` 是兩個不同的資料夾。知識庫在哪裡,在知識庫資料夾裡點檔案總管的網址列,看完整路徑有沒有 `OneDrive`):檔案可能只留在雲端、別台裝置同時改會冒出衝突副本,知識庫的版本紀錄被同步也會壞。直接 Enter 換一個位置(建議家目錄的 `LLMWiki`);已經有的知識庫要自己搬過去再重跑安裝。堅持要放:打 `2`,看完後果打 `yes`,版本紀錄(git)改放在這台電腦的 wiki-feeder 資料夾、不放在同步資料夾——衝突副本、只在雲端的檔不會因此消失 |
| 【收件匣】 | Enter(iCloud 雲碟裡的 `_WikiBox`);問「還沒有,要建立嗎?」再 Enter |
| 要照講義請 Claude 建好規則檔與目錄索引嗎? | (還沒有 `CLAUDE.md` 才會問)Enter。Claude 會花 1～3 分鐘寫好 `CLAUDE.md` 與目錄 `index.md`,好了會用兩三句話說它建了什麼 |
| 要在 CLAUDE.md 最後補上「版本紀錄由 wiki-feeder 代管」嗎? | Enter(要)。原本的規則不會被改,只在最後加一節 |
| 【知識庫名稱】 | Enter 或打一個你喜歡的 |
| 【轉寫】 | 列出找到的 doc2md,Enter 選第 1 個;它會試轉一個小檔,看到「可以用」就過了。說「找不到 meeting-scribe」時,貼上第 3 步資料夾裡 `.venv\Scripts\doc2md.exe` 的完整路徑 |
| 【摘要信】寄件的 Gmail | 預設是你 Claude 登入的 Gmail;不寄信就輸入 `-` |
| 收件信箱 | Enter(寄給自己) |
| 要(重新)輸入 Gmail 應用程式密碼嗎? | Enter |
| Gmail 的應用程式密碼 | 貼上第 4 步那 16 個字(打字時不會顯示),按 Enter。會寄一封測試信 |
| 讀得到收件匣嗎 | 自動。看到 `iCloud	可讀` 就對了 |
| 裝排程 | 自動 |

之後重跑 `Install.bat`(例如要補設摘要信)會先列出現在的設定、問「沿用這份(不重填)?」:要改就輸入 `n`。

看到 `✓ 安裝完成` 就可以關掉視窗。之後每分鐘會在背景跑一次,**不會跳出任何視窗**。

## 6. 確認真的在動

1. 在 iPhone 打開 **檔案** App → **iCloud 雲碟** → **_WikiBox**,丟一個檔進去
2. 等幾分鐘。在檔案總管上方的網址列貼上 `%USERPROFILE%\LLMWiki\WIKI\Wiki_Pages` 按 Enter(或你選的知識庫的完整路徑;不要從左邊欄的「文件」去找,那裡可能是 OneDrive 裡的另一個資料夾),會多出一頁;原檔被歸到 `Raw_Sources` 底下的主題資料夾
3. 有設摘要信的話,會收到一封「wiki-feeder 攝入摘要」

沒動靜的話看紀錄:檔案總管網址列貼上 `%LOCALAPPDATA%\wiki-feeder\logs`,打開 `feeder.log` 看最後幾行。

## 7. (選做)手機與電腦共用聲紋

在手機 scribe2md App、電腦 scribe2md 命名過的人,另一台也認得。這是 scribe2md 自己的功能,wiki-agent 不用設定;每一台都選**同一個 iCloud 雲碟裡的資料夾**就好。

1. 檔案總管打開 **iCloud 雲碟**,在最上層新增資料夾 `_聲紋同步`。⚠️ **不可以放在 `_WikiBox` 裡面**(那裡的檔會被送進知識庫,聲紋與真名就跟著進去)
2. 對 `_聲紋同步` 按右鍵 → **永遠保留在此裝置上**(沒有這一項就跳過)
3. 電腦打開 scribe2md(桌面上的「**AI 文件.MD 轉換器**」)→ **聲音→MD** → **名單與聲紋**,中間「聲紋資料管理」那欄最底下的「聲紋同步資料夾」按**選擇資料夾…**,選剛剛的 `_聲紋同步`。畫面與選資料夾視窗寫的是「OneDrive 裡的資料夾」,選 iCloud 雲碟裡的也可以;選到 `_WikiBox` 裡面(或包著它)的資料夾會被擋下來
4. 手機打開 scribe2md App → **設定** →「聲紋與名單」的**聲紋同步資料夾** → **iCloud 雲碟** → `_聲紋同步`。設定裡沒有這一項,是 App 還在「只要逐字稿」模式:到**設定 › 模式**切成「送進知識庫」

設好之後,電腦那欄底下的「上次同步」、手機的「立即同步」底下會列出另一台最後一次改動的時間。

設好之後,手機產生會議草稿時也會用到**名詞對照表**:把語音辨識聽錯的人名、公司、術語換成正確寫法。對照表不用另外維護,是你平常指正 Claude 時一點一點累積的,wiki-agent 每一輪攝入完自動放進 `_聲紋同步`,手機同步時一起帶過去(手機的**設定 › 離線 AI 會議草稿識別 › 名詞對照表**看得到)。`_聲紋同步` 要照第 1 步建在 iCloud 雲碟最上層。

**看到寫錯怎麼辦**:不用自己改檔。在會議頁看到人名、公司、術語寫錯,開 Claude 桌面版(打開知識庫資料夾)直接跟它說,例如:

- 「10/21 業務週會那頁的『王小明』應該是『王筱明』」
- 「昨天那場會議一直出現的『艾克米』是客戶 Acme」
- 「『林大』是林達,只有業務週會會聽錯成這樣」
- 「『張經理』那條換錯了,拿掉」

Claude 會改正頁面,同時把這條記進知識庫的名詞校正表(`memory/name-corrections.md`),之後的會議草稿與攝入就照正確寫法。兩個字的中文詞(例如「林大」)要講是哪個會議系列才會換,免得「基金」「政策」這類常用詞每場都被改掉。(安裝時有答應在 CLAUDE.md 補上「名詞校正表」那一節,Claude 才知道要記;當時沒補的話重跑一次安裝)

⚠️ wiki-agent 自動轉寫錄音時不會套用聲紋,逐字稿裡是「講者1」「講者2」。要名字的話,先在手機 App 或 scribe2md 裡轉好、命名,再把逐字稿送進 `_WikiBox`。

## 更新

**平常不必自己動手**:程式一天查一次新版,最新版發佈滿 1 天就自己換上——等正在處理的那一輪做完才換,換完先試讀收件匣與知識庫,讀不到就自己退回原本的版本。每次自動更新另外寄一封信(有設摘要信的話):

- 「wiki-feeder 已自動更新到 …」:成功,信裡寫這次改了什麼
- 「wiki-feeder 有新版 …:這一版要你動手更新」:這一版有要你自己做的步驟,照下面雙擊 Update.bat
- 「⚠️ 需要處理｜wiki-feeder 自動更新失敗,已退回 …」:已經退回原本的版本、照常在跑,不急著處理

當日摘要的警示出現「自動更新好幾天沒有查成功」:開機的這幾天都沒能查新版(關機、沒網路的日子不算),可能是自動更新本身出了問題,照下面雙擊 Update.bat 手動更新一次。

紀錄在 `%LOCALAPPDATA%\wiki-feeder\logs\update.log`。**不想自動更新**:用記事本打開 `%LOCALAPPDATA%\wiki-feeder\config.toml`,在 `[general]` 那段加一行 `auto_update = false`,存檔。

要馬上更新(或信裡請你動手時):雙擊 `C:\wiki-agent` 裡的 **Update.bat**。它會到 GitHub 下載新版、換掉程式資料夾裡的檔;如果剛好在處理檔案,它會等那一輪做完才更新,不會中途砍掉。設定、紀錄、知識庫都不動。

(以前照舊版說明、只下載 Install.bat 一個檔裝在 `C:\wiki-feeder` 的,一樣雙擊那裡的 Update.bat,它會用 Git 更新。以下的 `C:\wiki-agent` 都換成 `C:\wiki-feeder`。)

## 移除

- **只停掉自動處理**:雙擊 `C:\wiki-agent` 裡的 **Remove-Schedule.bat**。設定、紀錄、知識庫都不動;要再開,重跑 **Install.bat**
- **整個拿掉**:先做上面那步,再刪掉 `C:\wiki-agent` 與 `%LOCALAPPDATA%\wiki-feeder`。**你的知識庫(`WIKI`、`Raw_Sources`)不在這兩個地方,不會被刪**。例外:安裝時選了「照樣用同步資料夾」的,知識庫的版本紀錄在 `wiki-feeder` 資料夾的 `wiki-git` 裡,丟掉就沒了,要留的話先搬出來

## 出狀況時

- **信的主旨開頭是「⚠️ 需要處理」**:打開 PowerShell,打 `cd C:\wiki-agent; claude`,把那封信整封貼給 Claude,請它照 wiki-agent 的規則處理
- **「Claude Code 沒登入或登入過期」**:PowerShell 打 `claude` 重新登入,下一輪就會自己接著做
- **不要自己在知識庫裡執行 git**(包括請 Claude 幫你 commit):程式只接受它自己驗證過的版本,多一筆就會停下來等人
