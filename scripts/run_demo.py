"""Live end-to-end run: baseline traffic -> inject fault -> detect -> investigate.

Usage: PYTHONPATH=src uv run python scripts/run_demo.py [fault_name] [n_baseline] [n_fault]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(".env")

from clusterdoctor.agent import investigate, nemotron_chat  # noqa: E402
from clusterdoctor.faults import BASELINE, FAULTS, build_messages  # noqa: E402
from clusterdoctor.llm import InstrumentedClient  # noqa: E402
from clusterdoctor.store import Store  # noqa: E402
from clusterdoctor.tools import Tools  # noqa: E402
from clusterdoctor.watcher import detect_latency_incident  # noqa: E402

fault = FAULTS[sys.argv[1] if len(sys.argv) > 1 else "prompt_bloat"]
n_base = int(sys.argv[2]) if len(sys.argv) > 2 else 25
n_fault = int(sys.argv[3]) if len(sys.argv) > 3 else 25

store = Store(f"demo_{fault.name}.db")
QUESTIONS = ["What is the main risk?", "Summarise the key point.", "What should we monitor?"]


def run_phase(cfg, n):
    client = InstrumentedClient(store, app_version=cfg.app_version, max_retries=cfg.max_retries)

    def one(i):
        client.complete(build_messages(cfg, QUESTIONS[i % 3]), max_tokens=48,
                        concurrency=cfg.concurrency, fail_rate=cfg.fail_rate)

    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        list(pool.map(one, range(n)))


t0 = time.time()
print(f"baseline: {n_base} requests ({BASELINE.deploy_note})")
run_phase(BASELINE, n_base)
t1 = time.time()
store.add_event(t1, "deploy", fault.deploy_note)
print(f"injecting fault '{fault.name}': {fault.deploy_note}  (ground truth: {fault.root_cause})")
run_phase(fault, n_fault)
t2 = time.time()

inc = detect_latency_incident(store, (t0, t1), t1, t2, window_s=10, ratio=1.5, min_requests=3)
if not inc:
    sys.exit("watcher did not open an incident (try more fault requests)")
print("INCIDENT:", inc.summary())

tools = Tools(store, (t0, t1), inc.window)
result = investigate(nemotron_chat(), tools, inc.summary())
print(f"\nsteps: {result.steps}, tool calls: {[t['tool'] for t in result.trace]}")
print(json.dumps(result.diagnosis, indent=2))
print(f"dropped (unsupported) evidence: {len(result.dropped_evidence)}")
print(f"match ground truth: {result.diagnosis['root_cause'] == fault.root_cause}")
