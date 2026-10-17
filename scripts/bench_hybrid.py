"""Test 4 (pre-registered): hybrid workflow on the 24 hard Token Factory evaluations. Spend cap $0.60.

Usage: PYTHONPATH=src uv run python scripts/bench_hybrid.py [--dry]
Stops on the first API error (not on bugs in this code). Compares with the stored arms, which are not re-run.
"""
import hashlib
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

load_dotenv(".env")

from clusterdoctor.agent import SYSTEM_STRAT, investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.faults import HARD  # noqa: E402
from clusterdoctor.hybrid import evidence_pack, hybrid_investigate  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import TOOL_SPECS_STRAT, Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

CAP, HEADROOM = 0.60, 0.05
dry = "--dry" in sys.argv
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
manifest = json.loads(Path("bench/manifest.json").read_text())
out = Path("bench/results_hybrid.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": []}
done = {(r["case"], r["events"]) for r in state["rows"]}
by_fault = defaultdict(list)
for cid, c in manifest.items():
    if c["fault"] in HARD:
        for ev in (True, False): by_fault[c["fault"]].append((cid, c, ev))
jobs = [j for i in range(6) for f in sorted(by_fault) for j in by_fault[f][i:i + 1]]          # round-robin over the 4 fault types
chat = None if dry else nemotron_chat()
verifier = None if dry else nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))
spent = sum(r["cost"] for r in state["rows"])


def cost(tok, esc=None):
    p = tok["prompt"] + tok["verifier"]; c = tok["completion"]
    if esc: p += esc["prompt"] + esc["verifier"]; c += esc["completion"]
    return cost_usd(p, c)


for cid, case, ev in jobs:
    if (cid, ev) in done: continue
    store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"], window_s=10, ratio=1.5, min_requests=3)
    tools = Tools(store, (case["t0"], case["t1"]), inc.window, include_events=ev)
    if dry:
        toks = len(json.dumps(evidence_pack(tools), default=str)) // 4
        print(cid, ev, case["fault"], "| evidence pack ~", toks, "tokens"); continue
    if spent + HEADROOM > CAP:
        out.write_text(json.dumps(state, indent=1)); print(f"STOP: next case could pass the ${CAP} cap (spent ${spent:.2f}); {len(state['rows'])} cases run."); break
    t = time.time()
    try:
        esc = lambda: investigate(chat, tools, inc.summary(), specs=TOOL_SPECS_STRAT, system=SYSTEM_STRAT, verifier=verifier, required_tests=2)  # noqa: E731
        r = hybrid_investigate(chat, verifier, tools, inc.summary(), esc)
    except APIError as e:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API error ({type(e).__name__}: {str(e)[:100]}). Saved.")
    d = r["diagnosis"]; c = cost(r["tokens"], r.get("escalation_tokens"))
    row = {"case": cid, "events": ev, "truth": case["truth"], "fault": case["fault"], "first_pass": r["first_pass"],
           "root_cause": d["root_cause"], "confidence": d["confidence"], "escalated": r["escalated"], "reasons": r["reasons"],
           "calls": r["tokens"]["calls"], "cost": c, "latency_s": time.time() - t}
    spent += c; state["rows"].append(row); out.write_text(json.dumps(state, indent=1))
    print(f"{cid:20} ev={ev!s:5} truth={case['truth']:20} first={str((r['first_pass'] or {}).get('root_cause')):20} final={d['root_cause']:20}({str(d['confidence']):6}) esc={r['escalated']!s:5} {r['reasons']} ${c:.3f} spent ${spent:.2f}", flush=True)

if not dry:
    rows = state["rows"]; n = len(rows)
    stored_agent = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_strat.json").read_text())}
    stored_one = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_baseline_rich.json").read_text())}
    ok = lambda r: r["root_cause"] == r["truth"]  # noqa: E731
    wh = lambda r: not ok(r) and r["confidence"] == "high" and r["root_cause"] != "insufficient_evidence"  # noqa: E731
    k = lambda r: (r["case"], r["events"])  # noqa: E731
    print(f"\n=== Test 4 summary (design {design}) | cases run {n} of 24 | spend ${spent:.2f} ===")
    print(f"hybrid       : correct {sum(ok(r) for r in rows)}/{n}, wrong@high {sum(wh(r) for r in rows)}, mean ${statistics.mean(r['cost'] for r in rows):.4f}, {statistics.mean(r['latency_s'] for r in rows):.1f}s")
    print(f"same cases, stored agent arm   : correct {sum(stored_agent[k(r)]['root_cause'] == r['truth'] for r in rows)}/{n}")
    print(f"same cases, stored one-shot+tables: correct {sum(stored_one[k(r)]['root_cause'] == r['truth'] for r in rows)}/{n}")
    es = [r for r in rows if r["escalated"]]; ne = [r for r in rows if not r["escalated"]]
    print(f"escalated {len(es)}/{n} ({100*len(es)//max(n,1)}%): correct after escalation {sum(ok(r) for r in es)}/{len(es)} | not escalated: correct {sum(ok(r) for r in ne)}/{len(ne)}")
    print("escalation reasons:", dict(__import__('collections').Counter(x for r in es for x in r["reasons"])))
    fp = [r for r in rows if r["first_pass"]]
    print(f"first answer (before any revision or escalation) correct: {sum(r['first_pass']['root_cause'] == r['truth'] for r in fp)}/{len(fp)}")
