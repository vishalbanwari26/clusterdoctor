"""Hybrid workflow (pre-registered as Test 4 in docs/preregistered-tests.md).

evidence pack (code) -> one model call writes the report -> claim check (one revision) -> escalate to the tool agent
only if the final label is insufficient_evidence, confidence is low, claims still fail the check, or output is unparseable.
"""
from __future__ import annotations

import json
from typing import Callable

from .agent import Chat, _sanitize, verify_claims
from .bench import _parse_json
from .tools import ROOT_CAUSES

CONF = ("high", "medium", "low")

SYSTEM = f"""You are ClusterDoctor, an infrastructure reliability investigator for an AI app that calls a hosted LLM API.
An incident was detected by a monitor. You get a fixed evidence pack of sections (each has an id) and must write the report.
Compare like with like: the stratified tables give median latency by two factors side by side for the normal period (baseline)
and the incident; hold one factor fixed before blaming another. You only see application-side telemetry, so do not blame the
provider without evidence; if the pack cannot decide, say insufficient_evidence.
Reply with ONLY JSON: {{"root_cause": one of {ROOT_CAUSES}, "confidence": "high"|"medium"|"low",
"evidence": [{{"claim": "<one factual statement with its numbers>", "tool_call_id": "<a section id from the pack>"}}],
"rejected_hypotheses": [{{"cause": "<label>", "why_rejected": "<reason with numbers>"}}],
"uncertainties": ["..."], "recommended_actions": ["..."]}}.
Every evidence item must cite one section id from the pack. Use confidence as one of the three words, not a number."""


def evidence_pack(tools) -> dict:
    return {
        "pack_windows": tools.compare_windows(),
        "pack_events": tools.list_events(),
        "pack_retries_baseline": tools.retry_breakdown("baseline"),
        "pack_retries_incident": tools.retry_breakdown("incident"),
        "pack_strat_input_retries": tools.stratified_latency("both", "input_tokens", "retries"),
        "pack_strat_input_concurrency": tools.stratified_latency("both", "input_tokens", "concurrency"),
        "pack_strat_retries_concurrency": tools.stratified_latency("both", "retries", "concurrency"),
    }


def pack_trace(pack: dict) -> list[dict]:
    """The pack in the shape verify_claims expects (a ledger of tool results)."""
    return [{"id": k, "tool": k, "args": {}, "result": v} for k, v in pack.items()]


def _check(obj, pack_ids: set[str], labels: list[str] = ROOT_CAUSES) -> tuple[dict | None, str]:
    """Return (diagnosis, "") if usable, else (None, why) so the model can be told once."""
    if not isinstance(obj, dict):
        return None, "Reply with only the JSON object described."
    if obj.get("root_cause") not in labels:
        return None, f"root_cause must be exactly one of {labels}."
    if obj.get("confidence") not in CONF:
        return None, "confidence must be the word high, medium or low."
    d = _sanitize(dict(obj))
    if d["root_cause"] != "insufficient_evidence" and not any(e.get("tool_call_id") in pack_ids for e in d["evidence"]):
        return None, f"evidence must cite section ids from the pack: {sorted(pack_ids)}."
    return d, ""


def report_schema(pack_ids: list[str], labels: list[str]) -> dict:
    """Strict JSON schema: labels and citations are enums, so neither can be free text."""
    str_list = {"type": "array", "items": {"type": "string"}}
    return {"type": "json_schema", "json_schema": {"name": "report", "strict": True, "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["root_cause", "confidence", "evidence", "rejected_hypotheses", "uncertainties", "recommended_actions"],
        "properties": {
            "root_cause": {"type": "string", "enum": labels}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "evidence": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["claim", "tool_call_id"],
                                                    "properties": {"claim": {"type": "string"}, "tool_call_id": {"type": "string", "enum": pack_ids}}}},
            "rejected_hypotheses": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["cause", "why_rejected"],
                                                               "properties": {"cause": {"type": "string"}, "why_rejected": {"type": "string"}}}},
            "uncertainties": str_list, "recommended_actions": str_list}}}}


