"""所有路徑與參數集中在這裡。

程式庫本身不讀 `~` 也不讀環境變數:CLI 用 `Config.default()` 組出真實路徑,
測試用 `tmp_path` 組出假路徑——這是「測試絕不碰真實收件匣」的第一道防線。
"""
from __future__ import annotations

import os
import shutil
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

CONFIG_FILE = "config.toml"
INTAKE_DIR = "_收件區"     # 單庫設定的收件區:原件樹底下、不算原件(raw_skip_dirs)
# 攝入時 claude 執行 wiki-feeder 子命令的開頭(兩種設定共用一份,突變與測試才守得到兩邊)。用「正在執行的這一份」
# 程式的 python:常駐跑的是發佈副本,不可指回開發目錄。-P:`-m` 預設把 cwd(攝入時是知識庫)放進 sys.path 最前面,
# claude 先寫一個 wiki_feeder.py 再執行這行,就等於能跑任意程式
def tools_cmd(python: str, windows: bool) -> tuple[str, ...]:
    """Windows:排程跑的是 pythonw.exe(沒有主控台,claude 讀不到輸出)、-X utf8 是旗標不會傳下去
    (沒有 UTF-8 模式 CLI 會拒絕執行)——換成同一個資料夾的 python.exe 並明帶 -X utf8。"""
    if not windows:
        return (python, "-P", "-m", "wiki_feeder")
    p = PureWindowsPath(python)   # 在 Mac 上測時 Path 不認 \ 是分隔字元
    if p.name.lower() == "pythonw.exe":
        python = str(p.with_name("python.exe"))
    return (python, "-P", "-X", "utf8", "-m", "wiki_feeder")


INGEST_TOOLS_CMD = tools_cmd(sys.executable, sys.platform == "win32")
PLATFORM = sys.platform   # 測試換成 win32(不可直接改 sys.platform:shutil 等標準庫會跟著走 Windows 的路)


class ConfigError(Exception):
    pass


def find_ffmpeg(doc2md: Path) -> str:
    """meeting-scribe 的 static-ffmpeg 把 ffmpeg 下載到它 venv 的 site-packages 底下;找不到回空字串
    (量不到長段空白只會在摘要記一句警告,不擋轉寫)。"""
    venv = doc2md.parent.parent
    for pattern in ("Lib/site-packages/static_ffmpeg/bin/**/ffmpeg.exe", "lib/python*/site-packages/static_ffmpeg/bin/**/ffmpeg"):
        found = sorted(venv.glob(pattern))
        if found:
            return str(found[0])
    return ""


def state_dir_for(platform: str, home: Path, env: Mapping[str, str]) -> Path:
    """執行狀態目錄(處理紀錄、log、設定檔):Mac 在 ~/Library/Application Support,
    Windows 在 %LOCALAPPDATA%(≈ Mac 的 ~/Library;不放 %APPDATA%:那是漫遊設定檔,處理紀錄不該跟著帳號漫遊)。"""
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "wiki-feeder"
    return home / "Library" / "Application Support" / "wiki-feeder"


@dataclass(frozen=True)
class FuturesConfig:
    repo_dir: Path                      # 本機稀疏副本
    remote: str                         # git remote URL
    branch: str = "main"
    process_dir: str = "PROCESS"
    keep: tuple[str, ...] = ("_.txt",)  # PROCESS/ 根目錄下永不取走的佔位檔
    partial_clone: bool = True          # --filter=blob:none;測試的假 remote 可關掉
    push_retries: int = 3
    check_interval: float = 300         # 遠端檢查最短間隔:launchd 每分鐘一輪,公司端只在鎖定／登入時才推
    git_user: str = "wiki-feeder"
    git_email: str = "wiki-feeder@localhost"
    net_timeout: float = 300            # 每個 git 指令的上限;2026-10-05 ls-remote 經 ssh 卡了 44 分鐘(見 proc.py)


