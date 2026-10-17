"""Large-fleet benchmark: 64 simulated GPUs, 3 real faults + 2 decoys, agent vs budgeted one-shot dump.

Usage: PYTHONPATH=src uv run python scripts/bench_fleet.py [--dry] [reps]
--dry: generate + detect + build dumps only (no API calls, no cost).
"""
import json
import sys
import time

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.fleet import detect_low_util  # noqa: E402
from clusterdoctor.fleet_bench import fleet_baseline, fleet_dump  # noqa: E402
from clusterdoctor.gpu import SCENARIOS, generate_fleet  # noqa: E402
from clusterdoctor.gpu_tools import GPU_SYSTEM, GPU_TOOL_SPECS, GpuTools  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

dry = "--dry" in sys.argv
reps = int(next((a for a in sys.argv[1:] if a.isdigit()), 3))
ONSET, DUR = 7200, 12000
chat = None if dry else nemotron_chat()
rows = []

for seed in range(1, reps + 1):
    faults = {("node-02", 5): "thermal_throttle", ("node-05", 1): "dataloader_bottleneck",
              ("node-07", 6): "gpu_hardware_fault", ("node-03", 2): "transient_dip", ("node-04", 7): "idle"}
    store = Store(":memory:")
    t = time.time()
    generate_fleet(store, faults, duration=DUR, onset=ONSET, seed=seed)
    n_rows = store.db.execute("SELECT COUNT(*) c FROM gpu_metrics").fetchone()["c"]
    incs = detect_low_util(store, (0, ONSET), ONSET, DUR)
    flagged = {(i.node, i.gpu) for i in incs}
    truth_gpus = {k for k, v in faults.items() if SCENARIOS[v].root_cause != "none"}
    print(f"[seed {seed}] {n_rows} samples ({time.time() - t:.0f}s); flagged={sorted(flagged)}; "
          f"missed={sorted(truth_gpus - flagged)}; false_alerts={sorted(flagged - truth_gpus)}", flush=True)
    for inc in incs:
        key = (inc.node, inc.gpu)
        if key not in truth_gpus:
            continue
        truth = SCENARIOS[faults[key]].root_cause
        dump_chars = len(json.dumps(fleet_dump(store, inc.node, inc.gpu, (0, ONSET), inc.window)))
        row = {"seed": seed, "gpu": f"{key[0]}/{key[1]}", "truth": truth, "dump_chars": dump_chars,
               "raw_samples": n_rows}
        if not dry:
            t = time.time()
            res = investigate(chat, GpuTools(store, inc.node, inc.gpu, (0, ONSET), inc.window),
                              inc.summary() + " (telemetry is simulated)", specs=GPU_TOOL_SPECS, system=GPU_SYSTEM)
            row["agent"] = {"root_cause": res.diagnosis["root_cause"], "confidence": res.diagnosis["confidence"],
                            "latency_s": time.time() - t, "tool_calls": len(res.trace),
                            "cost_usd": cost_usd(res.prompt_tokens, res.completion_tokens)}
            b = fleet_baseline(chat, store, inc.node, inc.gpu, (0, ONSET), inc.window, inc.summary())
            row["baseline"] = {**b, "cost_usd": cost_usd(b["prompt_tokens"], b["completion_tokens"])}
        rows.append(row)

print(f"\ndump size: ~{rows[0]['dump_chars']//4} tokens vs {rows[0]['raw_samples']} raw samples")
if not dry:
    json.dump(rows, open("bench/results_fleet.json", "w"), indent=2)
    for who in ("agent", "baseline"):
        ok = sum(r[who]["root_cause"] == r["truth"] for r in rows)
        wh = sum(r[who]["root_cause"] != r["truth"] and r[who]["confidence"] == "high" for r in rows)
        print(f"{who:9}: {ok}/{len(rows)} correct, {wh} wrong@high, "
              f"${sum(r[who]['cost_usd'] for r in rows) / len(rows):.4f}/incident, "
              f"{sum(r[who]['latency_s'] for r in rows) / len(rows):.1f}s")
    for kind in ("thermal_throttling", "data_loader_bottleneck", "gpu_hardware_fault"):
        rs = [r for r in rows if r["truth"] == kind]
        print(f"  {kind:<24} agent {sum(r['agent']['root_cause'] == kind for r in rs)}/{len(rs)}  "
              f"baseline {sum(r['baseline']['root_cause'] == kind for r in rs)}/{len(rs)}")
