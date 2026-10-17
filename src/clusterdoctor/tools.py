"""Diagnostic tools the agent can call. All read from the Store; none mutate anything."""
from __future__ import annotations

import statistics
from typing import Callable

from .store import Store
from .watcher import percentile

ROOT_CAUSES = [
    "prompt_expansion", "client_concurrency", "retry_storm",
    "provider_side", "insufficient_evidence",
]


def _ok(rows):
    return [r for r in rows if r["status"] == 200 and r["latency_s"] is not None]


def _stats(rows) -> dict:
    ok = _ok(rows)
    if not rows:
        return {"n": 0}
    lat = [r["latency_s"] for r in ok]
    out = {
        "n": len(rows),
        "error_rate": round(1 - len(ok) / len(rows), 3),
        "avg_retries": round(statistics.mean(r["retries"] for r in rows), 2),
        "avg_concurrency": round(statistics.mean(r["concurrency"] for r in rows), 1),
        "app_versions": sorted({r["app_version"] for r in rows}),
    }
    if lat:
        out["latency_p50_s"] = round(percentile(lat, 0.5), 2)
        out["latency_p95_s"] = round(percentile(lat, 0.95), 2)
    ins = [r["input_tokens"] for r in ok if r["input_tokens"] is not None]
    outs = [r["output_tokens"] for r in ok if r["output_tokens"] is not None]
    ttft = [r["ttft_s"] for r in ok if r["ttft_s"] is not None]
    if ins:
        out["avg_input_tokens"] = round(statistics.mean(ins))
    if outs:
        out["avg_output_tokens"] = round(statistics.mean(outs))
    if ttft:
        out["ttft_p50_s"] = round(percentile(ttft, 0.5), 2)
    return out


class Tools:
    """Holds the incident context so the model only passes short arguments."""

    def __init__(self, store: Store, baseline: tuple[float, float], incident: tuple[float, float],
                 include_events: bool = True):
        self.store, self.baseline, self.incident = store, baseline, incident
        self.include_events = include_events

    def _window(self, name: str):
        return {"baseline": self.baseline, "incident": self.incident}[name]

    def compare_windows(self) -> dict:
        """Summary stats for the baseline window and the incident window side by side."""
        return {n: _stats(self.store.requests_between(*self._window(n))) for n in ("baseline", "incident")}

    def list_events(self) -> list[dict]:
        """Deploys and config changes recorded around the incident (from just before baseline end)."""
        if not self.include_events:
            return []
        rows = self.store.events_between(self.baseline[0], self.incident[1])
        return [{"ts": r["ts"], "kind": r["kind"], "detail": r["detail"],
                 "before_incident_start": r["ts"] <= self.incident[0]} for r in rows]

    def latency_by_input_size(self, window: str) -> list[dict]:
        """Median latency per input-token bucket, so size effects can be separated from other causes."""
        rows = [r for r in _ok(self.store.requests_between(*self._window(window)))
                if r["input_tokens"] is not None]
        return self._bucket(rows, "input_tokens", [0, 500, 1500, 4000, 10**9])

    def latency_by_concurrency(self, window: str) -> list[dict]:
        """Median latency per concurrency bucket."""
        rows = _ok(self.store.requests_between(*self._window(window)))
        return self._bucket(rows, "concurrency", [0, 2, 5, 10, 10**9])

    def retry_breakdown(self, window: str) -> list[dict]:
        """Median end-to-end latency and share of requests by number of retries."""
        rows = self.store.requests_between(*self._window(window))
        out = []
        for k in sorted({r["retries"] for r in rows}):
            grp = [r for r in rows if r["retries"] == k]
            lat = [r["latency_s"] for r in grp if r["latency_s"] is not None]
            out.append({"retries": k, "share": round(len(grp) / len(rows), 2), "n": len(grp),
                        "median_latency_s": round(statistics.median(lat), 2) if lat else None,
                        "final_error_rate": round(sum(r["status"] != 200 for r in grp) / len(grp), 2)})
        return out

    def stratified_latency(self, window: str, factor_a: str, factor_b: str) -> list[dict]:
        """Median latency per (factor_a bucket x factor_b bucket). window: baseline | incident | both.

        Use it to vary one factor while holding another fixed, e.g. does latency still rise with
        input size among requests with zero retries? With window=both, compare strata across windows.
        """
        edges = {"input_tokens": [0, 500, 1500, 4000, 10**9], "retries": [0, 1, 2, 10**9],
                 "concurrency": [0, 2, 5, 10, 10**9]}
        if factor_a not in edges or factor_b not in edges or factor_a == factor_b:
            return [{"error": f"factors must be two different values of {sorted(edges)}"}]
        out = []
        for w in (["baseline", "incident"] if window == "both" else [window]):
            rows = [r for r in _ok(self.store.requests_between(*self._window(w)))
                    if r["input_tokens"] is not None]
            for a_lo, a_hi in zip(edges[factor_a], edges[factor_a][1:]):
                for b_lo, b_hi in zip(edges[factor_b], edges[factor_b][1:]):
                    grp = [r["latency_s"] for r in rows
                           if a_lo <= r[factor_a] < a_hi and b_lo <= r[factor_b] < b_hi]
                    if grp:
                        fmt = lambda lo, hi: f"{lo}-{hi if hi < 10**9 else 'inf'}"  # noqa: E731
                        out.append({"window": w, factor_a: fmt(a_lo, a_hi), factor_b: fmt(b_lo, b_hi),
                                    "n": len(grp), "median_latency_s": round(statistics.median(grp), 2)})
        return out

    @staticmethod
    def _bucket(rows, key, edges) -> list[dict]:
        out = []
        for lo, hi in zip(edges, edges[1:]):
            grp = [r["latency_s"] for r in rows if lo <= r[key] < hi]
            if grp:
                out.append({f"{key}_range": f"{lo}-{hi if hi < 10**9 else 'inf'}",
                            "n": len(grp), "median_latency_s": round(statistics.median(grp), 2)})
        return out

    # name -> (callable, json schema) -------------------------------------------------
    def registry(self) -> dict[str, Callable]:
        return {
            "compare_windows": self.compare_windows,
            "list_events": self.list_events,
            "latency_by_input_size": self.latency_by_input_size,
            "latency_by_concurrency": self.latency_by_concurrency,
            "retry_breakdown": self.retry_breakdown,
            "stratified_latency": self.stratified_latency,
        }


