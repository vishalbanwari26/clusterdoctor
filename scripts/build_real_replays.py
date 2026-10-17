"""Build dashboard replays for the two real AcmeTrace Kalos incidents and run the agent on them.

Usage: PYTHONPATH=src uv run python scripts/build_real_replays.py [--dry]
Stops on the first API failure. Costs about $0.05 per incident.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor import snapshots  # noqa: E402
from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.fleet import detect_low_util, detect_xid_change  # noqa: E402
from clusterdoctor.gpu_tools import GpuTools  # noqa: E402
from clusterdoctor.real import load_event, load_slices  # noqa: E402
from clusterdoctor.replay import investigation_to_dict, run_real_gpu_investigation  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

dry = "--dry" in sys.argv
OUT = Path("data/replays"); OUT.mkdir(parents=True, exist_ok=True)
SLICES = load_slices()
ATTR = SLICES["attribution"]
SOURCE = ("REAL telemetry: AcmeTrace, Kalos cluster, Shanghai AI Laboratory (CC-BY-4.0). Subset and converted by this project. "
          "Node and GPU ids are the dataset's own.")
TITLES = {"A": ("real-xid94-a", "Real GPU: utilization collapses when a memory error hits"),
          "B": ("real-xid94-b", "Real GPU: a memory error with no visible symptoms")}
chat = None if dry else nemotron_chat()
verifier = None if dry else nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))

for ev, (rid, title) in TITLES.items():
    store = Store(":memory:")
    info = load_event(store, SLICES["events"][ev])
    node, gpu, onset, dur = info["node"], info["gpu"], info["onset"], info["duration"]
    baseline, incident = (0.0, onset - 600), (onset - 300, onset + 900)
    xid = [i for i in detect_xid_change(store, 0, dur + 1) if i.gpu == gpu]
    assert xid, "Xid watcher did not open an incident"
    t = GpuTools(store, node, gpu, baseline, incident).compare_windows()
    b, i = t["baseline"]["util_pct"], t["incident"]["util_pct"]
    summary = (f"{node} GPU {gpu}: driver reported Xid {xid[0].code}; utilization fell from {b:.0f}% to {i:.0f}%" if b is not None
               else f"{node} GPU {gpu}: driver reported Xid {xid[0].code}; no utilization baseline exists (data missing before the event)")
    flagged = [x for x in detect_low_util(store, baseline, onset - 300, dur) if x.node == node]
    print(f"[{rid}] {summary} | low-util watcher flags {len(flagged)} GPU(s) on this node")
    data = {"id": rid, "title": title, "domain": "gpu", "group": "Real GPU data (AcmeTrace Kalos)", "summary": summary,
            "source": SOURCE,
            "truth": {"root_cause": "gpu_hardware_fault", "real": True,
                      "fault": "Xid 94: contained memory error (NVIDIA Xid catalog)",
                      "note": "Reference label derived from the Xid code. It is not a human-verified diagnosis."},
            "chart": snapshots.fleet_chart(store, node, gpu, baseline, incident, onset, dur, simulated=False),
            "attribution": ATTR,
            "telemetry": {"real": True, "event": ev, "baseline": list(baseline), "incident": list(incident)},
            "investigation": None}
    if not dry:
        try:
            inv = run_real_gpu_investigation(chat, verifier, store, node, gpu, baseline, incident, summary)
        except Exception as e:                       # stop on API failure, do not retry
            sys.exit(f"STOP: API call failed ({type(e).__name__}). Nothing more was spent.")
        data["investigation"] = investigation_to_dict(inv)
        d = inv.diagnosis
        print(f"   -> {d['root_cause']} ({d['confidence']}) | ${data['investigation']['cost_usd']:.3f} | {data['investigation']['wall_s']:.0f}s")
        print("   tools:", [x["tool"] for x in inv.trace])
    (OUT / f"{rid}.json").write_text(json.dumps(data))
print("written:", [p.name for p in sorted(OUT.glob("real-*.json"))])
