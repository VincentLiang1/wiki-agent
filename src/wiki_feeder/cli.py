"""命令列入口:`uv run wiki-feeder collect`。"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler

from .collect import build_inboxes, collect, deploy_guard
from .config import Config, ConfigError
from .convert import convert
from .ingest import FILE_TOOLS, PAGE_TOOLS, IngestReport, ingest, post_summary
from .i18n import L, detect, set_lang
from .ledger import Ledger
from .osplat import WINDOWS, fill_missing_std_streams, hide_child_consoles


CHECK_BRCTL_WAIT = 240   # 安裝時讀 iCloud 同步狀態最多等多久:要留時間給人按「允許」(macsched 的 check 總共等 300 秒)


def _utf8_mode() -> bool:
    return bool(sys.flags.utf8_mode)


LOG_MAX_BYTES = 1_000_000   # 每份 1 MB
LOG_BACKUPS = 5             # 保留最近 5 份舊檔:最多約 6 MB


def _setup_logging(cfg: Config) -> None:
    """log 輪替;終端機執行時另外印到畫面。

    launchd 執行時不印到 stderr:那會寫進 plist 的 StandardErrorPath,那個檔沒有輪替、
    每分鐘一輪會一直長大。launchd 那份只留給 log 設好之前就當掉的 traceback。
    """
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handlers = [RotatingFileHandler(cfg.log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                    encoding="utf-8")]
    if sys.stderr.isatty():
        handlers.append(logging.StreamHandler(sys.stderr))
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def _post_alerts(cfg: Config, alerts: list[str]) -> None:
    """收件、轉寫的新警示也發到當日摘要(攝入自己會發)。launchd 底下沒人看本機的警示檔。"""
    if not alerts:
        return
    try:
        post_summary(cfg, IngestReport(alerts=alerts))
    except Exception as e:  # noqa: BLE001
        logging.error(L("警示發不到當日摘要:%s"), e)


def _summary(label: str, counts: dict[str, int]) -> None:
    """有事才記:每分鐘一輪,空跑的摘要只會把 log 洗掉。終端機手動執行時一律印。"""
    if any(counts.values()) or sys.stderr.isatty():
        logging.info(L("%s:%s"), label, L("、").join(f"{k} {v}" for k, v in counts.items()))


def _only(cfg: Config, names: set[str]) -> Config:
    return replace(
        cfg,
        icloud_inbox=cfg.icloud_inbox if "icloud" in names else None,
        onedrive_inbox=cfg.onedrive_inbox if "onedrive" in names else None,
        futures=cfg.futures if "futures" in names else None,
    )


def _load_config(cfg: Config | None) -> tuple[Config | None, ConfigError | None]:
    """讀設定檔、切到它的語言(一個行程一種語言,i18n.py)。讀不到時錯誤訊息用系統語言:
    先照原文讀一次,失敗才查系統語言再讀一次——常駐每分鐘一輪,讀得到設定檔時不必多跑查語言的子行程。"""
    if cfg is None:
        try:
            cfg = Config.default()
        except ConfigError:
            set_lang(detect())
            try:
                cfg = Config.default()
            except ConfigError as e:
                return None, e
    set_lang(cfg.lang)
    return cfg, None


def main(argv: list[str] | None = None, cfg: Config | None = None) -> int:
    # 先讀設定檔:--help 也要照設定檔的語言;讀不到的錯誤等確定不是 office-dump 才報
    cfg, cfg_error = _load_config(cfg)
    ap = argparse.ArgumentParser(prog="wiki-feeder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help=L("從三個收件匣取件到 Raw_Sources/_待處理/"))
    c.add_argument("--only", help=L("只跑部分入口,逗號分隔:icloud,onedrive,futures"))
    c.add_argument("--list", action="store_true", help=L("只列出雲端收件匣的候選檔,不搬、不碰 FUTURES"))
    c.add_argument("--dirs", action="store_true", help=L("與 --list 一起用:每個知識庫與原件資料夾也各試讀一次"))
    sub.add_parser("convert", help=L("把 _待處理/ 裡取到的檔轉寫／OCR 成 md"))
    sub.add_parser("ingest", help=L("把轉好的檔攝入公事庫(FWIKI)、推送、發當日摘要"))
    sub.add_parser("process", help=L("轉寫＋攝入:convert → ingest(launchd 與收件分開跑,長錄音轉寫時收件不被擋)"))
    sub.add_parser("run", help=L("一輪完整流程:collect → convert → ingest"))
    sub.add_parser("ledger", help=L("列出處理紀錄"))
    sub.add_parser("test-mail", help=L("寄一封測試信,確認 Email 摘要寄得出去、手機會跳通知"))
    rc = sub.add_parser("reconvert", help=L("已停止重試的轉寫檔重新排入(查明原因、修好之後)"))
    rc.add_argument("name", nargs="?", help=L("檔名(_待處理/ 裡的名字),例如 錄音.m4a"))
    rc.add_argument("--all", action="store_true", help=L("全部已停止重試的轉寫檔"))
    rg = sub.add_parser("reingest", help=L("看過摘要後重新攝入某一筆(例如被誤判為捨棄),附上背景說明"))
    rg.add_argument("name", help=L("檔名,例如 IMG_5872.JPG"))
    rg.add_argument("--note", required=True, help=L("背景說明,會寫進攝入提示"))
    sub.add_parser("resume", help=L("檢查過 STOP 之後解除:恢復攝入與補推"))
    w = sub.add_parser("watch", help=L("朋友版 Mac 的簡易看門狗一輪:哪一輪卡住、排程沒載入就發警示到當日摘要,"
                                       "並做 iCloud 定時重啟(每 3 分鐘;不自動修)"))
    w.add_argument("--prefix", default="io.github.wiki-agent", help=L("排程標籤的前綴(實測時換一組)"))
    sub.add_parser("watchdog", help=L("看門狗的一輪:查有沒有卡住、CPU／記憶體被佔用,有就自動修理並寄信(launchd 每 3 分鐘)"))
    q = sub.add_parser("quarantine", help=L("把攝入留在公事庫的沒追蹤檔搬到隔離區(不刪)"))
    q.add_argument("path")
    fs = sub.add_parser("finish-stopped", help=L("STOP 那筆檢查過 commit 後,照攝入回報把原件搬好、記成完成(不重攝入)"))
    fs.add_argument("name")
    sub.add_parser("unstick", help=L("結束超過心跳上限那一輪卡住的子行程"))
    od = sub.add_parser("office-dump", help=L("只讀印出 Office 原件的原文、儲存格顏色與公式(攝入時核對用)"))
    od.add_argument("path")
    ph = sub.add_parser("page-history", help=L("公事庫某頁的 commit 歷史,或 commit message 含關鍵字的 commit(攝入時查用)"))
    ph.add_argument("page", nargs="?")
    ph.add_argument("--grep", help=L("關鍵字(不分大小寫、不當正則)"))
    cd = sub.add_parser("commit-detail", help=L("公事庫某個 commit 的訊息與動到哪些檔(攝入時查用)"))
    cd.add_argument("rev", help=L("commit 雜湊,或 HEAD"))
    cp = sub.add_parser("check-pages", help=L("公事庫(或個人 WIKI、它的副本)頁面的控制字元、CJK 粗體失效(渲染器判定)與該庫規則的 grep 健檢"))
    cp.add_argument("pages", nargs="+")
    mh = sub.add_parser("make-handout", help=L("用公事庫 origin 那一版的 tools/make_handout.py 重產 handouts/ 的講義(攝入時用)"))
    mh.add_argument("--src", required=True, help=L("Wiki_Pages/ 底下的來源頁"))
    mh.add_argument("--out", required=True, help=L("handouts/<頁名>.md"))
    for flag in ("--drop-source", "--no-urls", "--embed-images"):
        mh.add_argument(flag, action="store_true")
    mh.add_argument("--drop", help=L("另外要砍掉的 H2 章節,逗號分隔"))
    mh.add_argument("--drop-alert", help=L("砍掉內文含這些關鍵字的提示區塊,逗號分隔"))
    ai = sub.add_parser("add-image", help=L("把原件或轉寫快取裡的圖轉成 jpg,放進公事庫頁面的 images/(攝入時用,不覆蓋)"))
    ai.add_argument("src")
    ai.add_argument("dest", help=L("Wiki_Pages/<群組>/images/<頁名>/<檔名>.jpg"))
    tg = sub.add_parser("tool-gaps", help=L("攝入工具缺口:近幾天被權限擋下的指令、claude 回報做不到的檢查"))
    tg.add_argument("--days", type=int, default=7)
    tg.add_argument("--ignore", metavar=L("關鍵字"), help=L("確定不做:含這個關鍵字的缺口不再出現在摘要信的提醒"))
    tg.add_argument("--resolved", metavar=L("關鍵字"), action="append", default=[],
                    help=L("已經補好(可重複):在這之前的紀錄不再提醒,之後又出現的照樣列、標「修好後又出現」"))
    ts = sub.add_parser("table-sums", help=L("公事庫某頁每張表各數字欄的加總、與合計列比對(攝入重算統計表時驗算用)"))
    ts.add_argument("page")
    ts.add_argument("--heading", help=L("只看標題(或表前那一行)含這個關鍵字的表"))
    args = ap.parse_args(argv)

    if args.cmd == "office-dump":
        from pathlib import Path

        from .office import dump
        print(dump(Path(args.path)))
        return 0

    if WINDOWS and not _utf8_mode():
        # 台灣的 Windows 預設 cp950:子行程輸出(中文 commit 訊息、路徑)會讀成亂碼,寫進處理紀錄就改不回來
        print(L("請用 UTF-8 模式執行:python -X utf8 -m wiki_feeder …(或設環境變數 PYTHONUTF8=1)"), file=sys.stderr)
        return 2
    fill_missing_std_streams()   # Windows 排程(pythonw.exe)底下 sys.stderr 是 None
    hide_child_consoles()   # Windows 排程(pythonw.exe)底下:子行程不另開主控台視窗
    if cfg is None:
        print(cfg_error, file=sys.stderr)
        return 2
    if args.cmd in FILE_TOOLS:
        # 攝入的 claude 用的寫檔指令:只寫公事庫的 handouts/ 與 images/,參數由 filetools 檢查過才動手
        from .filetools import add_image, make_handout
        from .pagetools import PageToolError
        target = cfg.repo(cfg.target_repo)
        try:
            if args.cmd == "make-handout":
                flags = [f for f, on in (("--drop-source", args.drop_source), ("--no-urls", args.no_urls),
                                         ("--embed-images", args.embed_images)) if on]
                flags += [x for f, v in (("--drop", args.drop), ("--drop-alert", args.drop_alert)) if v
                          for x in (f, v)]
                print(make_handout(target.repo_dir, target.branch, args.src, args.out, flags))
            else:
                print(add_image(target.repo_dir, [target.raw_root, cfg.md_cache], args.src, args.dest))
        except PageToolError as e:
            print(L("失敗:{e}", e=e))
            return 1
        return 0
    if args.cmd in PAGE_TOOLS:
        # 攝入的 claude 用的只讀指令:只看公事庫(照設定,不看 cwd),參數由 pagetools 檢查過才交給 git
        from .pagetools import PageRoot, PageToolError, check_pages, commit_detail, page_history, table_sums
        target = cfg.repo(cfg.target_repo)
        repo = target.repo_dir
        # check-pages 另收個人 WIKI:攝入回填寫的副本,與真的個人 WIKI(只讀)
        roots = [PageRoot(repo.name, repo, raw=target.raw_root, basic=target.managed)]
        if cfg.has_backfill:
            rc = cfg.repo(cfg.backfill_repo)
            wiki = rc.repo_dir
            roots += [PageRoot(f"{wiki.name} 副本", cfg.wiki_stage_dir, True, rc.raw_root),
                      PageRoot(wiki.name, wiki, True, rc.raw_root)]
        try:
            if args.cmd == "page-history":
                print(page_history(repo, args.page, args.grep))
            elif args.cmd == "commit-detail":
                print(commit_detail(repo, args.rev))
            elif args.cmd == "table-sums":
                print(table_sums(repo, args.page, args.heading))
            else:
                print(check_pages(roots, args.pages))
        except PageToolError as e:
            print(L("失敗:{e}", e=e))
            return 1
        return 0

    if args.cmd == "tool-gaps":
        from . import toolgaps
        if args.ignore:
            toolgaps.ignore(cfg, args.ignore)
            print(L("已加進不提醒清單:{word}", word=args.ignore))
        for w in args.resolved:
            toolgaps.resolve(cfg, w)
            print(L("已標成補好:{word}(之前的紀錄不再提醒)", word=w))
        print("\n".join(toolgaps.digest(cfg, days=args.days)) or L("近 {days} 天沒有攝入工具缺口", days=args.days))
        if toolgaps.ignored(cfg):
            print(L("(不提醒:{words})", words=L("、").join(toolgaps.ignored(cfg))))
        return 0

    if args.cmd == "test-mail":
        from .notify import MailError, send
        try:
            send(cfg, L("wiki-feeder 測試信"), L("這是 wiki-feeder 的測試信。手機有跳通知的話,當日摘要就會這樣寄給你。"))
        except MailError as e:
            print(L("失敗:{e}", e=e))
            return 1
        print(L("已寄出:{sender} → {to}", sender=cfg.mail_from, to=cfg.mail_to))
        return 0

    if args.cmd == "reingest":
        from .ingest import IngestError, reingest
        try:
            print(reingest(cfg, args.name, args.note))
        except IngestError as e:
            print(L("失敗:{e}", e=e))
            return 1
        return 0

    if args.cmd == "reconvert":
        if bool(args.name) == args.all:
            print(L("給一個檔名,或用 --all(兩者擇一)"))
            return 2
        from .convert import reconvert
        print(reconvert(cfg, None if args.all else args.name))
        return 0

    if args.cmd == "watch":
        # 朋友版 Mac 的第三個排程(macsched);使用者本人的由看門狗(watchdog)做
        from .repair import friend_round
        _setup_logging(cfg)
        _post_alerts(cfg, friend_round(cfg, (f"{args.prefix}.collect", f"{args.prefix}.process")))
        return 0

    if args.cmd == "watchdog":
        # 不握 deploy.lock:修理完要發佈,握著共享鎖等於自己擋自己
        from .repair import tick
        _setup_logging(cfg)
        msg = tick(cfg)
        if msg != "沒有問題":   # 每 3 分鐘一輪,沒事不記,免得把 log 洗掉
            logging.info("看門狗:%s", msg)
        return 0

    if args.cmd in ("quarantine", "finish-stopped"):
        from .ingest import IngestError, finish_stopped, quarantine
        try:
            print(quarantine(cfg, args.path) if args.cmd == "quarantine" else finish_stopped(cfg, args.name))
        except IngestError as e:
            print(L("失敗:{e}", e=e))
            return 1
        return 0

    if args.cmd == "unstick":
        from .watchdog import unstick
        print(unstick(cfg))
        return 0

    if args.cmd == "resume":
        from .ingest import resume
        print(resume(cfg))
        return 0

    if args.cmd == "ledger":
        with Ledger(cfg.ledger_path) as led:
            for row in led.all_items():
                print("\t".join(str(x) for x in row))
        return 0

    if args.cmd == "collect" and args.list:
        return _work(args, cfg)
    with deploy_guard(cfg.deploy_lock_path) as got:
        if not got:
            return 0   # 正在發佈新版:這輪不跑,下一輪就是新版
        return _work(args, cfg)


def _work(args, cfg: Config) -> int:
    if args.cmd in ("convert", "ingest", "process", "run"):
        _setup_logging(cfg)
        ok = True
        pending_alerts: list[str] = []
        if args.cmd == "run":
            r = collect(cfg)
            ok &= r.ok or r.locked
            pending_alerts += r.new_alerts
            _summary(L("收件"), {L("取到"): len(r.moved), L("重複"): len(r.duplicates), L("失敗"): len(r.failed),
                               L("警示"): len(r.alerts)})
        if args.cmd in ("convert", "process", "run"):
            cr = convert(cfg)
            ok &= cr.ok or cr.locked
            pending_alerts += cr.new_alerts
            _summary(L("轉寫"), {L("成功"): len(cr.done), L("略過"): len(cr.skipped), L("失敗"): len(cr.failed),
                               L("警示"): len(cr.alerts)})
        _post_alerts(cfg, pending_alerts)
        if args.cmd in ("ingest", "process", "run"):
            ir = ingest(cfg)
            ok &= ir.ok or ir.locked
            st = [o.status for o in ir.outcomes]
            _summary(L("攝入"), {L("攝入"): st.count("done"), L("捨棄候選"): st.count("discarded"),
                               L("失敗"): st.count("failed"), L("警示"): len(ir.alerts)})
        return 0 if ok else 1

    # 以下是 collect
    if args.only:
        cfg = _only(cfg, {x.strip().lower() for x in args.only.split(",")})
    if args.list:
        for inbox in build_inboxes(replace(cfg, futures=None)):
            # 每個收件匣都印一行狀態:空的也印,否則「空」與「根本沒跑」分不出來
            try:
                inbox.prepare()
                groups = inbox.candidates()
                # 「可讀」單獨一個鍵:scripts/macsched.py 以 "\t" + L("可讀") 比對(launchd.py 是使用者本人的,永遠原文)
                print(f"{inbox.name}\t{L('可讀')}" + L(",{n} 組候選", n=len(groups)))
                for g in groups:
                    print(f"{inbox.name}\t" + " + ".join(c.rel for c in g))
            except Exception as e:  # noqa: BLE001
                print(f"{inbox.name}\t{L('錯誤:')}{e}")
        # macsched.py check 在 launchd 底下跑:知識庫放在「文件」「桌面」底下的話,App 版要趁安裝時讓系統問過權限
        for repo in cfg.repos if args.dirs else ():
            for d in (repo.repo_dir, repo.raw_root):
                try:
                    os.listdir(d)
                    print(f"{d}\t{L('可讀')}")
                except OSError as e:
                    print(f"{d}\t{L('錯誤:')}{e}")
        if args.dirs and cfg.icloud_restart:
            # iCloud 定時重啟要讀 brctl status(也靠它叫醒 bird)。App 版第一次讀時系統把它算在 wiki-agent 頭上、
            # 跳視窗等人按(2026-10-23 實測:沒人按就一直卡著)——要趁安裝時問完,半夜碰到就每輪卡 60 秒
            from .watchdog import brctl_status, last_sync
            st = brctl_status(timeout=CHECK_BRCTL_WAIT)
            name = L("iCloud 同步狀態")
            print(f"{name}\t{L('可讀')}" if last_sync(st) is not None
                  else f"{name}\t{L('錯誤:')}" + (L("等了 {s} 秒沒有回應", s=CHECK_BRCTL_WAIT) if st is None
                                                  else " ".join(st.split())[:200]))
        return 0

    _setup_logging(cfg)
    r = collect(cfg)
    if r.locked:
        return 0
    _summary(L("收件"), {L("取到"): len(r.moved), L("重複"): len(r.duplicates), L("失敗"): len(r.failed),
                       L("還在變動"): len(r.skipped_unstable), L("警示"): len(r.alerts)})
    _post_alerts(cfg, r.new_alerts)
    return 0 if r.ok else 1