WINDOW_ARG = {"type": "object", "properties": {"window": {"type": "string", "enum": ["baseline", "incident"]}},
              "required": ["window"]}
NO_ARGS = {"type": "object", "properties": {}}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "compare_windows", "parameters": NO_ARGS,
        "description": "Latency, token, retry, error and concurrency stats for baseline vs incident windows."}},
    {"type": "function", "function": {
        "name": "list_events", "parameters": NO_ARGS,
        "description": "Deploys and config changes near the incident."}},
    {"type": "function", "function": {
        "name": "latency_by_input_size", "parameters": WINDOW_ARG,
        "description": "Median latency per input-token bucket for one window."}},
    {"type": "function", "function": {
        "name": "latency_by_concurrency", "parameters": WINDOW_ARG,
        "description": "Median latency per concurrency bucket for one window."}},
    {"type": "function", "function": {
        "name": "retry_breakdown", "parameters": WINDOW_ARG,
        "description": "Share of requests and median end-to-end latency by retry count for one window."}},
    {"type": "function", "function": {
        "name": "submit_diagnosis",
        "description": "Finish the investigation. Cite tool call ids as evidence. Use insufficient_evidence if the data cannot decide.",
        "parameters": {"type": "object", "properties": {
            "root_cause": {"type": "string", "enum": ROOT_CAUSES},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "tool_call_id": {"type": "string"}},
                "required": ["claim", "tool_call_id"]}},
            "rejected_hypotheses": {"type": "array", "items": {"type": "object", "properties": {
                "cause": {"type": "string"}, "why_rejected": {"type": "string"}},
                "required": ["cause", "why_rejected"]}},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "recommended_actions": {"type": "array", "items": {"type": "string"}},
        }, "required": ["root_cause", "confidence", "evidence", "rejected_hypotheses",
                        "uncertainties", "recommended_actions"]}}},
]


# ---- spec set with a required hypothesis-testing protocol ---------------------------------
import copy  # noqa: E402

FACTORS = ["input_tokens", "retries", "concurrency"]
_strat_tool = {"type": "function", "function": {
    "name": "stratified_latency",
    "description": ("Median latency in a grid of two factors, to vary one factor while holding another fixed. "
                    "window=both shows baseline and incident side by side."),
    "parameters": {"type": "object", "properties": {
        "window": {"type": "string", "enum": ["baseline", "incident", "both"]},
        "factor_a": {"type": "string", "enum": FACTORS}, "factor_b": {"type": "string", "enum": FACTORS}},
        "required": ["window", "factor_a", "factor_b"]}}}
_submit_strat = copy.deepcopy(TOOL_SPECS[-1])
_p = _submit_strat["function"]["parameters"]
_p["properties"]["hypothesis_tests"] = {"type": "array", "items": {"type": "object", "properties": {
    "hypothesis": {"type": "string"}, "factor_varied": {"type": "string"}, "held_fixed": {"type": "string"},
    "tool_call_id": {"type": "string"}, "result": {"type": "string"}},
    "required": ["hypothesis", "factor_varied", "held_fixed", "tool_call_id", "result"]}}
_p["required"].append("hypothesis_tests")
TOOL_SPECS_STRAT = [*TOOL_SPECS[:-1], _strat_tool, _submit_strat]