def hybrid_investigate(chat: Chat, verifier: Chat, tools, incident_summary: str, escalate: Callable[[], object],
                       pack: dict | None = None, system: str = SYSTEM, labels: list[str] = ROOT_CAUSES, strict: bool = False) -> dict:
    pack = pack if pack is not None else evidence_pack(tools); ids = set(pack); trace = pack_trace(pack)
    schema = report_schema(sorted(ids), labels) if strict else None
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Incident: {incident_summary}\n\n{json.dumps(pack, default=str)}"}]
    use = {"prompt": 0, "completion": 0, "verifier": 0, "calls": 0}

    def ask(strict_now=True):
        r = chat(messages, [], response_format=schema, max_tokens=1800) if (schema and strict_now) else chat(messages, [])
        use["prompt"] += r.get("prompt_tokens") or 0; use["completion"] += r.get("completion_tokens") or 0; use["calls"] += 1
        messages.append({"role": "assistant", "content": r.get("content") or ""})
        return _parse_json(r.get("content") or "")

    def ask_valid():
        d, why = _check(ask(), ids, labels)
        if d is None:
            # strict-schema decoding can degenerate into endless whitespace on long prompts, so the retry is a plain JSON reply that we validate ourselves
            messages.append({"role": "user", "content": why + " Reply again with the full JSON."})
            d, why = _check(ask(strict_now=False), ids, labels)
        return d, why

    reasons, first = [], None
    diag, why = ask_valid()
    issues, info = [], {"claims_total": 0, "first_issues": 0, "revised": False}
    if diag is None:
        reasons.append("unparseable")
    else:
        first = {"root_cause": diag["root_cause"], "confidence": diag["confidence"]}
        issues, u = verify_claims(verifier, trace, diag); use["verifier"] += u["tokens"]
        info["claims_total"] = len(diag["evidence"]) + len(diag["rejected_hypotheses"]); info["first_issues"] = len(issues)
        if issues:                                                    # one revision
            info["revised"] = True
            messages.append({"role": "user", "content": "A fact check found claims that conflict with the pack: " +
                             "; ".join(f"[{i['verdict']}] {i['claim'][:140]} -> {i['reason'][:160]}" for i in issues) +
                             ". Reply with the corrected full JSON."})
            d2, why = _check(ask(), ids, labels)
            if d2 is None:
                reasons.append("unparseable")
            else:
                diag = d2
                issues, u = verify_claims(verifier, trace, diag); use["verifier"] += u["tokens"]
        if diag is not None:
            if diag["root_cause"] == "insufficient_evidence": reasons.append("abstained")
            if diag["confidence"] == "low": reasons.append("low_confidence")
            if issues: reasons.append("claim_check_failed")
    out = {"first_pass": first, "reasons": sorted(set(reasons)), "tokens": use, "escalated": False, "diagnosis": diag,
           "claims": {**info, "final_issues": len(issues)}, "pack": pack}
    if reasons:
        inv = escalate()
        out["escalated"] = True
        out["escalation"] = inv
        out["diagnosis"] = inv.diagnosis
        out["escalation_tokens"] = {"prompt": inv.prompt_tokens, "completion": inv.completion_tokens, "verifier": inv.verifier_tokens}
    return out


# ---------------- domain packs and prompts (the product workflow) ----------------
from .evidence import effect_split  # noqa: E402
from .gpu_tools import GPU_ROOT_CAUSES  # noqa: E402

INF_SYSTEM = SYSTEM + """
Section pack_effect_split fits latency on the factors that vary INSIDE the incident window. Prefer a factor whose variation inside the window moves
latency. A factor marked varies_in_incident_window=false changed but cannot be separated from other changes in this window. If no factor varies and
latency still rose, consider that the cause is outside the app's own requests."""


def inference_pack(tools) -> dict:
    return {**evidence_pack(tools), "pack_effect_split": effect_split(tools)}


def gpu_pack(tools) -> dict:
    win = ("baseline", "incident")
    pack = {"pack_gpu_windows": tools.compare_windows(),
            **{f"pack_gpu_throttle_{w}": tools.throttle_reasons(w) for w in win},
            **{f"pack_gpu_pattern_{w}": tools.util_pattern(w) for w in win},
            **{f"pack_gpu_host_cpu_{w}": tools.host_cpu(w) for w in win},
            "pack_gpu_peers": tools.peer_gpus()}
    codes = {c for w in win for c in pack[f"pack_gpu_throttle_{w}"].get("xid_errors_seen", [])}
    if codes:
        pack["pack_gpu_xid_catalog"] = {str(c): tools.xid_lookup(int(c)) for c in sorted(codes)}
    return pack


_GPU_BASE = f"""You are ClusterDoctor, an infrastructure reliability investigator for GPU clusters. A monitor flagged one GPU, either for low utilization
or because the driver reported an Xid error (the incident text says which). You get a fixed evidence pack of sections (each has an id) and write the report.
Possible causes: {GPU_ROOT_CAUSES}. Low utilization alone does not identify a cause: compare the flagged GPU with its baseline and with its peers.
Missing values are null: say so instead of assuming. If the pack cannot decide, say insufficient_evidence. Every evidence item must cite one section id.
Use confidence as one of the three words. Reply with ONLY JSON matching the schema."""
GPU_SYSTEM_WF = _GPU_BASE + " The telemetry is SIMULATED; say what you can and cannot conclude."
REAL_SYSTEM_WF = _GPU_BASE + (" The telemetry is REAL (15 s samples) with utilization, temperature, power and the Xid code only: no clock, throttle-reason or host-CPU data. "
                              "pack_gpu_xid_catalog explains any Xid code from NVIDIA's catalog (only a few codes); rely only on what it says. The Xid field keeps the "
                              "last code, so a change is an event.")
