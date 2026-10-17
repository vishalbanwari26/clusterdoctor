"""Test 1 (pre-registered, docs/preregistered-tests.md): 2,048-GPU simulated fleet, 20 cases, agent vs one-shot 12k-token dump.

Usage: PYTHONPATH=src uv run python scripts/bench_scale.py [--dry]   Spend cap $1.20; stops on the first API failure.
"""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor import bigfleet as B  # noqa: E402
from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.bench import cost_usd  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

CAP = 1.60            # raised from the pre-registered 1.20: the agent cost $0.08 per case, see Deviations in the design doc
dry = "--dry" in sys.argv
design = hashlib.sha256(Path("docs/preregistered-tests.md").read_bytes()).hexdigest()[:16]
out = Path("bench/results_scale.json")
state = json.loads(out.read_text()) if out.exists() else {"design_sha256": design, "rows": []}
done = {r["id"] for r in state["rows"]}
cases = B.plan(0)
by_fam = {f: [c for c in cases if c['family'] == f] for f in 'ABCD'}
cases = [by_fam[f][i] for i in range(5) for f in 'ABCD']        # round-robin so a spend cap cannot truncate one family
t0 = time.time()
FLEET = Path("data/raw/bigfleet"); FLEET.mkdir(parents=True, exist_ok=True)
db, marker = FLEET / "fleet.db", FLEET / "READY"
if not marker.exists():                                  # generate once, reuse afterwards (about 10+ minutes of pure Python)
    db.unlink(missing_ok=True)
    store = Store(db); B.generate(store, cases); store.db.execute("CREATE INDEX IF NOT EXISTS idx_m_ts ON gpu_metrics(metric, ts)")
    store.db.commit(); marker.write_text("ok")
else:
    store = Store(db)
n = store.db.execute("SELECT COUNT(*) c FROM gpu_metrics").fetchone()["c"]
print(f"fleet ready: {n:,} samples ({time.time()-t0:.0f} s)", flush=True)
chat = None if dry else nemotron_chat()
spent = sum(r.get("cost", 0) for r in state["rows"])
for c in cases:
    if c["id"] in done: continue
    tools = B.BigFleetTools(store, c["node"], c["gpu"]); cmp_ = tools.compare_windows()
    summary = f"{c['node']} GPU {c['gpu']}: utilization fell from {cmp_['baseline']['util']:.0f}% to {cmp_['incident']['util']:.0f}% (simulated fleet)"
    if dry:
        d = B.dump(store, c["node"], c["gpu"]); toks = len(json.dumps(d, separators=(',', ':'))) // 4
        print(c["id"], c["family"], summary, f"| dump ~{toks} tokens", "OK" if toks <= 12000 else "TOO BIG")
        gs = tools.group_stats("temp", "gpu_index", "incident")[:2]; print("    slot groups:", gs)
        continue
    if spent >= CAP:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: spend cap ${CAP} reached.")
    try:
        inv = investigate(chat, tools, summary, specs=B.SCALE_SPECS, system=B.SYSTEM, max_steps=14)
        b = B.baseline_answer(chat, store, c["node"], c["gpu"], summary)
    except Exception as e:
        out.write_text(json.dumps(state, indent=1)); sys.exit(f"STOP: API call failed ({type(e).__name__}: {str(e)[:100]}). Saved.")
    d = inv.diagnosis
    row = {"id": c["id"], "family": c["family"], "truth": c["truth"], "agent": {"root_cause": d["root_cause"], "confidence": d["confidence"], "tool_calls": len(inv.trace)},
           "baseline": {"root_cause": b["root_cause"], "confidence": b["confidence"], "dump_tokens_est": b["dump_tokens_est"]},
           "cost": cost_usd(inv.prompt_tokens, inv.completion_tokens) + cost_usd(b["prompt_tokens"], b["completion_tokens"])}
    spent += row["cost"]; state["rows"].append(row); out.write_text(json.dumps(state, indent=1))
    print(f"{c['id']} {c['family']} truth={c['truth']:22} agent={d['root_cause']:22}({d['confidence']:6}) base={b['root_cause']:22}({b['confidence']:6}) tools={len(inv.trace)} spent ${spent:.2f}", flush=True)
if not dry:
    print(f"\n=== Test 1 summary (design {design}) ===")
    for fam in "ABCD":
        rs = [r for r in state["rows"] if r["family"] == fam]
        if rs:
            ca = sum(r["agent"]["root_cause"] == r["truth"] for r in rs); cb = sum(r["baseline"]["root_cause"] == r["truth"] for r in rs)
            print(f"family {fam}: agent {ca}/{len(rs)}  one-shot {cb}/{len(rs)}")
    rs = state["rows"]; ca = sum(r["agent"]["root_cause"] == r["truth"] for r in rs); cb = sum(r["baseline"]["root_cause"] == r["truth"] for r in rs)
    print(f"pooled: agent {ca}/{len(rs)}  one-shot {cb}/{len(rs)}  | spend ${spent:.2f}")