@dataclass(frozen=True)
class RepoConfig:
    """一個知識庫:git repo 與它的原件樹。"""
    key: str                            # "company" / "personal"(分流結果的代號)
    label: str                          # 「公事庫」/「個人庫」(摘要上顯示)
    repo_dir: Path
    raw_root: Path                      # FRaw_Sources / Raw_Sources
    github: str                         # owner/name,摘要裡的 commit 連結用;空字串 = 沒有 GitHub(不附連結)
    branch: str = "master"
    # 程式代管 git(朋友的 Windows 版,使用者 2026-10-19):庫本來不是 git 庫,程式 git init、遠端是執行狀態目錄裡
    # 的本機 bare repo;攝入的 claude 只改檔不 commit,程式驗證後代為 commit,人手動改的攝入前另存快照
    managed: bool = False


@dataclass(frozen=True)
class Config:
    pending_dir: Path                   # Raw_Sources/_待處理
    state_dir: Path                     # 處理紀錄、鎖檔、log、警示
    icloud_inbox: Path | None
    onedrive_inbox: Path | None
    futures: FuturesConfig | None
    stable_wait: float = 5.0            # 檔案大小連續兩次不變的間隔秒數
    unavailable_alert_after: int = 3    # 收件匣連續幾輪讀不到才發警示(偶發一次多半是雲端同步中,不是權限壞了)
    trigger_icloud_download: bool = True
    raw_roots: tuple[Path, ...] = ()    # 既有原件的根目錄(重複判定用),排除下面兩個子目錄
    raw_skip_dirs: tuple[str, ...] = ("_待處理", "_捨棄候選")
    # --- M2 轉寫與 OCR ---
    doc2md_cmd: tuple[str, ...] = ()    # 呼叫 doc2md 的命令(不含檔案與參數);測試換成假腳本
    doc2md_timeout: float = 6 * 3600    # 長錄音可能要數十分鐘
    ffmpeg: str = ""                    # 量長段空白解音檔用;Mac 用系統的 afconvert、不用它(osplat.decode_cmd)
    convert_max_attempts: int = 3       # 轉檔失敗重試幾輪後改發警示
    silence_window: float = 1.0         # 長段空白:每幾秒算一次音量
    silence_margin_db: float = 15.0     # 「安靜」與「有聲」兩群至少要差幾 dB 才算有安靜段(離手機遠的小聲講者約差 10 dB)
    silence_min_gap: float = 180.0      # 連續幾秒沒聲音才列進當日摘要
    # --- M3 攝入、當日摘要 ---
    # 不分流:一律攝入 target_repo(使用者 2026-10-04 定案:先全進公事庫,事後要搬再下指令)
    repos: tuple[RepoConfig, ...] = ()
    target_repo: str = "company"
    # 攝入照公事庫規則回填的個人庫(使用者 2026-10-07 放行);寫進副本、程式驗證後才 commit(ingest.backfill)
    backfill_repo: str = "personal"
    # 回填進個人庫的內容與 commit message 多出這些字就整筆不收(單向規則,§5.12);字串只在使用者自己的設定裡
    backfill_forbidden: tuple[str, ...] = ()
    claude_cmd: tuple[str, ...] = ()    # 測試換成假腳本
    # 攝入時 claude 能執行的非 git 指令前綴;只讀子命令一個一個放行(ingest.INGEST_TOOLS)
    ingest_tools_cmd: tuple[str, ...] = ()
    feeder_github: str = ""             # wiki-feeder 自己的 GitHub repo(owner/name):修理信的 commit 連結
    # 當日摘要寄 Email(使用者 2026-10-06 定案不開 Issue,本機另留 summaries/);密碼在鑰匙圈,見 notify.py
    mail_from: str = ""
    mail_to: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_keychain_service: str = "wiki-feeder-smtp"
    ingest_budget_usd: float = 10.0     # 探測:一則短筆記約 1 美元、22 輪;2026-10-07 使用者要求從 5 調大
    ingest_timeout: float = 3600
    ingest_max_attempts: int = 3
    push_retries: int = 3
    # --- 看門狗與自動修理(使用者 2026-10-05 定案:每 3 分鐘查、卡住就自己修、修完寄信;一天最多 3 次) ---
    repair_repo: Path | None = None     # 開發目錄:修理在這裡改程式、測試、推送,再由看門狗發佈
    repair_max_per_day: int = 3
    repair_timeout: float = 3600
    repair_budget_usd: float = 10.0
    collect_hung_after: float = 1800    # 一個收件匣做超過這麼久算卡住(第一次 clone FUTURES 上限 1800 秒)
    # CPU／記憶體被佔著不放:連續幾次檢查(每 3 分鐘)都超過門檻才算,只查原因、寄信
    resource_cpu_pct: float = 70        # ps 的 %CPU(一顆核心 = 100);使用者 2026-10-05 定 70%
    resource_cpu_ticks: int = 5         # 約 15 分鐘
    resource_rss_frac: float = 0.25     # 單一行程佔總記憶體的比例
    resource_mem_free_pct: float = 10   # 整台可用記憶體低於這個百分比
    resource_mem_ticks: int = 3         # 約 9 分鐘
    # iCloud 同步探針(使用者 2026-10-09 要求):沒人丟檔時「最後同步時間」本來就不動,分不出壞了還是沒事做,
    # 所以看門狗定時寫一個小檔進 iCloud 雲碟,看它有沒有傳上去;None = 不查
    icloud_probe_dir: Path | None = None
    # 最慢約 25 分鐘發現(間隔 + 時限;使用者 2026-10-09 選的,原本 60＋30 分鐘嫌慢)。實測 4 秒～1 分鐘就傳上去,
    # 時限不要再低於 10 分鐘:iCloud 忙著下載長錄音時探針會排在後面,誤判一次就用掉 7 天內唯一一次自動重啟
    icloud_probe_every: float = 900     # 隔多久寫一次探針(秒,不含系統睡眠)
    icloud_sync_timeout: float = 600    # 寫了之後多久還沒傳上去算 iCloud 卡住
    icloud_restart_checks: int = 12     # 重啟 bird 之後最多查幾次(每 15 秒一次)
    # 聲紋同步橋樑(scribe2md-ios 的 voiceprint_bridge.py)每輪寫的狀態檔;None = 不查。
    # 使用者 2026-10-14:讀不到雲端檔先自己修、修完寄信講經過,修不好才寄信找人
    vp_bridge_status: Path | None = None
    vp_bridge_label: str = "tw.vli.scribe2md.voiceprint-bridge"
    vp_bridge_stuck_after: float = 1800  # 同一個檔連續讀不到多久才出手(橋樑每 2 分鐘一輪)
    vp_bridge_fresh: float = 600         # 狀態檔要在這段時間內寫過才算數(剛睡醒、橋樑還沒跑的舊狀態不算)
    vp_bridge_checks: int = 8            # 出手之後最多查幾次(每 15 秒一次)
    md_cache_keep_days: float = 7       # 攝入完成(或捨棄、移走)幾天後刪掉轉寫快取;原件不動,要重轉再轉

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "ledger.sqlite3"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "collect.lock"

    @property
    def alerts_path(self) -> Path:
        return self.state_dir / "alerts.jsonl"

    @property
    def log_path(self) -> Path:
        return self.state_dir / "logs" / "feeder.log"

    @property
    def summaries_dir(self) -> Path:
        return self.state_dir / "summaries"     # 當日摘要留底:一天一個 YYYY-MM-DD.md

    @property
    def convert_lock_path(self) -> Path:
        # 與 collect 分開:長錄音轉寫期間收件照常進行
        return self.state_dir / "convert.lock"

    @property
    def ingest_lock_path(self) -> Path:
        return self.state_dir / "ingest.lock"

    @property
    def deploy_lock_path(self) -> Path:
        # 每次執行全程握共享鎖、deploy 握獨佔鎖;scripts/launchd.py 的 LOCKS 要列同一個檔名
        return self.state_dir / "deploy.lock"

    @property
    def ingest_stop_path(self) -> Path:
        # STOP 之後留著,直到人檢查完執行 `wiki-feeder resume`;在之前攝入與補推都不做
        return self.state_dir / "ingest.stop"

    @property
    def verified_heads_path(self) -> Path:
        # 每個庫最後一個驗證通過的 commit:補推只推到這裡,超出的是當掉那輪沒驗證過的 commit
        return self.state_dir / "verified_heads.json"

    @property
    def local_origin(self) -> Path:
        # 程式代管 git 的遠端:本機 bare repo,推送、補推、「已驗證」照雙庫那套走,另外多一份本機備份
        return self.state_dir / "wiki-origin.git"

    @property
    def has_backfill(self) -> bool:
        return any(r.key == self.backfill_repo for r in self.repos)

    @property
    def discard_dir(self) -> Path:
        # 捨棄候選放在原件樹裡(要備份的地方),不放 state dir;人確認後才真的刪
        return self.repo(self.target_repo).raw_root / "_捨棄候選"

    @property
    def sidecar_archive(self) -> Path:
        return self.state_dir / "sidecars"

    def repo(self, key: str) -> RepoConfig:
        return next(r for r in self.repos if r.key == key)

    @property
    def repair_lock_path(self) -> Path:
        # 看門狗自己的鎖:不握 deploy.lock(修理完要發佈,握著共享鎖等於自己擋自己)
        return self.state_dir / "repair.lock"

    @property
    def repair_log_path(self) -> Path:
        # 每次修理一行:次數上限、同一問題第二次改找人,都從這裡算
        return self.state_dir / "repair.jsonl"

    @property
    def resource_state_path(self) -> Path:
        return self.state_dir / "resource_watch.json"

    @property
    def icloud_probe_state_path(self) -> Path:
        return self.state_dir / "icloud_probe.json"

    @property
    def tool_gaps_path(self) -> Path:
        # 攝入被權限擋下的指令、claude 回報做不到的檢查,一筆一行;摘要信一天提醒一次(toolgaps.py)
        return self.state_dir / "tool_gaps.jsonl"

    @property
    def tool_gaps_ignore_path(self) -> Path:
        return self.state_dir / "tool_gaps_ignore.txt"    # 確定不做的關鍵字,一行一個

    @property
    def tool_gaps_resolved_path(self) -> Path:
        return self.state_dir / "tool_gaps_resolved.jsonl"  # 已補好的關鍵字與時間:那之前的紀錄不再提醒

    @property
    def tool_gaps_reported_path(self) -> Path:
        return self.state_dir / "tool_gaps_reported"      # 今天提醒過沒(日期)

    @property
    def quarantine_dir(self) -> Path:
        # 攝入在庫裡留下的沒追蹤檔搬來這裡,不刪(檔案不能丟)
        return self.state_dir / "quarantine"

    @property
    def wiki_stage_dir(self) -> Path:
        # 個人庫頁面的副本:攝入的 claude 只寫這裡(不是 git 庫、沒有 hook),程式驗證後才寫回個人庫並 commit。
        # 個人庫的 pre-commit hook 會執行庫裡的 python 腳本,claude 改得到真的個人庫就等於能跑任意程式
        return self.state_dir / "wiki-stage"

    @property
    def wiki_refused_dir(self) -> Path:
        # 回填沒過驗證時,claude 寫在副本裡的改動留在這裡(`<sha256>/`),不寫進個人庫
        return self.state_dir / "wiki-refused"

    @property
    def md_cache(self) -> Path:
        # 不放 WIKI/FWIKI 底下:分流前不知道去哪個庫,公事內容不可落在個人庫的樹裡;
        # WIKI 自己的 .md_cache 也會被它的 doc2md 執行清掉
        return self.state_dir / "md_cache"

    @classmethod
    def default(cls) -> "Config":
        """真實環境的設定:執行狀態目錄裡有 config.toml 就照它(朋友版,Mac 與 Windows)。
        沒有的話,只有使用者本人的 Mac 認得出來——owner_mac.py 不發佈到公開 repo,朋友那台沒有這個檔;
        其他一律大聲失敗、說明要放哪。絕不退回使用者的設定:會拿使用者的路徑收件、寄使用者的信(使用者 2026-10-20)。"""
        state = state_dir_for(PLATFORM, Path.home(), os.environ)
        path = state / CONFIG_FILE
        if path.exists():
            return cls.from_file(path, state)
        if PLATFORM == "darwin":    # 使用者的 Windows 也有這個私人 repo:那台不可拿到 Mac 的路徑
            try:
                from . import owner_mac
            except ModuleNotFoundError as e:
                if e.name != f"{__package__}.owner_mac":
                    raise
            else:
                return owner_mac.config()
        raise ConfigError(f"找不到設定檔 {path}:先執行安裝(Windows 是 安裝.bat、Mac 是 install.sh),它會問完問題寫好這個檔")

    @classmethod
    def from_file(cls, path: Path, state: Path) -> "Config":
        """單庫的設定檔(朋友的 Windows 版):一個知識庫、收件匣、寄信、doc2md 與 claude 的位置。

        不認得的鍵一律報錯:拼錯的鍵安靜地被略過,收件匣就變成「沒設定」、檔案一直沒人收。
        """
        try:
            # utf-8-sig:記事本的「UTF-8 (BOM)」、PowerShell 5.1 寫的檔開頭有 BOM,tomllib 不認
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"設定檔 {path} 讀不了:{e}") from e
        known = {"inbox": {"icloud", "onedrive"}, "wiki": {"dir", "raw", "label", "github", "branch"},
                 "mail": {"from", "to"}, "tools": {"doc2md", "claude", "ffmpeg"}}
        problems = [f"[{k}]" for k in data if k not in known]
        problems += [f"[{k}] {x}" for k, keys in known.items() for x in data.get(k, {}) if x not in keys]
        if problems:
            raise ConfigError(f"設定檔 {path} 有不認得的設定:{'、'.join(problems)}")
        inbox, wiki, mail, tools = (data.get(k, {}) for k in ("inbox", "wiki", "mail", "tools"))
        for k in ("dir", "raw"):
            if not wiki.get(k):
                raise ConfigError(f"設定檔 {path} 沒有 [wiki] {k}")
        if not tools.get("doc2md"):
            raise ConfigError(f"設定檔 {path} 沒有 [tools] doc2md(meeting-scribe 安裝資料夾裡的 doc2md)")
        if not inbox.get("icloud") and not inbox.get("onedrive"):
            raise ConfigError(f"設定檔 {path} 沒有任何收件匣([inbox] icloud 或 onedrive)")

        def opt(v: str | None) -> Path | None:
            return Path(v) if v else None

        raw = Path(wiki["raw"])
        return cls(
            # 收件區不可與原件樹的 _待處理 同一個:收件區的檔搬進 _待處理 時會把自己改名成 X_2
            pending_dir=raw / INTAKE_DIR,
            raw_roots=(raw,),
            raw_skip_dirs=("_待處理", "_捨棄候選", INTAKE_DIR),
            state_dir=state,
            icloud_inbox=opt(inbox.get("icloud")),
            onedrive_inbox=opt(inbox.get("onedrive")),
            futures=None,
            repos=(RepoConfig("main", wiki.get("label", "知識庫"), Path(wiki["dir"]), raw,
                              wiki.get("github", ""), wiki.get("branch", "master"), managed=True),),
            target_repo="main",
            backfill_repo="",
            claude_cmd=(tools.get("claude") or shutil.which("claude") or "claude",),
            ingest_tools_cmd=INGEST_TOOLS_CMD,
            mail_from=mail.get("from", ""),
            mail_to=mail.get("to", ""),
            doc2md_cmd=(tools["doc2md"],),
            ffmpeg=tools.get("ffmpeg") or find_ffmpeg(Path(tools["doc2md"])),
        )
