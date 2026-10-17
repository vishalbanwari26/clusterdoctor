"""Generate live traffic for a scenario: a baseline phase, then a (possibly faulty) phase."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from .faults import BASELINE, Fault, build_messages
from .llm import InstrumentedClient
from .store import Store

QUESTIONS = ["What is the main risk?", "Summarise the key point.", "What should we monitor?"]


def _run(store: Store, cfg: Fault, n: int, workers: int, offset: int = 0) -> None:
    client = InstrumentedClient(store, app_version=cfg.app_version, max_retries=cfg.max_retries)

    def one(i):
        i += offset
        bloated = cfg.bloat_share and i % round(1 / cfg.bloat_share) == 0
        chunks = cfg.bloat_chunks if bloated else cfg.context_chunks
        msgs = build_messages(replace(cfg, context_chunks=chunks), QUESTIONS[i % 3])
        client.complete(msgs, max_tokens=48, concurrency=workers, fail_rate=cfg.fail_rate,
                        extra_latency_s=cfg.extra_latency_s)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, range(n)))


def run_phase(store: Store, cfg: Fault, n: int) -> None:
    if not cfg.burst:
        return _run(store, cfg, n, cfg.concurrency)
    done = 0   # bursts: many workers, then a single-worker lull, repeated
    while done < n:
        _run(store, cfg, min(80, n - done), cfg.concurrency, done)
        done += 80
        if done < n:
            _run(store, cfg, min(10, n - done), 1, done)
            done += 10


def generate_case(store: Store, fault: Fault, n_base: int, n_fault: int) -> dict:
    """Returns the time boundaries. A 'healthy' case uses BASELINE config for phase two."""
    t0 = time.time()
    run_phase(store, BASELINE, n_base)
    t1 = time.time()
    if fault.name != "healthy" and fault.deploy_note:
        store.add_event(t1, "deploy", fault.deploy_note)
    run_phase(store, fault, n_fault)
    return {"t0": t0, "t1": t1, "t2": time.time(), "fault": fault.name,
            "truth": fault.root_cause}
