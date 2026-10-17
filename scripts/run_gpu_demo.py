"""Simulated GPU incident -> fleet watcher -> Ultra investigation.

Usage: PYTHONPATH=src uv run python scripts/run_gpu_demo.py thermal_throttle|dataloader_bottleneck
"""
import json
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.fleet import detect_low_util  # noqa: E402
from clusterdoctor.gpu import SCENARIOS, generate  # noqa: E402
from clusterdoctor.gpu_tools import GPU_SYSTEM, GPU_TOOL_SPECS, GpuTools  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

sc = SCENARIOS[sys.argv[1]]
store = Store(":memory:")
DUR, ONSET = 900, 300
generate(store, sc.name, t0=0, duration=DUR, onset=ONSET, seed=7)
incs = detect_low_util(store, (0, ONSET), ONSET, DUR)
print(f"scenario {sc.name} (truth: {sc.root_cause}); flagged: {[i.summary() for i in incs]}")
inc = incs[0]
res = investigate(nemotron_chat(), GpuTools(store, inc.node, inc.gpu, (0, ONSET), inc.window),
                  inc.summary() + " (telemetry is simulated)", specs=GPU_TOOL_SPECS, system=GPU_SYSTEM)
d = res.diagnosis
print("tool calls:", [f"{t['id']}:{t['tool']}" for t in res.trace])
print(json.dumps({k: d[k] for k in ("root_cause", "confidence", "uncertainties", "recommended_actions")}, indent=1))
for e in d["evidence"]:
    print(" -", e["tool_call_id"], e["claim"][:110])
print("dropped citations:", len(res.dropped_evidence), "| correct:", d["root_cause"] == sc.root_cause)
