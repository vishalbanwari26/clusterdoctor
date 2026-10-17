"""Test 3 (pre-registered): real job-end collapses with no Xid and normal temperature. Does a model invent a fault?

Usage: PYTHONPATH=src uv run python scripts/false_alarm_test.py [--dry]   Spend cap $0.80; stops on the first API failure.
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.gpu import POWER, SCHEMA, TEMP, UTIL  # noqa: E402
from clusterdoctor.hidden import FA_LABELS, FA_SPECS, FA_SYSTEM, HiddenTools, baseline_answer  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

CAP = 0.80
dry = "--dry" in sys.argv
FAULTS = {"thermal_throttling", "data_loader_bottleneck", "gpu_hardware_fault"}
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
data = json.loads(Path("data/real/job_end_cases.json").read_text())
cases = data["cases"]
cases = [c for pair in zip(cases[:16], cases[16:]) for c in pair] + cases[32:]          # interleave old and new windows
out = Path("bench/results_false_alarm.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": [], "excluded": []}
done = {r["id"] for r in state["rows"]} | {e["id"] for e in state["excluded"]}
chat = None if dry else nemotron_chat()
KEY = {"util": UTIL, "temp": TEMP, "power": POWER}
spent = sum(r["cost"] for r in state["rows"])


def build(case):
    s = Store(":memory:"); s.db.executescript(SCHEMA)
    t0 = min(m["t"][0] for m in case["metrics"].values())
    rows = [(ts - t0, case["node"], int(g), KEY[k], v, "real") for k, m in case["metrics"].items()
            for g, vals in m["v"].items() for ts, v in zip(m["t"], vals) if v is not None]
    s.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); s.db.commit()
    return s, case["time"] - t0


for case in cases:
    if case["id"] in done: continue
    store, anchor = build(case)
    tools = HiddenTools(store, case["node"], case["gpu_index"], (0, anchor - 300), (anchor - 300, anchor + 900))
    cw = tools.compare_windows(); tb, ti = cw["baseline"]["temp_c"], cw["incident"]["temp_c"]
    if ti is None or ti >= 70 or (tb is not None and ti - tb > 8):          # pre-registered: normal temperature only
        state["excluded"].append({"id": case["id"], "reason": f"temperature not normal (baseline {tb}, incident {ti})"}); continue
    if dry:
        print(case["id"], case["gpu"], cw["baseline"]["util_pct"], "->", cw["incident"]["util_pct"], "| temp", tb, "->", ti); continue
    if spent >= CAP:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: spend cap ${CAP} reached.")
    try:
        b = baseline_answer(chat, tools, FA_SYSTEM, FA_LABELS)
        inv = investigate(chat, tools, f"{case['node']} GPU {case['gpu_index']}: utilization collapse at the anchor time (telemetry is real)",
                          specs=FA_SPECS, system=FA_SYSTEM, max_steps=14)
    except Exception as e:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API call failed ({type(e).__name__}: {str(e)[:100]}). Saved.")
    d = inv.diagnosis
    row = {"id": case["id"], "gpu": case["gpu"], "baseline": {"root_cause": b["root_cause"], "confidence": b["confidence"]},
           "agent": {"root_cause": d["root_cause"], "confidence": d["confidence"], "tool_calls": len(inv.trace)},
           "cost": cost_usd(b["prompt_tokens"], b["completion_tokens"]) + cost_usd(inv.prompt_tokens, inv.completion_tokens)}
    spent += row["cost"]; state["rows"].append(row); out.write_text(json.dumps(state, indent=1))
    print(f"{case['id']} {case['gpu']:18} baseline={b['root_cause']:22}({b['confidence']:6}) agent={d['root_cause']:22}({d['confidence']:6}) spent ${spent:.2f}", flush=True)

out.write_text(json.dumps(state, indent=1))
if not dry:
    n = len(state["rows"]); print(f"\n=== Test 3 summary (design {design}) | windows run {n}, excluded for temperature {len(state['excluded'])} ===")
    for who in ("baseline", "agent"):
        c = Counter(r[who]["root_cause"] for r in state["rows"]); fa = sum(c[k] for k in FAULTS)
        print(f"{who:9} false alarms {fa}/{n} ({100*fa/max(n,1):.0f}%)  {dict(c)}")
    print(f"rule of three: if 0 false alarms, the 95% upper bound is about {300/max(n,1):.0f}%. spend ${spent:.2f}")
