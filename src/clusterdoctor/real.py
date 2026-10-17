"""Load the derived AcmeTrace Kalos slices (real telemetry) into the same store the agent reads.

Data: AcmeTrace, Shanghai AI Laboratory, CC-BY-4.0. See data/real/kalos_events.json for attribution.
Only utilization, temperature, power and (for the target GPU) the Xid code exist in these slices:
no clock, throttle-reason or host-CPU series. Missing samples are simply not stored.
"""
from __future__ import annotations

import json
from pathlib import Path

from .gpu import POWER, SCHEMA, TEMP, UTIL, XID
from .store import Store

SLICES = Path(__file__).resolve().parents[2] / "data" / "real" / "kalos_events.json"
_KEY = {"util": UTIL, "temp": TEMP, "power": POWER}


def load_slices(path: Path = SLICES) -> dict:
    return json.loads(Path(path).read_text())


def load_event(store: Store, ev: dict, source: str = "real") -> dict:
    """Insert one event into gpu_metrics with times as seconds from the first sample.

    Returns {node, gpu, onset, duration}. The target GPU's Xid series is 0 before the event, the code after.
    """
    store.db.executescript(SCHEMA)
    t0 = min(m["t"][0] for m in ev["metrics"].values())
    t_end = max(m["t"][-1] for m in ev["metrics"].values())
    node, tgt = ev["node"], ev["gpu_index"]
    rows = []
    for key, m in ev["metrics"].items():
        for g, vals in m["v"].items():
            for ts, v in zip(m["t"], vals):
                if v is not None:
                    rows.append((ts - t0, node, int(g), _KEY[key], v, source))
    onset = ev["event_epoch"] - t0
    for ts in ev["metrics"]["util"]["t"]:
        rows.append((ts - t0, node, tgt, XID, float(ev["xid"]) if ts >= ev["event_epoch"] else 0.0, source))
    with store.lock:
        store.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows)
        store.db.commit()
    return {"node": node, "gpu": tgt, "onset": onset, "duration": t_end - t0}
