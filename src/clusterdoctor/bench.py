"""Benchmark helpers: the single-pass baseline and cost accounting.

The baseline sees what a dashboard shows (window comparison stats and recent
events) in ONE model call, with no tools and no follow-up queries. It uses the
same model as the agent, so the comparison isolates the investigation loop.
"""
from __future__ import annotations

import json
import time

from .agent import Chat
from .tools import ROOT_CAUSES, Tools

BASELINE_SYSTEM = f"""You diagnose application-side performance incidents for an app calling a hosted LLM API.
You get dashboard-style summaries once and must answer in one reply. Respond with ONLY a JSON object:
{{"root_cause": one of {ROOT_CAUSES}, "confidence": "high"|"medium"|"low", "reasoning": "<short>"}}
Use insufficient_evidence if the summaries cannot decide."""

# Ultra pricing per 1M tokens (USD) from the Token Factory listing.
PRICE_IN, PRICE_OUT = 1.00, 3.00


def cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens / 1e6 * PRICE_IN + completion_tokens / 1e6 * PRICE_OUT


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def baseline_diagnose(chat: Chat, tools: Tools, incident_summary: str) -> dict:
    dashboard = {"windows": tools.compare_windows(), "events": tools.list_events()}
    messages = [{"role": "system", "content": BASELINE_SYSTEM},
                {"role": "user", "content": f"Incident: {incident_summary}\n\n{json.dumps(dashboard, default=str)}"}]
    t = time.time()
    reply = chat(messages, [])
    parsed = _parse_json(reply.get("content") or "")
    valid = parsed is not None and parsed.get("root_cause") in ROOT_CAUSES
    return {
        "root_cause": parsed["root_cause"] if valid else "unparseable",
        "confidence": parsed.get("confidence", "low") if valid else "low",
        "latency_s": time.time() - t,
        "prompt_tokens": reply.get("prompt_tokens") or 0,
        "completion_tokens": reply.get("completion_tokens") or 0,
    }


def baseline_diagnose_rich(chat: Chat, tools: Tools, incident_summary: str) -> dict:
    """Single pass, no tools, but given every table the agent could query (the 'fair' baseline)."""
    pairs = [("input_tokens", "retries"), ("input_tokens", "concurrency"), ("retries", "concurrency")]
    dashboard = {
        "windows": tools.compare_windows(),
        "events": tools.list_events(),
        "retry_breakdown": {w: tools.retry_breakdown(w) for w in ("baseline", "incident")},
        "stratified_latency_both_windows": {f"{a} x {b}": tools.stratified_latency("both", a, b) for a, b in pairs},
    }
    messages = [{"role": "system", "content": BASELINE_SYSTEM + (
                    "\nThe tables include stratified median latency (baseline and incident side by side). "
                    "Compare within a fixed stratum before blaming a factor.")},
                {"role": "user", "content": f"Incident: {incident_summary}\n\n{json.dumps(dashboard, default=str)}"}]
    t = time.time()
    reply = chat(messages, [])
    parsed = _parse_json(reply.get("content") or "")
    valid = parsed is not None and parsed.get("root_cause") in ROOT_CAUSES
    return {"root_cause": parsed["root_cause"] if valid else "unparseable",
            "confidence": parsed.get("confidence", "low") if valid else "low",
            "latency_s": time.time() - t,
            "prompt_tokens": reply.get("prompt_tokens") or 0,
            "completion_tokens": reply.get("completion_tokens") or 0}
