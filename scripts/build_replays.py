"""Build dashboard replays: chart snapshots + a stored investigation per incident.

Usage: PYTHONPATH=src uv run python scripts/build_replays.py [--dry] [id ...]
--dry: snapshots only, no API calls (investigation left null).
Needs bench/cases/*.db (run bench_generate.py first). Live mode costs about $0.04 per incident.
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor import snapshots  # noqa: E402
from clusterdoctor.agent import SYSTEM_STRAT, investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.fleet import detect_low_util  # noqa: E402
from clusterdoctor.gpu import SCENARIOS, generate_fleet  # noqa: E402
from clusterdoctor.gpu_tools import GPU_SYSTEM, GPU_TOOL_SPECS, GpuTools  # noqa: E402
from clusterdoctor.replay import investigation_to_dict, run_app_investigation, run_gpu_investigation  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
dry = "--dry" in sys.argv
out = Path("data/replays"); out.mkdir(parents=True, exist_ok=True)
manifest = json.loads(Path("bench/manifest.json").read_text())

APP = {  # id -> (case, title)
    "prompt-bloat": ("prompt_bloat_1", "Prompt bloat after a retrieval change"),
    "retry-storm": ("retry_storm_1", "Retry policy change, intermittent 429s"),
    "overlap": ("overlap_2", "Two changes shipped together"),
    "misleading-event": ("misleading_event_1", "Deploy event points at the wrong change"),
    "provider-slowdown": ("provider_slowdown_1", "Latency up, nothing changed on our side"),
}
GPU = {  # id -> (node, gpu, scenario)
    "gpu-thermal": ("node-02", 5, "thermal_throttle"),
    "gpu-loader": ("node-05", 1, "dataloader_bottleneck"),
    "gpu-hardware": ("node-07", 6, "gpu_hardware_fault"),
}
FLEET_FAULTS = {("node-02", 5): "thermal_throttle", ("node-05", 1): "dataloader_bottleneck",
                ("node-07", 6): "gpu_hardware_fault", ("node-03", 2): "transient_dip", ("node-04", 7): "idle"}
ONSET, DUR, SEED = 7200, 12000, 1
want = lambda i: not args or i in args  # noqa: E731
chat = None if dry else nemotron_chat()
verifier = None if dry else nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))

for rid, (cid, title) in APP.items():
    if not want(rid):
        continue
    case = manifest[cid]; store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"],
                                  window_s=10, ratio=1.5, min_requests=3)
    data = {"id": rid, "title": title, "domain": "inference", "summary": inc.summary(),
            "source": "Live calls to Token Factory (Nemotron-3.5 Lightning)"
                      + (" with injected faults" if case["fault"] in ("retry_storm", "overlap", "provider_slowdown") else ""),
            "truth": {"root_cause": case["truth"], "fault": case["fault"]},
            "chart": snapshots.latency_chart(store, case["t0"], case["t1"], case["t2"]),
            "glance": snapshots.at_a_glance(store, (case["t0"], case["t1"]), inc.window),
            "telemetry": {"baseline": [case["t0"], case["t1"]], "incident": list(inc.window), "t0": case["t0"], "t2": case["t2"]},
            "investigation": None}
    (out / f"{rid}.telemetry.json").write_text(json.dumps(snapshots.export_requests(store, case["t0"], case["t2"])))
    if not dry:
        print(f"[{rid}] investigating...", flush=True)
        inv = run_app_investigation(chat, verifier, store, (case["t0"], case["t1"]), inc.window, inc.summary())
        data["investigation"] = investigation_to_dict(inv)
        print("   ->", inv.diagnosis["root_cause"], "truth:", case["truth"], flush=True)
    (out / f"{rid}.json").write_text(json.dumps(data))

if any(want(i) for i in GPU):
    store = Store(":memory:")
    generate_fleet(store, FLEET_FAULTS, duration=DUR, onset=ONSET, seed=SEED)
    incs = {(i.node, i.gpu): i for i in detect_low_util(store, (0, ONSET), ONSET, DUR)}
    for rid, (node, gpu, sc) in GPU.items():
        if not want(rid):
            continue
        inc = incs[(node, gpu)]
        data = {"id": rid, "title": {"gpu-thermal": "One GPU slows down, temperature climbing",
                                     "gpu-loader": "Utilization drops, GPU stays cool",
                                     "gpu-hardware": "Utilization collapses on one GPU"}[rid],
                "domain": "gpu", "summary": inc.summary(),
                "source": "SIMULATED fleet (64 GPUs). No real GPU behind this data.",
                "truth": {"root_cause": SCENARIOS[sc].root_cause, "fault": sc},
                "chart": snapshots.fleet_chart(store, node, gpu, (0, ONSET), inc.window, ONSET, DUR),
                "telemetry": {"seed": SEED, "onset": ONSET, "duration": DUR, "node": node, "gpu": gpu,
                              "faults": [[k[0], k[1], v] for k, v in FLEET_FAULTS.items()],
                              "baseline": [0, ONSET], "incident": list(inc.window)},
                "investigation": None}
        if not dry:
            print(f"[{rid}] investigating...", flush=True)
            inv = run_gpu_investigation(chat, verifier, store, node, gpu, (0, ONSET), inc.window, inc.summary())
            data["investigation"] = investigation_to_dict(inv)
            print("   ->", inv.diagnosis["root_cause"], "truth:", SCENARIOS[sc].root_cause, flush=True)
        (out / f"{rid}.json").write_text(json.dumps(data))
print("written:", sorted(p.name for p in out.glob("*.json") if "telemetry" not in p.name))
