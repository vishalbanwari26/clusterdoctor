"""Scale test fleet: 32 racks x 8 nodes x 8 GPUs = 2,048 simulated GPUs, 6 h at 30 s (about 4.4M samples).

Pre-registered in docs/preregistered-tests.md. Four families of cause x 5 cases, all in one fleet, so every case sees the others as
distractors. Windows are relative to the anomaly onset (hour 4)."""
from __future__ import annotations

import copy
import json
import random
import statistics
import time

from .agent import Chat
from .bench import _parse_json
from .gpu import POWER, SCHEMA, TEMP, UTIL
from .gpu_tools import GPU_TOOL_SPECS, _spec
from .store import Store

RACKS, NODES, GPUS, STEP, DUR, ONSET = 32, 8, 8, 30.0, 21600.0, 14400.0
BASE_WIN = (0.0, ONSET - 600)
INC_WIN = (ONSET + 1200, ONSET + 1800)          # 20-30 min after onset: every ramp has finished
SERIES_WIN = (ONSET - 600, ONSET + 1800)        # 40 minutes around onset
LABELS = ["gpu_thermal_isolated", "rack_cooling_failure", "slot_position_issue", "node_wide_stall", "insufficient_evidence"]
node_id = lambda r, n: f"r{r:02d}n{n}"  # noqa: E731
rack_of = lambda node: int(node[1:3])  # noqa: E731


def plan(seed: int = 0) -> list[dict]:
    """20 cases. Racks are disjoint across families so cases do not interfere; family C shares racks 16..31 using different slots."""
    rng = random.Random(seed); cases = []
    for i in range(5):                                          # A: one GPU, racks 0..4
        cases.append({"family": "A", "truth": "gpu_thermal_isolated", "rack": i, "node": node_id(i, rng.randrange(NODES)), "gpu": rng.randrange(GPUS)})
    for i in range(5):                                          # B: whole rack, racks 5..9
        r = 5 + i; n = rng.randrange(NODES); g = rng.choice([0, 4])          # hottest quartile: (node*8+g) % 4 == 0
        cases.append({"family": "B", "truth": "rack_cooling_failure", "rack": r, "node": node_id(r, n), "gpu": g})
    for i in range(5):                                          # C: one slot index on 16 nodes over 8 racks
        slot = i + 1; racks = rng.sample(range(16, 32), 8)
        nodes = [node_id(r, n) for r in racks for n in rng.sample(range(NODES), 2)]
        cases.append({"family": "C", "truth": "slot_position_issue", "slot": slot, "nodes": nodes, "node": nodes[0], "gpu": slot})
    for i in range(5):                                          # D: one node, racks 10..14
        r = 10 + i; n = rng.randrange(NODES)
        cases.append({"family": "D", "truth": "node_wide_stall", "rack": r, "node": node_id(r, n), "gpu": rng.randrange(GPUS)})
    for i, c in enumerate(cases): c["id"] = f"c{i:02d}"
    return cases


def plan_v2(seed: int = 3) -> list[dict]:
    """v2: A 3, B 3, D 3 as before; C is ONE clean slot issue (slot 3 on 16 nodes) with 5 different flagged GPUs among them."""
    rng = random.Random(seed); cases = []
    for i in range(3):
        cases.append({"family": "A", "truth": "gpu_thermal_isolated", "rack": i, "node": node_id(i, rng.randrange(NODES)), "gpu": rng.randrange(GPUS)})
    for i in range(3):
        r = 5 + i; n = rng.randrange(NODES)
        cases.append({"family": "B", "truth": "rack_cooling_failure", "rack": r, "node": node_id(r, n), "gpu": rng.choice([0, 4])})
    for i in range(3):
        r = 10 + i
        cases.append({"family": "D", "truth": "node_wide_stall", "rack": r, "node": node_id(r, rng.randrange(NODES)), "gpu": rng.randrange(GPUS)})
    racks = rng.sample(range(16, 32), 8)
    nodes = [node_id(r, n) for r in racks for n in rng.sample(range(NODES), 2)]
    flagged = rng.sample(nodes, 5)
    for nd in flagged:
        cases.append({"family": "C", "truth": "slot_position_issue", "slot": 3, "nodes": nodes, "node": nd, "gpu": 3})
    for i, c in enumerate(cases): c["id"] = f"v{i:02d}"
    return cases


