"""Statistical incident detection. No LLM here: cheap, predictable, testable.

An incident opens when a window's p95 latency exceeds the baseline p95 by
`ratio` for `sustain` consecutive windows. The LLM only runs after this fires.
"""
from __future__ import annotations

from dataclasses import dataclass

from .store import Store


def percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        raise ValueError("empty")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class Incident:
    metric: str
    opened_at: float
    window: tuple[float, float]
    baseline_window: tuple[float, float]
    baseline_value: float
    observed_value: float

    def summary(self) -> str:
        return (f"{self.metric} rose from {self.baseline_value:.2f}s (baseline) "
                f"to {self.observed_value:.2f}s")


def detect_latency_incident(
    store: Store, baseline: tuple[float, float], start: float, end: float,
    window_s: float = 30.0, ratio: float = 1.8, sustain: int = 2, min_requests: int = 5,
) -> Incident | None:
    base = [r["latency_s"] for r in store.requests_between(*baseline)
            if r["status"] == 200 and r["latency_s"] is not None]
    if len(base) < min_requests:
        return None
    base_p95 = percentile(base, 0.95)

    streak = 0
    t = start
    while t + window_s <= end:
        rows = [r["latency_s"] for r in store.requests_between(t, t + window_s)
                if r["status"] == 200 and r["latency_s"] is not None]
        if len(rows) >= min_requests and percentile(rows, 0.95) > base_p95 * ratio:
            streak += 1
            if streak >= sustain:
                return Incident("p95_latency", t + window_s, (t - (sustain - 1) * window_s, t + window_s),
                                baseline, base_p95, percentile(rows, 0.95))
        else:
            streak = 0
        t += window_s
    return None
