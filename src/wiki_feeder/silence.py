"""錄音裡的長段空白(例如中場休息忘了按停),列進 PR 摘要讓審核的人知道中間停過。

doc2md 的逐字稿只在換講者時標時間、執行紀錄也沒有分段時間,所以直接量音檔:
afconvert(macOS 內建)解成 8 kHz 單聲道 WAV → 每 window 秒算一次音量 →
以 Otsu 法把音量分成「安靜」「有聲」兩群 → 連續 ≥ min_gap 秒安靜才算一段。

門檻依每份錄音自己算、不用固定 dB:會議室的冷氣聲、手機收音的底噪每份都不同,
固定門檻不是把整場判成沒聲音、就是一段都抓不到。
"""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from .osplat import decode_cmd

_RATE = 8000


def decode(path: Path, out_wav: Path, ffmpeg: str = "") -> None:
    cmd = decode_cmd(str(path), str(out_wav), _RATE, ffmpeg)   # Mac:afconvert;Windows:meeting-scribe 的 ffmpeg
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} 解不開 {path.name}:{r.stderr.strip()}")


def window_db(samples: np.ndarray, rate: int, window: float) -> np.ndarray:
    n = max(1, int(rate * window))
    usable = len(samples) // n * n
    if usable == 0:
        return np.array([])
    frames = samples[:usable].astype(np.float64).reshape(-1, n) / 32768.0
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    return 20 * np.log10(rms + 1e-10)


def quiet_threshold(db: np.ndarray, margin_db: float) -> float | None:
    """用 Otsu 法把每秒音量分成「安靜」「有聲」兩群,回傳分界;兩群差不到 margin_db 就回 None(沒有安靜段)。

    ⚠️ 不可用「第 N 百分位當底噪」:那是假設安靜時間佔一定比例——整場幾乎沒停過時,
    估出來的底噪其實是講話音量,整場被判成無語音;錄音機忘了關、後面兩小時空白時則相反。
    兩種實測都踩過(2 小時合成錄音、中間 5 分鐘安靜 → 整場判成無語音)。
    """
    x = np.clip(db, -100.0, 0.0)
    if x.size < 2 or x.max() - x.min() < margin_db:
        return None
    hist, edges = np.histogram(x, bins=200)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers)
    m0 = s0 / np.maximum(w0, 1)
    m1 = (s0[-1] - s0) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    k = int(np.argmax(between[:-1]))
    if m1[k] - m0[k] < margin_db:
        return None
    return float(edges[k + 1])


def find_gaps(db: np.ndarray, window: float, margin_db: float, min_gap: float) -> list[tuple[float, float]]:
    """回傳 [(開始秒, 結束秒), ...]。"""
    if db.size == 0:
        return []
    thr = quiet_threshold(db, margin_db)
    if thr is None:
        return []
    quiet = np.clip(db, -100.0, 0.0) < thr
    gaps, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * window >= min_gap:
                gaps.append((start * window, i * window))
            start = None
    return gaps


def analyze(path: Path, window: float, margin_db: float, min_gap: float,
            ffmpeg: str = "") -> tuple[float, list[tuple[float, float]]]:
    """回傳 (錄音長度秒, 長段空白清單)。"""
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        decode(path, wav, ffmpeg)
        with wave.open(str(wav)) as w:
            rate = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    duration = len(samples) / rate
    return duration, find_gaps(window_db(samples, rate, window), window, margin_db, min_gap)


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def describe(gaps: list[tuple[float, float]]) -> list[str]:
    return [f"第 {fmt_time(a)}–{fmt_time(b)} 無語音" for a, b in gaps]
