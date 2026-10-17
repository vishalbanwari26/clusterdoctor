"""Evaluate the agent and the single-pass baseline on stored benchmark cases.

Usage: PYTHONPATH=src uv run python scripts/bench_eval.py
Reads bench/manifest.json, writes bench/results.json, prints a summary table.
"""
import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.faults import HARD  # noqa: E402
from clusterdoctor.bench import baseline_diagnose, cost_usd  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

manifest = json.loads(Path("bench/manifest.json").read_text())
chat = nemotron_chat()


def evaluate(cid: str, case: dict, with_events: bool) -> dict:
    store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"],
                                  window_s=10, ratio=1.5, min_requests=3)
    row = {"case": cid, "fault": case["fault"], "truth": case["truth"], "events": with_events,
           "detected": inc is not None}
    if inc is None:
        return row
    row["detect_delay_s"] = round(inc.opened_at - case["t1"], 1)
    tools = Tools(store, (case["t0"], case["t1"]), inc.window, include_events=with_events)

    t = time.time()
    res = investigate(chat, tools, inc.summary())
    d = res.diagnosis
    row["agent"] = {
        "root_cause": d["root_cause"], "confidence": d["confidence"],
        "latency_s": round(time.time() - t, 1), "tool_calls": len(res.trace),
        "valid_citations": len(d["evidence"]), "dropped_citations": len(res.dropped_evidence),
        "tokens": res.prompt_tokens + res.completion_tokens,
        "cost_usd": cost_usd(res.prompt_tokens, res.completion_tokens),
    }
    b = baseline_diagnose(chat, Tools(store, (case["t0"], case["t1"]), inc.window, with_events), inc.summary())
    row["baseline"] = {**b, "tokens": b["prompt_tokens"] + b["completion_tokens"],
                       "cost_usd": cost_usd(b["prompt_tokens"], b["completion_tokens"])}
    return row


jobs = [(cid, c, ev) for cid, c in manifest.items() for ev in ((True, False) if c["fault"] != "healthy" else (True,))]
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(lambda j: evaluate(*j), jobs))
Path("bench/results.json").write_text(json.dumps(rows, indent=2))

# ---- summary ----------------------------------------------------------------
healthy = [r for r in rows if r["fault"] == "healthy"]
faulty = [r for r in rows if r["fault"] != "healthy"]
print(f"\nDetection: {sum(r['detected'] for r in faulty)}/{len(faulty)} incidents detected; "
      f"false alerts on healthy: {sum(r['detected'] for r in healthy)}/{len(healthy)}")
scored = [r for r in faulty if r["detected"]]


def summarize(label, subset):
    if not subset:
        return
    out = [f"{label:<34} n={len(subset):<3}"]
    for who in ("agent", "baseline"):
        ok = sum(r[who]["root_cause"] == r["truth"] for r in subset)
        wrong_hi = sum(r[who]["root_cause"] != r["truth"] and r[who]["confidence"] == "high" for r in subset)
        ab = sum(r[who]["root_cause"] == "insufficient_evidence" for r in subset)
        out.append(f"{who}: {ok}/{len(subset)} correct, {ab} abstained, {wrong_hi} wrong@high, "
                   f"{statistics.mean(r[who]['latency_s'] for r in subset):.1f}s, "
                   f"{statistics.mean(r[who]['tokens'] for r in subset):.0f} tok, "
                   f"${statistics.mean(r[who]['cost_usd'] for r in subset):.4f}")
    print("\n".join(out))


print()
summarize("EASY cases", [r for r in scored if r["fault"] not in HARD])
summarize("HARD cases", [r for r in scored if r["fault"] in HARD])
summarize("ALL (with+without deploy event)", scored)
summarize("with deploy event", [r for r in scored if r["events"]])
summarize("WITHOUT deploy event", [r for r in scored if not r["events"]])
by_fault = defaultdict(list)
for r in scored:
    by_fault[r["fault"]].append(r)
for f, rs in by_fault.items():
    summarize(f"  fault={f}", rs)
print(f"\nagent tool calls (mean): {statistics.mean(r['agent']['tool_calls'] for r in scored):.1f}; "
      f"dropped citations total: {sum(r['agent']['dropped_citations'] for r in scored)}")
