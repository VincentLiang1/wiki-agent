"""處理紀錄:以 SHA-256 為鍵、三個入口共用。

⚠️ `record()` 一定要在刪來源之前呼叫、而且 commit 完才回傳——
順序反過來,中途當掉就會出現「來源刪了、紀錄卻沒有」的狀態。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    sha256        TEXT PRIMARY KEY,
    size          INTEGER NOT NULL,
    source        TEXT NOT NULL,
    original_path TEXT NOT NULL,
    dest_path     TEXT NOT NULL,
    taken_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversions (
    sha256        TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL,      -- done / skipped / failed
    md_path       TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    log_path      TEXT,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingests (
    sha256        TEXT PRIMARY KEY,
    status        TEXT NOT NULL,      -- moving / moved / ingesting / done / failed / discarded / attached / gone
                                      -- / stopped(STOP,等人)。moving、ingesting 是先寫再做的進行中狀態:
                                      -- 當掉後下一輪看得出做到哪(moving 接著搬完,ingesting 轉成 STOP)
    repo          TEXT,               -- 攝入哪個庫(目前一律 company)
    raw_path      TEXT,               -- 原件目前的位置(攝入後是主題資料夾裡的位置)
    result        TEXT,               -- 攝入回報 JSON(頁面、commit、待確認)
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_index (
    path          TEXT PRIMARY KEY,   -- Raw_Sources／FRaw_Sources 底下既有的原件
    sha256        TEXT NOT NULL,
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_index_sha ON raw_index(sha256);
CREATE TABLE IF NOT EXISTS duplicates (
    sha256        TEXT NOT NULL,
    source        TEXT NOT NULL,
    original_path TEXT NOT NULL,
    seen_at       TEXT NOT NULL
);
"""


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # 收件與轉寫攝入是兩個 agent、同時開這個檔;預設 5 秒等不到鎖就丟例外
        self._db = sqlite3.connect(path, timeout=30)
        try:
            # WAL:讀的人不擋寫的人。看門狗每 3 分鐘讀一次,不能害攝入等鎖逾時、留下 ingesting 而 STOP
            self._db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass   # 別人正握著鎖切不了:下次開檔再切(設定會留在檔案裡)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def lookup(self, sha256: str) -> str | None:
        row = self._db.execute("SELECT dest_path FROM items WHERE sha256 = ?", (sha256,)).fetchone()
        return row[0] if row else None

    def record(self, sha256: str, size: int, source: str, original_path: str, dest_path: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
                (sha256, size, source, original_path, dest_path, _now()),
            )

    def record_duplicate(self, sha256: str, source: str, original_path: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO duplicates VALUES (?, ?, ?, ?)",
                (sha256, source, original_path, _now()),
            )

    # -- M2 轉寫 ---------------------------------------------------------------
    def pending_conversions(self, max_attempts: int) -> list[tuple[str, str]]:
        """還沒轉、或失敗次數未達上限的 (sha256, dest_path)。"""
        return self._db.execute(
            """SELECT i.sha256, i.dest_path FROM items i
               LEFT JOIN conversions c ON c.sha256 = i.sha256
               WHERE c.sha256 IS NULL OR (c.status = 'failed' AND c.attempts < ?)
               ORDER BY i.taken_at""",
            (max_attempts,),
        ).fetchall()

    def conversion_done(self, sha256: str, kind: str, status: str, md_path: str | None) -> None:
        with self._db:
            self._db.execute(
                """INSERT INTO conversions (sha256, kind, status, md_path, attempts, updated_at)
                   VALUES (?, ?, ?, ?, 0, ?)
                   ON CONFLICT(sha256) DO UPDATE SET kind=excluded.kind, status=excluded.status,
                       md_path=excluded.md_path, error=NULL, updated_at=excluded.updated_at""",
                (sha256, kind, status, md_path, _now()),
            )

    def conversion_failed(self, sha256: str, kind: str, error: str, log_path: str | None) -> int:
        """記一次失敗,回傳累計失敗次數。"""
        with self._db:
            self._db.execute(
                """INSERT INTO conversions (sha256, kind, status, attempts, error, log_path, updated_at)
                   VALUES (?, ?, 'failed', 1, ?, ?, ?)
                   ON CONFLICT(sha256) DO UPDATE SET status='failed', attempts=attempts+1,
                       error=excluded.error, log_path=excluded.log_path, updated_at=excluded.updated_at""",
                (sha256, kind, error, log_path, _now()),
            )
        return self._db.execute("SELECT attempts FROM conversions WHERE sha256 = ?", (sha256,)).fetchone()[0]

    def stuck_conversions(self, max_attempts: int) -> list[tuple[str, str, str]]:
        """已停止重試的轉寫 (sha256, 目前路徑, 最後一次的錯誤)。"""
        return self._db.execute(
            """SELECT i.sha256, i.dest_path, c.error FROM items i JOIN conversions c ON c.sha256 = i.sha256
               WHERE c.status = 'failed' AND c.attempts >= ? ORDER BY i.taken_at""",
            (max_attempts,),
        ).fetchall()

    def conversion_reset(self, sha256: str) -> None:
        with self._db:
            self._db.execute("UPDATE conversions SET attempts = 0 WHERE sha256 = ? AND status = 'failed'", (sha256,))

    def conversion(self, sha256: str) -> tuple | None:
        return self._db.execute(
            "SELECT kind, status, md_path, attempts, error FROM conversions WHERE sha256 = ?", (sha256,)
        ).fetchone()

    # -- M3 分流與攝入 ---------------------------------------------------------
    def ingest_candidates(self, max_attempts: int) -> list[tuple[str, str, str]]:
        """轉寫已完成、還沒攝入完的 (sha256, 目前路徑, 轉寫種類)。"""
        return self._db.execute(
            """SELECT i.sha256, COALESCE(g.raw_path, i.dest_path), c.kind FROM items i
               JOIN conversions c ON c.sha256 = i.sha256 AND c.status IN ('done', 'skipped')
               LEFT JOIN ingests g ON g.sha256 = i.sha256
               WHERE g.sha256 IS NULL OR g.status IN ('moving', 'moved')
                  OR (g.status = 'failed' AND g.attempts < ?)
               ORDER BY i.taken_at""",
            (max_attempts,),
        ).fetchall()

    def stuck_ingests(self, max_attempts: int) -> list[str]:
        """攝入已停止重試的原件目前路徑。"""
        return [r[0] for r in self._db.execute(
            """SELECT i.dest_path FROM items i JOIN ingests g ON g.sha256 = i.sha256
               WHERE g.status = 'failed' AND g.attempts >= ? ORDER BY i.taken_at""",
            (max_attempts,))]

    def interrupted_ingests(self) -> list[tuple[str, str]]:
        """上一輪攝入到一半當掉的 (sha256, 原件路徑):攝入握著鎖,開頭還看得到 ingesting 就是當掉留下的。"""
        return self._db.execute(
            """SELECT g.sha256, COALESCE(g.raw_path, i.dest_path) FROM ingests g
               JOIN items i ON i.sha256 = g.sha256 WHERE g.status = 'ingesting' ORDER BY i.taken_at""").fetchall()

    def ingest_row(self, sha256: str) -> dict | None:
        cur = self._db.execute("SELECT * FROM ingests WHERE sha256 = ?", (sha256,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    def stopped_ingests(self) -> list[tuple[str, str]]:
        return self._db.execute(
            """SELECT g.sha256, COALESCE(g.raw_path, i.dest_path) FROM ingests g
               JOIN items i ON i.sha256 = g.sha256 WHERE g.status = 'stopped' ORDER BY i.taken_at""").fetchall()

    def ingest_row_by_path(self, dest_path: str) -> dict | None:
        cur = self._db.execute("SELECT g.* FROM ingests g JOIN items i ON i.sha256 = g.sha256 WHERE i.dest_path = ?",
                               (dest_path,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    def ingest_set(self, sha256: str, status: str, **fields) -> None:
        """寫入或更新一筆攝入狀態;fields 只更新給到的欄位。"""
        cols = ["status", "updated_at", *fields]
        vals = [status, _now(), *fields.values()]
        with self._db:
            self._db.execute(
                f"INSERT INTO ingests (sha256, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
                f"ON CONFLICT(sha256) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in cols)}",
                (sha256, *vals),
            )

    def ingest_failed(self, sha256: str, error: str) -> int:
        with self._db:
            self._db.execute(
                """INSERT INTO ingests (sha256, status, attempts, error, updated_at) VALUES (?, 'failed', 1, ?, ?)
                   ON CONFLICT(sha256) DO UPDATE SET status='failed', attempts=attempts+1,
                       error=excluded.error, updated_at=excluded.updated_at""",
                (sha256, error, _now()),
            )
        return self._db.execute("SELECT attempts FROM ingests WHERE sha256 = ?", (sha256,)).fetchone()[0]

    def finished_md(self, older_than_iso: str) -> list[tuple[str, str]]:
        """攝入已結束(完成／捨棄／移走)且早於某時間的 (sha256, md_path)。"""
        return self._db.execute(
            """SELECT c.sha256, c.md_path FROM conversions c JOIN ingests g ON g.sha256 = c.sha256
               WHERE c.md_path IS NOT NULL AND g.status IN ('done', 'discarded', 'gone')
                 AND g.updated_at < ?""",
            (older_than_iso,),
        ).fetchall()

    def forget_md(self, sha256: str) -> None:
        with self._db:
            self._db.execute("UPDATE conversions SET md_path = NULL WHERE sha256 = ?", (sha256,))

    def move_item(self, sha256: str, new_path: str) -> None:
        with self._db:
            self._db.execute("UPDATE items SET dest_path = ? WHERE sha256 = ?", (new_path, sha256))

    # -- 既有原件索引 ---------------------------------------------------------
    def refresh_raw_index(self, roots: tuple[Path, ...], skip_dirs: tuple[str, ...]) -> tuple[int, int]:
        """增量更新:大小與修改時間沒變的不重算。回傳 (重算雜湊的檔數, 移除的筆數)。"""
        from .mover import sha256_of  # 避免循環匯入

        known = {r[0]: (r[1], r[2]) for r in self._db.execute("SELECT path, size, mtime_ns FROM raw_index")}
        seen, rows = set(), []
        for root in roots:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                if Path(dirpath) == root:
                    dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    if fn.startswith("."):
                        continue
                    fp = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(fp)
                    except OSError:
                        continue
                    seen.add(fp)
                    if known.get(fp) == (st.st_size, st.st_mtime_ns):
                        continue
                    try:
                        sha = sha256_of(Path(fp))
                    except OSError:
                        continue
                    rows.append((fp, sha, st.st_size, st.st_mtime_ns))
        # 只清掉「這次有掃的根目錄」底下不見的檔:只更新 FRaw_Sources 時不可把 Raw_Sources 的索引全清掉
        # (實測踩過:攝入只更新公事庫的索引,下一輪收件就把兩萬個原件全部重算一次)
        prefixes = tuple(_dir_prefix(r) for r in roots)
        gone = [p for p in known if p not in seen and p.startswith(prefixes)]
        # 雜湊全算完才一次寫入:邊算邊 INSERT 會整段握著寫鎖(整樹重算實測 4.7 秒),
        # 另一個 agent 的寫入等滿 timeout 就丟 database is locked,攝入在 commit 之後當掉
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO raw_index VALUES (?, ?, ?, ?)", rows)
            self._db.executemany("DELETE FROM raw_index WHERE path = ?", [(p,) for p in gone])
        return len(rows), len(gone)

    def raw_shas_under(self, root: Path) -> set[str]:
        prefix = _dir_prefix(root)
        # 不用 LIKE:路徑裡的 _(例如 FRaw_Sources)在 LIKE 是萬用字元
        return {r[0] for r in self._db.execute(
            "SELECT sha256 FROM raw_index WHERE substr(path, 1, ?) = ?", (len(prefix), prefix))}

    def raw_paths_under(self, root: Path) -> dict[str, str]:
        """{路徑: sha256}:STOP 時要能說出消失的是哪一份。"""
        prefix = _dir_prefix(root)
        return dict(self._db.execute(
            "SELECT path, sha256 FROM raw_index WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)))

    def raw_lookup(self, sha256: str) -> str | None:
        row = self._db.execute("SELECT path FROM raw_index WHERE sha256 = ? LIMIT 1", (sha256,)).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def all_items(self) -> list[tuple]:
        return self._db.execute("SELECT * FROM items ORDER BY taken_at").fetchall()


def _dir_prefix(root, sep: str = os.sep) -> str:
    """索引裡「這個目錄底下」的路徑前綴。用系統的分隔字元:索引存的是 os.walk 組出來的路徑,Windows 是 `\\`;
    寫死 `/` 的話 Windows 上什麼都比對不到——原件少一份也不會 STOP(2026-10-19 Windows 實測)。"""
    return str(root).rstrip(sep) + sep


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
