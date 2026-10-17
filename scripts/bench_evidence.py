"""Test 5b + 5c (pre-registered): one call with the evidence pack + computed effect split and a strict JSON schema, 3 samples per case.

Pass 1 = sample 1 for all 24 evaluations (5b), passes 2-3 = samples 2 and 3 (5c). Cases ordered round-robin. Stops on the first API error.
Per-script cap $0.55; global Test 5 cap $1.00 via bench/spend_test5.json.
Usage: PYTHONPATH=src uv run python scripts/bench_evidence.py [--dry]
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError

load_dotenv(".env")

from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.bench import BASELINE_SYSTEM, _parse_json, cost_usd  # noqa: E402
from clusterdoctor.evidence import effect_split  # noqa: E402
from clusterdoctor.faults import HARD  # noqa: E402
from clusterdoctor.hybrid import evidence_pack  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import ROOT_CAUSES, Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

SCRIPT_CAP, GLOBAL_CAP, HEADROOM = 0.55, 1.00, 0.02
dry = "--dry" in sys.argv
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
ledger_path = Path("bench/spend_test5.json"); ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"entries": []}
out = Path("bench/results_evidence.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": {}}
manifest = json.loads(Path("bench/manifest.json").read_text())
SCHEMA = {"type": "json_schema", "json_schema": {"name": "diagnosis", "strict": True, "schema": {
    "type": "object", "properties": {"root_cause": {"type": "string", "enum": ROOT_CAUSES},
                                     "confidence": {"type": "string", "enum": ["high", "medium", "low"]}, "reasoning": {"type": "string"}},
    "required": ["root_cause", "confidence", "reasoning"], "additionalProperties": False}}}
SYSTEM = BASELINE_SYSTEM + ("\nThe tables include stratified median latency (baseline and incident side by side). Compare within a fixed stratum before blaming a factor."
                            "\nThe effect split fits latency on the factors that vary INSIDE the incident window. Prefer a factor whose variation inside the window moves latency. "
                            "A factor marked varies_in_incident_window=false changed but cannot be separated from other changes in this window. "
                            "If no factor varies and latency still rose, consider that the cause is outside the app's own requests.")
by_fault = defaultdict(list)
for cid, c in manifest.items():
    if c["fault"] in HARD:
        for ev in (True, False): by_fault[c["fault"]].append((cid, c, ev))
jobs = [j for i in range(6) for f in sorted(by_fault) for j in by_fault[f][i:i + 1]]
spent_here = sum(e["usd"] for e in ledger["entries"] if e["script"] == "evidence"); spent_all = sum(e["usd"] for e in ledger["entries"])
chat = None if dry else nemotron_chat()


def prompt_for(cid, case, ev):
    store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"], window_s=10, ratio=1.5, min_requests=3)
    tools = Tools(store, (case["t0"], case["t1"]), inc.window, include_events=ev)
    dump = {**evidence_pack(tools), "pack_effect_split": effect_split(tools)}
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Incident: {inc.summary()}\n\n{json.dumps(dump, default=str)}"}]


stop = False
for sample in (1, 2, 3):
    for cid, case, ev in jobs:
        key = f"{cid}|{ev}"; row = state["rows"].setdefault(key, {"case": cid, "events": ev, "truth": case["truth"], "fault": case["fault"], "samples": []})
        if len(row["samples"]) >= sample: continue
        msgs = prompt_for(cid, case, ev)
        if dry:
            print(cid, ev, "prompt ~", len(json.dumps(msgs)) // 4, "tokens"); continue
        if spent_here + HEADROOM > SCRIPT_CAP or spent_all + HEADROOM > GLOBAL_CAP:
            print(f"STOP: cap (script ${spent_here:.2f}/{SCRIPT_CAP}, all ${spent_all:.2f}/{GLOBAL_CAP}) before sample {sample}"); stop = True; break
        try:
            r = chat(msgs, [], response_format=SCHEMA)
        except APIError as e:
            out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API error ({type(e).__name__}: {str(e)[:100]}). Saved.")
        p = _parse_json(r.get("content") or "") or {}
        c = cost_usd(r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0)
        row["samples"].append({"root_cause": p.get("root_cause", "unparseable"), "confidence": p.get("confidence", "low"), "cost": c})
        ledger["entries"].append({"script": "evidence", "usd": c}); spent_here += c; spent_all += c
        ledger_path.write_text(json.dumps(ledger)); out.write_text(json.dumps(state, indent=1))
    if stop: break
    if not dry: print(f"pass {sample} done | script spend ${spent_here:.3f}", flush=True)

if not dry:
    rows = list(state["rows"].values()); n = len(rows)
    old = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_baseline_rich.json").read_text())}
    rep = lambda r: int(r["case"].rsplit("_", 1)[1])  # noqa: E731
    ok = lambda lab, r: lab == r["truth"]  # noqa: E731
    print(f"\n=== Test 5b: evidence arm, sample 1 (design {design}) ===")
    for name, sel in (("all 24", rows), ("dev (repeats 1-2)", [r for r in rows if rep(r) <= 2]), ("weak hold-out (repeat 3)", [r for r in rows if rep(r) == 3])):
        s1 = [r for r in sel if r["samples"]]
        if not s1: continue
        c = sum(ok(r["samples"][0]["root_cause"], r) for r in s1); wh = sum(not ok(r["samples"][0]["root_cause"], r) and r["samples"][0]["confidence"] == "high" for r in s1)
        oc = sum(old[(r["case"], r["events"])]["root_cause"] == r["truth"] for r in s1)
        owh = sum(old[(r["case"], r["events"])]["root_cause"] != r["truth"] and old[(r["case"], r["events"])]["confidence"] == "high" for r in s1)
        print(f"{name:26} n={len(s1)}: evidence arm {c} correct, {wh} wrong@high | stored one-shot+tables {oc} correct, {owh} wrong@high")
    full = [r for r in rows if len(r["samples"]) == 3]
    if full:
        print(f"\n=== Test 5c: majority of 3 samples, {len(full)} cases ===")
        from collections import Counter
        right = wh = abstain = 0; agree = Counter(); single = sum(ok(r["samples"][0]["root_cause"], r) for r in full)
        for r in full:
            labs = [s["root_cause"] for s in r["samples"]]; top, k = Counter(labs).most_common(1)[0]
            agree[k] += 1
            if k == 1: label, conf = "insufficient_evidence", "low"; abstain += 1
            else:
                sel = [s for s in r["samples"] if s["root_cause"] == top]
                conf = "high" if k == 3 and all(s["confidence"] in ("high", "medium") for s in sel) else "medium"; label = top
            right += ok(label, r); wh += (not ok(label, r)) and conf == "high" and label != "insufficient_evidence"
        cost = sum(s["cost"] for r in full for s in r["samples"]) / len(full)
        print(f"majority accuracy {right}/{len(full)} (single sample {single}/{len(full)}) | wrong@high after calibration {wh} | abstained (all differ) {abstain} | agreement 3/3: {agree[3]}, 2/3: {agree[2]}, none: {agree[1]} | cost per case ${cost:.4f}")
    print(f"spend this script ${spent_here:.3f}; Test 5 total ${spent_all:.3f} of ${GLOBAL_CAP}")
