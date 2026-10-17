"""Test 2 (pre-registered, docs/preregistered-tests.md): simulated fleet, 4 seeds x 3 difficulty levels, agent vs one-shot dump.

Usage: PYTHONPATH=src uv run python scripts/bench_sim_levels.py [--dry]
Spend cap $1.00. Stops on the first API failure. Results are saved after every incident.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.fleet import detect_low_util, detect_xid_change  # noqa: E402
from clusterdoctor.fleet_bench import fleet_baseline  # noqa: E402
from clusterdoctor.gpu import SCENARIOS, generate_fleet  # noqa: E402
from clusterdoctor.gpu_tools import GPU_SYSTEM, GPU_TOOL_SPECS, GpuTools  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

CAP = 1.00
dry = "--dry" in sys.argv
LEVELS = {"easy": (1.0, 1.0, 0.0), "medium": (0.6, 1.5, 0.05), "hard": (0.35, 2.0, 0.15)}
SEEDS = (101, 102, 103, 104)
ONSET, DUR = 7200, 12000
FAULTS = {("node-02", 5): "thermal_throttle", ("node-05", 1): "dataloader_bottleneck", ("node-07", 6): "gpu_hardware_fault",
          ("node-03", 2): "transient_dip", ("node-04", 7): "idle"}
REAL = {k: v for k, v in FAULTS.items() if SCENARIOS[v].root_cause != "none"}
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
out = Path("bench/results_sim_levels.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": []}
done = {(r["level"], r["seed"], r["gpu"]) for r in state["rows"]}
chat = None if dry else nemotron_chat()
spent = sum(r.get("cost", 0) for r in state["rows"])

for seed in SEEDS:
    for level, (strength, noise, missing) in LEVELS.items():
        store = Store(":memory:")
        generate_fleet(store, FAULTS, duration=DUR, onset=ONSET, seed=seed, strength=strength, noise=noise, missing=missing)
        util = {(i.node, i.gpu): i for i in detect_low_util(store, (0, ONSET), ONSET, DUR)}
        xid = {(i.node, i.gpu): i for i in detect_xid_change(store, 0, DUR + 1)}
        flagged_false = sorted(set(util) | set(xid) - set(REAL))
        for key, scen in REAL.items():
            tag = (level, seed, f"{key[0]}/{key[1]}")
            if tag in done:
                continue
            truth = SCENARIOS[scen].root_cause
            if key in util:
                inc = util[key]; window, summary = inc.window, inc.summary()
            elif key in xid:
                x = xid[key]; window, summary = (x.opened_at - 240, x.opened_at + 120), x.summary()
            else:
                state["rows"].append({"level": level, "seed": seed, "gpu": tag[2], "truth": truth, "detected": False})
                continue
            row = {"level": level, "seed": seed, "gpu": tag[2], "truth": truth, "detected": True,
                   "false_alerts_in_fleet": len([k for k in flagged_false if k in {(n, g) for (n, g) in FAULTS} and k not in REAL])}
            if dry:
                print(row); continue
            if spent >= CAP:
                out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: spend cap ${CAP} reached.")
            try:
                inv = investigate(chat, GpuTools(store, key[0], key[1], (0, ONSET), window), summary + " (telemetry is simulated)",
                                  specs=GPU_TOOL_SPECS, system=GPU_SYSTEM)
                b = fleet_baseline(chat, store, key[0], key[1], (0, ONSET), window, summary)
            except Exception as e:
                out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API call failed ({type(e).__name__}). Saved.")
            d = inv.diagnosis
            row["agent"] = {"root_cause": d["root_cause"], "confidence": d["confidence"], "tool_calls": len(inv.trace)}
            row["baseline"] = {"root_cause": b["root_cause"], "confidence": b["confidence"]}
            row["cost"] = cost_usd(inv.prompt_tokens, inv.completion_tokens) + cost_usd(b["prompt_tokens"], b["completion_tokens"])
            spent += row["cost"]; state["rows"].append(row)
            out.write_text(json.dumps(state, indent=1))
            print(f"{level:6} s{seed} {tag[2]:12} truth={truth:24} agent={d['root_cause']:24}({d['confidence']:6}) base={b['root_cause']:24}({b['confidence']:6}) spent ${spent:.2f}", flush=True)

if not dry:
    print(f"\n=== Test 2 summary (design {design}) ===")
    for level in LEVELS:
        rs = [r for r in state["rows"] if r["level"] == level]
        det = [r for r in rs if r["detected"]]
        c = lambda who: sum(r[who]["root_cause"] == r["truth"] for r in det)
        wh = lambda who: sum(r[who]["root_cause"] != r["truth"] and r[who]["confidence"] == "high" for r in det)
        print(f"{level:6} incidents={len(rs)} detected={len(det)} | agent {c('agent')}/{len(det)} (wrong@high {wh('agent')}) | one-shot {c('baseline')}/{len(det)} (wrong@high {wh('baseline')})")
    print(f"spend ${spent:.2f}")
