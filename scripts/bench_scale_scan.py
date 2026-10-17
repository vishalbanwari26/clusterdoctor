"""Test 5d (pre-registered): one-shot dump + automatic dimension scan + strict schema on the fleet-scale cases.
Dev = the v2 fleet; held-out = the v3 fleet (new seed, new hot slot, new placements). Stops on the first API error. Cap $0.30 for this script.
Usage: PYTHONPATH=src uv run python scripts/bench_scale_scan.py [dev|heldout|both] [--dry]"""
import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

load_dotenv(".env")

from clusterdoctor import bigfleet as B  # noqa: E402
from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.bench import _parse_json, cost_usd  # noqa: E402
from clusterdoctor.evidence import dimension_scan  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

SCRIPT_CAP, GLOBAL_CAP, HEADROOM = 0.45, 1.00, 0.02   # per-script cap raised after my token-cap error; the global $1.00 cap is the approved one
dry = "--dry" in sys.argv
which = next((a for a in sys.argv[1:] if a in ("dev", "heldout", "both")), "both")
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
ledger_path = Path("bench/spend_test5.json"); ledger = json.loads(ledger_path.read_text())
out = Path("bench/results_scale_scan.json"); state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": []}
done = {(r["fleet"], r["id"]) for r in state["rows"]}
FLEETS = {"dev": ("data/raw/bigfleet_v2", B.plan_v2()), "heldout": ("data/raw/bigfleet_v3", B.plan_v2(seed=77, slot=6))}
SCHEMA = {"type": "json_schema", "json_schema": {"name": "diagnosis", "strict": True, "schema": {
    "type": "object", "properties": {"root_cause": {"type": "string", "enum": B.LABELS}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                     "reasoning": {"type": "string"}}, "required": ["root_cause", "confidence", "reasoning"], "additionalProperties": False}}}
SYSTEM = (B.SYSTEM.split("Use the tools")[0] + "The dump has a dimension scan: for each metric and each grouping (node, rack, slot index) it lists the groups whose "
          "incident mean is most unusual among groups (z in standard deviations; outlier=true when z is 4 or more). A group outlier that contains the flagged GPU "
          "points at a cause shared by that group. Answer with ONLY JSON.")
spent_here = sum(e["usd"] for e in ledger["entries"] if e["script"] == "scale_scan"); spent_all = sum(e["usd"] for e in ledger["entries"])
chat = None if dry else nemotron_chat()
for fleet in (["dev", "heldout"] if which == "both" else [which]):
    path, cases = FLEETS[fleet]
    if not (Path(path) / "READY").exists(): sys.exit(f"{fleet} fleet not ready")
    store = Store(Path(path) / "fleet.db")
    for c in cases:
        if (fleet, c["id"]) in done: continue
        tools = B.BigFleetTools(store, c["node"], c["gpu"]); cw = tools.compare_windows()
        summary = f"{c['node']} GPU {c['gpu']}: utilization fell from {cw['baseline']['util']:.0f}% to {cw['incident']['util']:.0f}% (simulated fleet)"
        d = {**B.dump(store, c["node"], c["gpu"]), "dimension_scan": dimension_scan(tools)}
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Incident: {summary}\n\n{json.dumps(d, separators=(',', ':'))}"}]
        if dry:
            sc = [x for x in d["dimension_scan"] if x["outlier"]][:3]
            print(fleet, c["id"], c["family"], "| prompt ~", len(json.dumps(msgs)) // 4, "tokens | outliers:", [(x["metric"], x["dimension"], x["group"], x["z"]) for x in sc]); continue
        if spent_here + HEADROOM > SCRIPT_CAP or spent_all + HEADROOM > GLOBAL_CAP:
            out.write_text(json.dumps(state, indent=1)); print("STOP: cap reached"); sys.exit(0)
        cst, p, tries = 0.0, {}, 0
        for tries in (1, 2):           # strict-schema decoding occasionally degenerates into whitespace: capped at 400 tokens, one retry
            try:
                r = chat(msgs, [], response_format=SCHEMA, max_tokens=2500)
            except APIError as e:
                out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API error ({type(e).__name__}: {str(e)[:100]}). Saved.")
            cst += cost_usd(r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0)
            p = _parse_json(r.get("content") or "") or {}
            if p.get("root_cause") in B.LABELS: break
        state["rows"].append({"fleet": fleet, "id": c["id"], "family": c["family"], "truth": c["truth"], "root_cause": p.get("root_cause", "unparseable"),
                              "confidence": p.get("confidence", "low"), "cost": cst, "attempts": tries})
        ledger["entries"].append({"script": "scale_scan", "usd": cst}); spent_here += cst; spent_all += cst
        ledger_path.write_text(json.dumps(ledger)); out.write_text(json.dumps(state, indent=1))
        print(f"{fleet:7} {c['id']} {c['family']} truth={c['truth']:22} -> {str(p.get('root_cause')):22}({p.get('confidence')}) tries={tries} spent ${spent_here:.3f}", flush=True)
if not dry:
    print(f"\n=== Test 5d summary (design {design}) ===")
    for fleet in ("dev", "heldout"):
        rs = [r for r in state["rows"] if r["fleet"] == fleet]
        if not rs: continue
        fam = {f: (sum(r["root_cause"] == r["truth"] for r in rs if r["family"] == f), sum(1 for r in rs if r["family"] == f)) for f in "ABCD"}
        print(f"{fleet:8} pooled {sum(r['root_cause'] == r['truth'] for r in rs)}/{len(rs)} | " + "  ".join(f"{f}:{a}/{b}" for f, (a, b) in fam.items()))
    print("stored arms on the dev fleet (v2): one-shot without the scan 8/14 (C 0/5); agent 1/14")
    print(f"spend this script ${spent_here:.3f}; Test 5 total ${spent_all:.3f} of $1.00")
