"""Chart-ready snapshots of an incident's telemetry, for the dashboard."""
from __future__ import annotations

from .gpu import POWER, SM_CLOCK, TEMP, UTIL
from .store import Store
from .tools import Tools
from .watcher import percentile


def latency_chart(store: Store, t0: float, t1: float, t2: float, window_s: float = 10.0) -> dict:
    windows, t = [], t0
    while t < t2:
        lat = [r["latency_s"] for r in store.requests_between(t, t + window_s)
               if r["status"] == 200 and r["latency_s"] is not None]
        windows.append({"t": round(t - t0, 1), "n": len(lat), "p95": round(percentile(lat, 0.95), 2) if lat else None})
        t += window_s
    base = [r["latency_s"] for r in store.requests_between(t0, t1) if r["status"] == 200 and r["latency_s"]]
    return {"kind": "latency", "window_s": window_s, "windows": windows,
            "baseline_p95": round(percentile(base, 0.95), 2), "change_t": round(t1 - t0, 1),
            "events": [{"t": round(e["ts"] - t0, 1), "kind": e["kind"], "detail": e["detail"]}
                       for e in store.events_between(t0, t2)]}


def at_a_glance(store: Store, baseline, incident) -> dict:
    return Tools(store, baseline, incident).compare_windows()


def export_requests(store: Store, t0: float, t2: float) -> dict:
    cols = ("ts", "app_version", "model", "input_tokens", "output_tokens", "latency_s", "ttft_s",
            "status", "retries", "concurrency", "source")
    return {"requests": [[r[c] for c in cols] for r in store.requests_between(t0, t2)], "columns": cols,
            "events": [[e["ts"], e["kind"], e["detail"]] for e in store.events_between(t0, t2)]}


def fleet_chart(store: Store, node: str, gpu: int, baseline: tuple[float, float], incident: tuple[float, float],
                onset: float, duration: float, simulated: bool = True) -> dict:
    cells = {}
    for key, (a, b) in (("util_base", baseline), ("util_inc", incident)):
        for r in store.db.execute("SELECT node, gpu, AVG(value) m FROM gpu_metrics WHERE metric=? AND ts>=? AND ts<? "
                                  "GROUP BY node, gpu", (UTIL, a, b)):
            cells.setdefault((r["node"], r["gpu"]), {})[key] = round(r["m"])
    for r in store.db.execute("SELECT node, gpu, AVG(value) m FROM gpu_metrics WHERE metric=? AND ts>=? AND ts<? "
                              "GROUP BY node, gpu", (TEMP, *incident)):
        cells.setdefault((r["node"], r["gpu"]), {})["temp_inc"] = round(r["m"])
    series = []
    for r in store.db.execute(
            """SELECT ts, MAX(CASE WHEN metric=? THEN value END) u, MAX(CASE WHEN metric=? THEN value END) tp,
                      MAX(CASE WHEN metric=? THEN value END) c, MAX(CASE WHEN metric=? THEN value END) p
               FROM gpu_metrics WHERE node=? AND gpu=? GROUP BY ts ORDER BY ts""",
            (UTIL, TEMP, SM_CLOCK, POWER, node, gpu)):
        series.append({"t": r["ts"], "util": None if r["u"] is None else round(r["u"], 1),
                       "temp": None if r["tp"] is None else round(r["tp"], 1), "clock": None if r["c"] is None else round(r["c"])})
    return {"kind": "fleet", "simulated": simulated, "onset": onset, "duration": duration, "flagged": {"node": node, "gpu": gpu},
            "incident_window": list(incident),
            "cells": [{"node": n, "gpu": g, **v} for (n, g), v in sorted(cells.items())],
            "series": series[::2]}
