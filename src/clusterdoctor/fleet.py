"""Fleet watcher: flags GPUs whose utilization drops well below their own baseline.

Statistical, no LLM. Per-GPU baselines mean one slow GPU does not hide behind
a healthy fleet average.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .gpu import UTIL, XID
from .store import Store


@dataclass
class GpuIncident:
    node: str
    gpu: int
    opened_at: float
    baseline_util: float
    observed_util: float
    window: tuple[float, float] = (0.0, 0.0)

    def summary(self) -> str:
        return (f"{self.node} GPU {self.gpu}: utilization fell from {self.baseline_util:.0f}% "
                f"to {self.observed_util:.0f}%")


def _util(store: Store, node: str, gpu: int, start: float, end: float) -> list[float]:
    return [r["value"] for r in store.db.execute(
        "SELECT value FROM gpu_metrics WHERE node=? AND gpu=? AND metric=? AND ts>=? AND ts<?",
        (node, gpu, UTIL, start, end))]


def detect_low_util(store: Store, baseline: tuple[float, float], start: float, end: float,
                    window_s: float = 60.0, drop: float = 0.4, sustain: int = 2,
                    min_baseline: float = 20.0, min_samples: int = 2) -> list[GpuIncident]:
    """An incident opens when a GPU's mean utilization is below (1-drop) x baseline for `sustain` windows.

    Real telemetry has gaps. A GPU with no usable baseline is skipped (it cannot be judged), and a window
    with fewer than `min_samples` samples counts as unknown and breaks the streak.
    """
    gpus = store.db.execute("SELECT DISTINCT node, gpu FROM gpu_metrics ORDER BY node, gpu").fetchall()
    found = []
    for g in gpus:
        base = _util(store, g["node"], g["gpu"], *baseline)
        if len(base) < 3 or statistics.mean(base) < min_baseline:  # skip GPUs that were never busy
            continue
        base_mean, streak, t = statistics.mean(base), 0, start
        while t + window_s <= end:
            w = _util(store, g["node"], g["gpu"], t, t + window_s)
            if len(w) >= min_samples and statistics.mean(w) < base_mean * (1 - drop):
                streak += 1
                if streak >= sustain:
                    found.append(GpuIncident(g["node"], g["gpu"], t + window_s, base_mean, statistics.mean(w),
                                             (t - (sustain - 1) * window_s, t + window_s)))
                    break
            else:
                streak = 0
            t += window_s
    return found


@dataclass
class XidIncident:
    node: str
    gpu: int
    opened_at: float
    code: int
    previous: int

    def summary(self) -> str:
        return f"{self.node} GPU {self.gpu}: driver reported Xid {self.code}"


def detect_xid_change(store: Store, start: float, end: float) -> list[XidIncident]:
    """Opens an incident when a GPU's Xid value changes to a new nonzero code inside [start, end).

    The DCGM Xid field is sticky (it keeps the last code), so a nonzero value alone is not an event:
    only a change is. A GPU with no sample before `start` starts from its first sample: nothing can
    be said about a change that happened before the data begins.
    """
    out = []
    gpus = store.db.execute("SELECT DISTINCT node, gpu FROM gpu_metrics WHERE metric=? ORDER BY node, gpu", (XID,)).fetchall()
    for g in gpus:
        before = store.db.execute(
            "SELECT value FROM gpu_metrics WHERE node=? AND gpu=? AND metric=? AND ts<? ORDER BY ts DESC LIMIT 1",
            (g["node"], g["gpu"], XID, start)).fetchone()
        prev = int(before["value"]) if before else None
        for r in store.db.execute(
                "SELECT ts, value FROM gpu_metrics WHERE node=? AND gpu=? AND metric=? AND ts>=? AND ts<? ORDER BY ts",
                (g["node"], g["gpu"], XID, start, end)):
            v = int(r["value"])
            if prev is None:
                prev = v
                continue
            if v != prev and v > 0:
                out.append(XidIncident(g["node"], g["gpu"], r["ts"], v, prev))
                break
            prev = v
    return out
