"""Controlled application-side faults, so every incident has a known root cause.

Each fault changes how the demo app builds its requests. The ground truth is
returned so the benchmark can score the agent's diagnosis against it.
"""
from __future__ import annotations

from dataclasses import dataclass

FILLER = ("The quarterly report covers capacity planning, thermal envelopes, "
          "network topology and scheduler behaviour across the fleet. ") * 4


@dataclass(frozen=True)
class Fault:
    name: str
    root_cause: str          # ground truth label used by the benchmark
    app_version: str         # version string recorded with each request
    context_chunks: int      # retrieved chunks stuffed into the prompt
    concurrency: int
    deploy_note: str
    fail_rate: float = 0.0
    max_retries: int = 2
    bloat_share: float = 0.0     # share of requests that get bloat_chunks instead
    bloat_chunks: int = 600
    extra_latency_s: float = 0.0  # injected provider-side delay (simulated)
    burst: bool = False           # alternate 16-worker bursts with single-worker lulls


BASELINE = Fault("baseline", "none", "v1", 2, 1, "initial release")

HEALTHY = Fault("healthy", "none", "v1", 2, 1, "no change")

FAULTS = {
    "prompt_bloat": Fault(
        "prompt_bloat", "prompt_expansion", "v2", 600, 1,
        "retrieval top_k raised from 2 to 600 chunks"),
    "high_concurrency": Fault(
        "high_concurrency", "client_concurrency", "v1", 2, 16,
        "worker pool raised from 1 to 16"),
    "retry_storm": Fault(
        "retry_storm", "retry_storm", "v3", 2, 1,
        "retry policy changed: max_retries 2 -> 4", fail_rate=0.5, max_retries=4),
    # ---- hard cases: a one-shot dashboard summary can mislead ----
    "overlap": Fault(
        "overlap", "retry_storm", "v4", 40, 1,
        "retrieval top_k raised from 2 to 40", fail_rate=0.5, max_retries=4),
    "misleading_event": Fault(
        "misleading_event", "client_concurrency", "v4", 40, 16,
        "retrieval top_k raised from 2 to 40", burst=True),
    "bloat_subset": Fault(
        "bloat_subset", "prompt_expansion", "v4", 2, 1,
        "retrieval fallback enabled for long documents", bloat_share=0.125),
    "provider_slowdown": Fault(
        "provider_slowdown", "provider_side", "v1", 2, 1, "", extra_latency_s=1.0),
}

HARD = {"overlap", "misleading_event", "bloat_subset", "provider_slowdown"}


def build_messages(fault: Fault, question: str) -> list[dict]:
    context = "\n\n".join(f"[doc {i}] {FILLER}" for i in range(fault.context_chunks))
    return [
        {"role": "system", "content": "Answer briefly using the documents provided."},
        {"role": "user", "content": f"{context}\n\nQuestion: {question}"},
    ]