def generate(store: Store, cases: list[dict], seed: int = 1) -> None:
    rng = random.Random(seed)
    store.db.executescript(SCHEMA)
    ramp = lambda t, mins: 0.0 if t < ONSET else min(1.0, (t - ONSET) / (mins * 60))  # noqa: E731
    hot_single = {(c["node"], c["gpu"]) for c in cases if c["family"] == "A"}
    hot_racks = {c["rack"] for c in cases if c["family"] == "B"}
    slot_hot = {(n, c["slot"]) for c in cases if c["family"] == "C" for n in c["nodes"]}
    stall = {c["node"] for c in cases if c["family"] == "D"}
    offsets = {}
    rows = []; t = 0.0
    while t < DUR:
        for r in range(RACKS):
            for n in range(NODES):
                node = node_id(r, n)
                for g in range(GPUS):
                    off = offsets.setdefault((node, g), rng.gauss(0, 1.5))
                    util, temp = 94 + rng.gauss(0, 3), 62 + off + rng.gauss(0, 1.0)
                    if (node, g) in hot_single:
                        k = ramp(t, 10); temp += 20 * k; util -= 45 * k
                    if r in hot_racks:
                        k = ramp(t, 20); temp += 15 * k
                        if (n * 8 + g) % 4 == 0: util -= 40 * k
                    if (node, g) in slot_hot:
                        k = ramp(t, 10); temp += 18 * k; util -= 45 * k
                    if node in stall and t >= ONSET:
                        util = max(0.0, 4 + rng.gauss(0, 2)); temp = 62 + off - 22 * ramp(t, 10) + rng.gauss(0, 1.0)
                    util = max(0.0, min(100.0, util))
                    power = 90 + 3.2 * util + rng.gauss(0, 5)
                    rows.append((t, node, g, UTIL, util, "simulated")); rows.append((t, node, g, TEMP, temp, "simulated"))
                    rows.append((t, node, g, POWER, power, "simulated"))
        t += STEP
        if len(rows) > 400000:
            store.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); rows = []
    store.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); store.db.commit()


METRIC = {"util": UTIL, "temp": TEMP, "power": POWER}


