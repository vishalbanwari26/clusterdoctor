"""Rebuild the dashboard replays with the fixed workflow (evidence pack, one strict call, claim check, escalate only if needed).

The earlier tool-agent investigations are kept in data/replays_agent/. Shares the Test 5 spend ledger (global cap $1.00; this script $0.40).
Usage: PYTHONPATH=src uv run python scripts/build_workflow_replays.py [id ...]"""
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

load_dotenv(".env")

from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.replay import run_live_workflow  # noqa: E402

SCRIPT_CAP, GLOBAL_CAP, HEADROOM = 0.40, 1.00, 0.08
DATA, OLD = Path("data/replays"), Path("data/replays_agent"); OLD.mkdir(exist_ok=True)
ledger_path = Path("bench/spend_test5.json"); ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"entries": []}
ids = sys.argv[1:] or ["prompt-bloat", "retry-storm", "overlap", "misleading-event", "provider-slowdown",
                       "real-xid94-a", "real-xid94-b", "gpu-thermal", "gpu-loader", "gpu-hardware"]
chat, verifier = nemotron_chat(), nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))
here = sum(e["usd"] for e in ledger["entries"] if e["script"] == "workflow_replays"); total = sum(e["usd"] for e in ledger["entries"])
for rid in ids:
    d = json.loads((DATA / f"{rid}.json").read_text())
    if d.get("investigation_kind") == "fixed workflow":
        print(f"{rid}: already rebuilt"); continue
    if here + HEADROOM > SCRIPT_CAP or total + HEADROOM > GLOBAL_CAP:
        sys.exit(f"STOP: cap (script ${here:.2f}/{SCRIPT_CAP}, all ${total:.2f}/{GLOBAL_CAP}) before {rid}")
    if not (OLD / f"{rid}.json").exists():
        shutil.copy(DATA / f"{rid}.json", OLD / f"{rid}.json")
    try:
        inv = run_live_workflow(rid, d, DATA, chat, verifier)
    except APIError as e:
        sys.exit(f"STOP: API error ({type(e).__name__}: {str(e)[:100]}).")
    d["investigation"], d["investigation_kind"] = inv, "fixed workflow"
    (DATA / f"{rid}.json").write_text(json.dumps(d))
    here += inv["cost_usd"]; total += inv["cost_usd"]
    ledger["entries"].append({"script": "workflow_replays", "usd": inv["cost_usd"]}); ledger_path.write_text(json.dumps(ledger))
    w, g = inv["workflow"], inv["diagnosis"]; truth = d["truth"]["root_cause"]
    print(f"{rid:18} -> {g['root_cause']:24}({g['confidence']:6}) truth={truth:24} escalated={w['escalated']!s:5} {w['reasons']} ${inv['cost_usd']:.3f} {inv['wall_s']:.0f}s | spent ${here:.2f}", flush=True)
print(f"done. workflow replays spend ${here:.2f}; Test 5 total ${total:.2f} of ${GLOBAL_CAP}")
