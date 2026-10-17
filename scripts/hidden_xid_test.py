"""Run the baseline and the agent on every window with the Xid series hidden. Hard API spend cap; stops on API failure.

Usage: PYTHONPATH=src uv run python scripts/hidden_xid_test.py [--dry]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.gpu import POWER, SCHEMA, TEMP, UTIL  # noqa: E402
from clusterdoctor.hidden import HIDDEN_SPECS, SYSTEM, HiddenTools, baseline_answer  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

CAP_USD = 1.50
dry = "--dry" in sys.argv
data = json.loads(Path("data/real/hidden_xid_cases.json").read_text())
chat = None if dry else nemotron_chat()
KEY = {"util": UTIL, "temp": TEMP, "power": POWER}
out_path = Path("bench/results_hidden_xid.json")
results = json.loads(out_path.read_text()) if out_path.exists() else {}
spent = sum(r["baseline"]["cost_usd"] + r["agent"]["cost_usd"] for r in results.values())


def build(case):
    s = Store(":memory:"); s.db.executescript(SCHEMA)
    t0 = min(m["t"][0] for m in case["metrics"].values())
    rows = [(ts - t0, case["node"], int(g), KEY[k], v, "real") for k, m in case["metrics"].items()
            for g, vals in m["v"].items() for ts, v in zip(m["t"], vals) if v is not None]
    s.db.executemany("INSERT INTO gpu_metrics VALUES (?,?,?,?,?,?)", rows); s.db.commit()
    anchor = case["time"] - t0
    return s, anchor


for case in data["cases"]:
    if case["id"] in results:
        continue
    store, anchor = build(case)
    tools = HiddenTools(store, case["node"], case["gpu_index"], (0, anchor - 300), (anchor - 300, anchor + 900))
    truth = case["kind"] != "N_collapse"
    if dry:
        print(case["id"], case["kind"], "truth driver_error =", truth, tools.compare_windows()["incident"]); continue
    if spent >= CAP_USD:
        sys.exit(f"STOP: spend cap ${CAP_USD} reached (${spent:.2f}).")
    try:
        b = baseline_answer(chat, tools)
        b["cost_usd"] = cost_usd(b["prompt_tokens"], b["completion_tokens"])
        inv = investigate(chat, tools, f"{case['node']} GPU {case['gpu_index']}: event at the anchor time (telemetry is real)",
                          specs=HIDDEN_SPECS, system=SYSTEM)
    except Exception as e:
        sys.exit(f"STOP: API call failed ({type(e).__name__}). Results so far are saved.")
    d = inv.diagnosis
    a = {"root_cause": d["root_cause"], "confidence": d["confidence"], "tool_calls": len(inv.trace),
         "cost_usd": cost_usd(inv.prompt_tokens, inv.completion_tokens)}
    results[case["id"]] = {"kind": case["kind"], "truth_driver_error": truth, "xid_code": case["xid_code"], "baseline": b, "agent": a}
    spent += b["cost_usd"] + a["cost_usd"]
    out_path.write_text(json.dumps(results, indent=1))
    print(f"{case['id']} {case['kind']:10} truth={'ERR' if truth else 'ok '} | baseline {b['root_cause']:22} ({b['confidence']}) | agent {a['root_cause']:22} ({a['confidence']}) | spent ${spent:.2f}", flush=True)

if not dry:
    print("\n=== summary (positives = driver error; N = normal job end; chance on positives vs N is 50%) ===")
    for who in ("baseline", "agent"):
        print(f"\n{who}:")
        for kind in ("P_collapse", "P_silent", "N_collapse"):
            rs = [r for r in results.values() if r["kind"] == kind]
            if not rs: continue
            c = defaultdict(int)
            for r in rs: c[r[who]["root_cause"]] += 1
            right = c["driver_error_reported"] if kind != "N_collapse" else c["no_driver_error"]
            print(f"  {kind:11} n={len(rs):2d}  right={right}  said driver_error={c['driver_error_reported']}  said no_error={c['no_driver_error']}  abstained={c['insufficient_evidence']}")
    print(f"\ntotal spend ${spent:.2f}")
