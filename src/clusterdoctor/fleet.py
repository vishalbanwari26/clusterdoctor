"""Fleet watcher: flags GPUs whose utilization drops well below their own baseline.

Statistical, no LLM. Per-GPU baselines mean one slow GPU does not hide behind
a healthy fleet average.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .gpu import UTIL
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
                    min_baseline: float = 20.0) -> list[GpuIncident]:
    """An incident opens when a GPU's mean utilization is below (1-drop) x baseline for `sustain` windows."""
    gpus = store.db.execute("SELECT DISTINCT node, gpu FROM gpu_metrics ORDER BY node, gpu").fetchall()
    found = []
    for g in gpus:
        base = _util(store, g["node"], g["gpu"], *baseline)
        if len(base) < 3 or statistics.mean(base) < min_baseline:  # skip GPUs that were never busy
            continue
        base_mean, streak, t = statistics.mean(base), 0, start
        while t + window_s <= end:
            w = _util(store, g["node"], g["gpu"], t, t + window_s)
            if w and statistics.mean(w) < base_mean * (1 - drop):
                streak += 1
                if streak >= sustain:
                    found.append(GpuIncident(g["node"], g["gpu"], t + window_s, base_mean, statistics.mean(w),
                                             (t - (sustain - 1) * window_s, t + window_s)))
                    break
            else:
                streak = 0
            t += window_s
    return found