class BigFleetTools:
    def __init__(self, store: Store, node: str, gpu: int):
        self.store, self.node, self.gpu = store, node, gpu
        self._cache: dict = {}

    def _win(self, w): return {"baseline": BASE_WIN, "incident": INC_WIN}[w]

    def _gpu_means(self, metric: str, w: str) -> dict:
        key = (metric, w)
        if key not in self._cache:
            a, b = self._win(w)
            self._cache[key] = {(r["node"], r["gpu"]): r["m"] for r in self.store.db.execute(
                "SELECT node, gpu, AVG(value) m FROM gpu_metrics WHERE metric=? AND ts>=? AND ts<? GROUP BY node, gpu", (METRIC[metric], a, b))}
        return self._cache[key]

    def compare_windows(self) -> dict:
        return {w: {m: round(self._gpu_means(m, w)[(self.node, self.gpu)], 1) for m in METRIC} for w in ("baseline", "incident")}

    def series(self, metric: str, start_min: int = -10, end_min: int = 30) -> list[dict]:
        a, b = ONSET + start_min * 60, ONSET + end_min * 60
        rows = self.store.db.execute("SELECT ts, value FROM gpu_metrics WHERE node=? AND gpu=? AND metric=? AND ts>=? AND ts<? ORDER BY ts",
                                     (self.node, self.gpu, METRIC[metric], a, b)).fetchall()
        step = max(1, len(rows) // 60)
        return [{"min_from_onset": round((r["ts"] - ONSET) / 60, 1), "value": round(r["value"], 1)} for r in rows[::step]]

    def peer_gpus(self) -> list[dict]:
        out = []
        for g in range(GPUS):
            out.append({"gpu": g, "flagged": g == self.gpu, **{m: round(self._gpu_means(m, "incident")[(self.node, g)], 1) for m in METRIC}})
        return out

    def group_stats(self, metric: str, group_by: str, window: str) -> list[dict]:
        if metric not in METRIC or group_by not in ("node", "rack", "gpu_index") or window not in ("baseline", "incident"):
            return {"error": "metric must be util|temp|power, group_by must be node|rack|gpu_index, window must be baseline|incident"}  # type: ignore[return-value]
        keyf = {"node": lambda n, g: n, "rack": lambda n, g: f"rack {rack_of(n)}", "gpu_index": lambda n, g: f"slot {g}"}[group_by]
        groups: dict = {}
        for (n, g), v in self._gpu_means(metric, window).items():
            groups.setdefault(keyf(n, g), []).append(v)
        fleet = statistics.mean(v for vs in groups.values() for v in vs)
        rows = [{"group": k, "mean": round(statistics.mean(v), 2), "n_gpus": len(v), "vs_fleet": round(statistics.mean(v) - fleet, 2)} for k, v in groups.items()]
        return sorted(rows, key=lambda r: -abs(r["vs_fleet"]))[:10]

    def registry(self): return {"compare_windows": self.compare_windows, "series": self.series, "peer_gpus": self.peer_gpus, "group_stats": self.group_stats}


_M = {"type": "string", "enum": list(METRIC)}
_submit = copy.deepcopy(GPU_TOOL_SPECS[-1]); _submit["function"]["parameters"]["properties"]["root_cause"]["enum"] = LABELS
SCALE_SPECS = [
    _spec("compare_windows", "Flagged GPU: mean utilization, temperature and power, normal period vs incident.", {"type": "object", "properties": {}}),
    _spec("series", "Flagged GPU metric over time, at most 60 points. Minutes are relative to the anomaly onset.",
          {"type": "object", "properties": {"metric": _M, "start_min": {"type": "integer"}, "end_min": {"type": "integer"}}, "required": ["metric"]}),
    _spec("peer_gpus", "The 8 GPUs on the flagged GPU's node during the incident.", {"type": "object", "properties": {}}),
    _spec("group_stats", "A metric averaged per group across the whole 2,048-GPU fleet. Returns the 10 groups that deviate most from the fleet mean. group_by: node, rack (8 nodes) or gpu_index (slot position, same index on every node).",
          {"type": "object", "properties": {"metric": _M, "group_by": {"type": "string", "enum": ["node", "rack", "gpu_index"]},
                                           "window": {"type": "string", "enum": ["baseline", "incident"]}}, "required": ["metric", "group_by", "window"]}),
    _submit]

SYSTEM = """You are ClusterDoctor. A fleet of 2,048 GPUs: 32 racks of 8 nodes, 8 GPUs per node (gpu_index = slot position 0 to 7).
One GPU lost utilization. Telemetry (utilization %, temperature C, power W) is simulated, 30 s samples. Possible causes:
- gpu_thermal_isolated: this GPU alone overheats, its neighbours are normal.
- rack_cooling_failure: many GPUs in the same rack run hot.
- slot_position_issue: GPUs at the same slot index run hot across many nodes in different racks (airflow or layout).
- node_wide_stall: every GPU on the node stopped together and temperatures fell (a job ended).
- insufficient_evidence: the data cannot decide.
Use the tools, compare like with like, and finish with submit_diagnosis citing call_ids. Other GPUs in the fleet may be misbehaving for unrelated reasons."""


def dump(store: Store, node: str, gpu: int) -> dict:
    """The pre-registered one-shot dump. Deliberately has no grouping by slot index."""
    t = BigFleetTools(store, node, gpu); r = rack_of(node)
    nodes_in_rack = {}
    for m in METRIC:
        for w in ("baseline", "incident"):
            for (n, g), v in t._gpu_means(m, w).items():
                if rack_of(n) == r:
                    nodes_in_rack.setdefault((n, m, w), []).append(v)
    racks = {}
    for m in METRIC:
        for w in ("baseline", "incident"):
            for (n, g), v in t._gpu_means(m, w).items():
                racks.setdefault((rack_of(n), m, w), []).append(v)
    inc_t = sorted(t._gpu_means("temp", "incident").values()); inc_u = sorted(t._gpu_means("util", "incident").values())
    pct = lambda a, p: round(a[int((len(a) - 1) * p)], 1)  # noqa: E731
    return {
        "flagged_gpu": f"{node} GPU {gpu}", "flagged_gpu_means": t.compare_windows(),
        "flagged_gpu_series_40min": {m: [(x["min_from_onset"], x["value"]) for x in t.series(m, -10, 30)] for m in METRIC},
        "node_gpus_incident": t.peer_gpus(),
        "rack_nodes": [{"node": n, **{f"{m}_{w}": round(statistics.mean(v), 1) for (nn, m, w), v in nodes_in_rack.items() if nn == n}} for n in sorted({k[0] for k in nodes_in_rack})],
        "all_racks": [{"rack": rr, **{f"{m}_{w}": round(statistics.mean(v), 1) for (r2, m, w), v in racks.items() if r2 == rr}} for rr in range(RACKS)],
        "fleet_percentiles_incident": {"util": [pct(inc_u, .01), pct(inc_u, .5), pct(inc_u, .99)], "temp": [pct(inc_t, .01), pct(inc_t, .5), pct(inc_t, .99)]},
    }


def baseline_answer(chat: Chat, store: Store, node: str, gpu: int, summary: str) -> dict:
    d = dump(store, node, gpu); text = json.dumps(d, separators=(",", ":"))
    system = SYSTEM.split("Use the tools")[0] + 'Answer with ONLY JSON: {"root_cause": one of ' + str(LABELS) + ', "confidence": "high"|"medium"|"low", "reasoning": "<short>"}.'
    t = time.time()
    reply = chat([{"role": "system", "content": system}, {"role": "user", "content": f"Incident: {summary}\n\n{text}"}], [])
    p = _parse_json(reply.get("content") or ""); ok = p is not None and p.get("root_cause") in LABELS
    return {"root_cause": p["root_cause"] if ok else "unparseable", "confidence": p.get("confidence", "low") if ok else "low",
            "dump_tokens_est": len(text) // 4, "latency_s": time.time() - t,
            "prompt_tokens": reply.get("prompt_tokens") or 0, "completion_tokens": reply.get("completion_tokens") or 0}
