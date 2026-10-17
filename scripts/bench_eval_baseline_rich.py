"""Fair baseline: one call, no tools, given the same stratified tables the agent can query."""
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.bench import baseline_diagnose_rich, cost_usd  # noqa: E402
from clusterdoctor.faults import HARD  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

manifest = json.loads(Path("bench/manifest.json").read_text())
chat = nemotron_chat()


def evaluate(cid, case, ev):
    store = Store(case["db"])
    inc = detect_latency_incident(store, (case["t0"], case["t1"]), case["t1"], case["t2"],
                                  window_s=10, ratio=1.5, min_requests=3)
    b = baseline_diagnose_rich(chat, Tools(store, (case["t0"], case["t1"]), inc.window, ev), inc.summary())
    return {"case": cid, "fault": case["fault"], "truth": case["truth"], "events": ev, **b,
            "cost_usd": cost_usd(b["prompt_tokens"], b["completion_tokens"])}


jobs = [(cid, c, ev) for cid, c in manifest.items() if c["fault"] in HARD for ev in (True, False)]
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(lambda j: evaluate(*j), jobs))
Path("bench/results_baseline_rich.json").write_text(json.dumps(rows, indent=2))

simple = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_unverified.json").read_text()) if "baseline" in r}
strat = {(r["case"], r["events"]): r for r in json.loads(Path("bench/results_strat.json").read_text())}
print(f"{'fault':<20}{'n':>3} | {'baseline':>9} {'base+tables':>12} | {'agent (full)':>13}")
g = defaultdict(list)
for r in rows: g[r["fault"]].append(r)
g["ALL HARD"] = rows
for f, rs in g.items():
    s = sum(simple[(r["case"], r["events"])]["baseline"]["root_cause"] == r["truth"] for r in rs)
    b = sum(r["root_cause"] == r["truth"] for r in rs)
    a = sum(strat[(r["case"], r["events"])]["root_cause"] == r["truth"] for r in rs)
    print(f"{f:<20}{len(rs):>3} | {s:>6}/{len(rs):<2} {b:>9}/{len(rs):<2} | {a:>10}/{len(rs)}")
wh = lambda rs, k=lambda r: r: sum(k(r)["root_cause"] != r["truth"] and k(r)["confidence"] == "high" for r in rs)
print(f"\nwrong@high: base={wh(rows, lambda r: simple[(r['case'], r['events'])]['baseline'])}, "
      f"base+tables={wh(rows)}, agent={wh(rows, lambda r: strat[(r['case'], r['events'])])}")
print(f"base+tables mean: {statistics.mean(r['latency_s'] for r in rows):.1f}s, ${statistics.mean(r['cost_usd'] for r in rows):.4f}, "
      f"{statistics.mean(r['prompt_tokens'] + r['completion_tokens'] for r in rows):.0f} tok")
miss = [(r["case"], r["events"], r["truth"], r["root_cause"], r["confidence"]) for r in rows if r["root_cause"] != r["truth"]]
print("misses:", *miss, sep="\n  ")
