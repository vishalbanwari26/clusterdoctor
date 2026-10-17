"""One-shot baseline for large-fleet incidents: a budgeted dump instead of tools.

The raw fleet series is far too large for one prompt, so the baseline gets aggregates:
per-GPU window means for the whole fleet, per-node host CPU, and a downsampled raw series
for the flagged GPU only.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

from .agent import Chat
from .bench import _parse_json
from .gpu import CPU_UTIL, POWER, SM_CLOCK, TEMP, THROTTLE, UTIL, XID
from .gpu_tools import GPU_ROOT_CAUSES
from .store import Store

BASE_SYSTEM = f"""You diagnose one flagged GPU in a large cluster from a one-shot telemetry dump.
Respond with ONLY JSON: {{"root_cause": one of {GPU_ROOT_CAUSES}, "confidence": "high"|"medium"|"low", "reasoning": "<short>"}}.
The data may be simulated. Use insufficient_evidence if the dump cannot decide."""


def fleet_dump(store: Store, node: str, gpu: int, baseline: tuple[float, float],
               incident: tuple[float, float]) -> dict:
    agg = defaultdict(dict)
    q = """SELECT node, gpu, metric, AVG(value) m, MAX(value) mx, AVG(value > 0) share
           FROM gpu_metrics WHERE ts >= ? AND ts < ? GROUP BY node, gpu, metric"""
    for w, (a, b) in (("base", baseline), ("inc", incident)):
        for r in store.db.execute(q, (a, b)):
            row = agg[(r["node"], r["gpu"])]
            key = {UTIL: "util", TEMP: "temp", POWER: "power", SM_CLOCK: "clock"}.get(r["metric"])
            if key:
                row[f"{key}_{w}"] = round(r["m"])
            if w == "inc" and r["metric"] == THROTTLE:
                row["throttled_share"] = round(r["share"], 2)
            if w == "inc" and r["metric"] == XID:
                row["max_xid"] = int(r["mx"])
    host = {}
    for r in store.db.execute("SELECT node, AVG(value) m FROM gpu_metrics WHERE metric=? AND ts>=? AND ts<? "
                              "AND gpu=0 GROUP BY node", (CPU_UTIL, *incident)):
        host[r["node"]] = round(r["m"])
    rnd = lambda v: None if v is None else round(v)  # noqa: E731  (missing samples are legitimate)
    series = [{"t": round(r["ts"] - incident[0]), "util": rnd(r["u"]), "temp": rnd(r["tp"]), "clock": rnd(r["c"])}
              for r in store.db.execute(
                  """SELECT ts, MAX(CASE WHEN metric=? THEN value END) u, MAX(CASE WHEN metric=? THEN value END) tp,
                            MAX(CASE WHEN metric=? THEN value END) c FROM gpu_metrics
                     WHERE node=? AND gpu=? AND ts>=? AND ts<? GROUP BY ts ORDER BY ts""",
                  (UTIL, TEMP, SM_CLOCK, node, gpu, *incident))][::3]
    return {"flagged": f"{node} GPU {gpu}",
            "fleet": [{"gpu": f"{n}/{g}", **v} for (n, g), v in sorted(agg.items())],
            "host_cpu_pct_by_node": host, "flagged_gpu_series_downsampled": series}


def fleet_baseline(chat: Chat, store: Store, node: str, gpu: int, baseline, incident, summary: str) -> dict:
    dump = fleet_dump(store, node, gpu, baseline, incident)
    text = json.dumps(dump)
    t = time.time()
    reply = chat([{"role": "system", "content": BASE_SYSTEM},
                  {"role": "user", "content": f"Incident: {summary}\n\n{text}"}], [])
    parsed = _parse_json(reply.get("content") or "")
    ok = parsed is not None and parsed.get("root_cause") in GPU_ROOT_CAUSES
    return {"root_cause": parsed["root_cause"] if ok else "unparseable",
            "confidence": parsed.get("confidence", "low") if ok else "low",
            "latency_s": time.time() - t, "dump_chars": len(text),
            "prompt_tokens": reply.get("prompt_tokens") or 0, "completion_tokens": reply.get("completion_tokens") or 0}
