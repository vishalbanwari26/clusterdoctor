"""Fair one-shot baseline on the two real Kalos events, 3 repeats each (about $0.01 per call)."""
import json
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import nemotron_chat  # noqa: E402
from clusterdoctor.bench import baseline_diagnose_real, cost_usd  # noqa: E402
from clusterdoctor.gpu_tools import GpuTools  # noqa: E402
from clusterdoctor.real import load_event, load_slices  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402

chat = nemotron_chat()
rows = []
for ev in ("A", "B"):
    d = json.load(open(f"data/replays/real-xid94-{ev.lower()}.json"))
    store = Store(":memory:"); info = load_event(store, load_slices()["events"][ev])
    tools = GpuTools(store, info["node"], info["gpu"], tuple(d["telemetry"]["baseline"]), tuple(d["telemetry"]["incident"]))
    agent = d["investigation"]["diagnosis"]
    for rep in range(3):
        try:
            b = baseline_diagnose_real(chat, tools, d["summary"] + " (REAL telemetry, AcmeTrace Kalos)")
        except Exception as e:
            sys.exit(f"STOP: API call failed ({type(e).__name__}).")
        b["cost_usd"] = cost_usd(b["prompt_tokens"], b["completion_tokens"])
        rows.append({"event": ev, "rep": rep + 1, "baseline": b, "agent": {"root_cause": agent["root_cause"], "confidence": agent["confidence"]}})
        print(f"{ev} #{rep+1}: baseline {b['root_cause']} ({b['confidence']}) ${b['cost_usd']:.4f} | agent {agent['root_cause']} ({agent['confidence']})")
        print("    reasoning:", b["reasoning"][:230])
json.dump(rows, open("bench/results_real_baseline.json", "w"), indent=2)
print(f"total baseline cost ${sum(r['baseline']['cost_usd'] for r in rows):.3f}")
