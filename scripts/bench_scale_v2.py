"""Test 1 v2 (pre-registered in docs/preregistered-tests.md): clean slot family, label and citation retries.

Usage: PYTHONPATH=src uv run python scripts/bench_scale_v2.py [--dry]   Spend cap $2.00; stops on the first API failure.
"""
import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor import bigfleet as B  # noqa: E402
from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

CAP = 2.00
dry = "--dry" in sys.argv
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
out = Path("bench/results_scale_v2.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": []}
done = {r["id"] for r in state["rows"]}
cases = B.plan_v2()
by_fam = {f: [c for c in cases if c["family"] == f] for f in "ABCD"}
cases = [by_fam[f][i] for i in range(5) for f in "ABCD" if i < len(by_fam[f])]            # round-robin
d = Path("data/raw/bigfleet_v2")
if not (d / "READY").exists():
    sys.exit("fleet v2 not ready yet (scripts/gen_bigfleet_v2.py)")
store = Store(d / "fleet.db")
chat = None if dry else nemotron_chat()
spent = sum(r.get("cost", 0) for r in state["rows"])
for c in cases:
    if c["id"] in done: continue
    tools = B.BigFleetTools(store, c["node"], c["gpu"]); cw = tools.compare_windows()
    summary = f"{c['node']} GPU {c['gpu']}: utilization fell from {cw['baseline']['util']:.0f}% to {cw['incident']['util']:.0f}% (simulated fleet)"
    if dry:
        gi = tools.group_stats("temp", "gpu_index", "incident")[:3]
        print(c["id"], c["family"], summary, "| top slots:", [(g["group"], g["vs_fleet"]) for g in gi]); continue
    if spent >= CAP:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: spend cap ${CAP} reached.")
    try:
        inv = investigate(chat, tools, summary, specs=B.SCALE_SPECS, system=B.SYSTEM, max_steps=14)
        b = B.baseline_answer(chat, store, c["node"], c["gpu"], summary)
    except Exception as e:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API call failed ({type(e).__name__}: {str(e)[:100]}). Saved.")
    dg = inv.diagnosis
    row = {"id": c["id"], "family": c["family"], "truth": c["truth"],
           "agent": {"root_cause": dg["root_cause"], "confidence": dg["confidence"], "tool_calls": len(inv.trace), "turns": inv.steps,
                     "original_root_cause": str(inv.original_root_cause)[:80], "label_retries": inv.label_retries,
                     "citation_retries": inv.citation_retries, "schema_retries": inv.schema_retries,
                     "used_group_stats": [t["args"].get("group_by") for t in inv.trace if t["tool"] == "group_stats"]},
           "baseline": {"root_cause": b["root_cause"], "confidence": b["confidence"], "dump_tokens_est": b["dump_tokens_est"]},
           "cost": cost_usd(inv.prompt_tokens, inv.completion_tokens) + cost_usd(b["prompt_tokens"], b["completion_tokens"])}
    spent += row["cost"]; state["rows"].append(row); out.write_text(json.dumps(state, indent=1))
    print(f"{c['id']} {c['family']} truth={c['truth']:22} agent={dg['root_cause']:22}({dg['confidence']:6}) retries(l{inv.label_retries}/c{inv.citation_retries}/s{inv.schema_retries}) "
          f"base={b['root_cause']:22}({b['confidence']:6}) spent ${spent:.2f}", flush=True)
if not dry:
    rs = state["rows"]; print(f"\n=== Test 1 v2 summary (design {design}) ===")
    for fam in "ABCD":
        f = [r for r in rs if r["family"] == fam]
        if f:
            ca = sum(r["agent"]["root_cause"] == r["truth"] for r in f); cb = sum(r["baseline"]["root_cause"] == r["truth"] for r in f)
            ab = sum(r["agent"]["root_cause"] == "insufficient_evidence" for r in f)
            print(f"family {fam} n={len(f)}: agent {ca} correct ({ab} abstained) | one-shot {cb} correct")
    ca = sum(r["agent"]["root_cause"] == r["truth"] for r in rs); cb = sum(r["baseline"]["root_cause"] == r["truth"] for r in rs)
    rescued = sum(1 for r in rs if r["agent"]["label_retries"] or r["agent"]["citation_retries"])
    print(f"POOLED agent {ca}/{len(rs)} | one-shot {cb}/{len(rs)} | answers needing a retry: {rescued} | spend ${spent:.2f}")
