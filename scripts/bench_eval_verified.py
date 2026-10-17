"""Rerun the HARD cases with the claim-verification pass; compare with bench/results_unverified.json."""
import json
import os
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.faults import HARD  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

manifest = json.loads(Path("bench/manifest.json").read_text())
chat = nemotron_chat()
verifier = nemotron_chat(os.environ.get("CD_VERIFIER_MODEL"))


def evaluate(cid, case, with_events):
    store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"],
                                  window_s=10, ratio=1.5, min_requests=3)
    tools = Tools(store, (case["t0"], case["t1"]), inc.window, include_events=with_events)
    t = time.time()
    res = investigate(chat, tools, inc.summary(), verifier=verifier)
    d = res.diagnosis
    return {"case": cid, "fault": case["fault"], "truth": case["truth"], "events": with_events,
            "root_cause": d["root_cause"], "confidence": d["confidence"],
            "latency_s": time.time() - t, "revisions": res.revisions,
            "claims": res.claims_total, "unsupported_first": res.claims_unsupported_first,
            "unsupported_final": res.claims_unsupported_final,
            "cost_usd": cost_usd(res.prompt_tokens + res.verifier_tokens, res.completion_tokens)}


jobs = [(cid, c, ev) for cid, c in manifest.items() if c["fault"] in HARD for ev in (True, False)]
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(lambda j: evaluate(*j), jobs))
Path("bench/results_verified.json").write_text(json.dumps(rows, indent=2))

old = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_unverified.json").read_text()) if "agent" in r}
def acc(rs, key): return sum(key(r) for r in rs)
print(f"\n{'fault':<20}{'n':>3} | {'no-verify':>10} {'verified':>9} | claims  unsupported first->final  | revisions")
groups = defaultdict(list)
for r in rows: groups[r["fault"]].append(r)
groups["ALL HARD"] = rows
for f, rs in groups.items():
    before = acc(rs, lambda r: old[(r["case"], r["events"])]["agent"]["root_cause"] == r["truth"])
    after = acc(rs, lambda r: r["root_cause"] == r["truth"])
    c, u1, u2 = (sum(r[k] for r in rs) for k in ("claims", "unsupported_first", "unsupported_final"))
    print(f"{f:<20}{len(rs):>3} | {before:>7}/{len(rs):<2}{after:>6}/{len(rs):<2}| {c:>5}   {u1:>3} ({u1/c:.0%}) -> {u2:>3} ({u2/c:.0%})"
          f"   | {sum(r['revisions'] for r in rs)}")
print(f"\nwrong@high after verification: {acc(rows, lambda r: r['root_cause'] != r['truth'] and r['confidence'] == 'high')} "
      f"(before: {acc(rows, lambda r: old[(r['case'], r['events'])]['agent']['root_cause'] != r['truth'] and old[(r['case'], r['events'])]['agent']['confidence'] == 'high')})")
print(f"mean latency {statistics.mean(r['latency_s'] for r in rows):.1f}s, mean cost ${statistics.mean(r['cost_usd'] for r in rows):.4f}")
