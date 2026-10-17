"""The investigation loop: the model calls diagnostic tools, then submits a diagnosis.

The diagnosis is validated before it is accepted. Every evidence item must cite a
tool call that actually happened in this investigation; otherwise it is dropped,
and a diagnosis left with no supported evidence is downgraded to insufficient_evidence.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from .tools import Tools, TOOL_SPECS

SYSTEM = """You are ClusterDoctor, an infrastructure reliability investigator.
An incident was detected by a monitor. Find the root cause using only the tools.
Method: form competing hypotheses, call tools that can tell them apart, and reject
hypotheses the data contradicts. Compare like with like (hold other factors fixed).
Only diagnose causes the telemetry can support. You only see application-side
telemetry, so do not blame the inference provider's internals without evidence;
if the data cannot decide, submit insufficient_evidence. Finish by calling
submit_diagnosis, citing the call_id (like call_1) of the tool result that supports each claim."""

VERIFIER_SYSTEM = """You audit an investigation report against the raw tool results it was based on.
You get tool_results (the only data that exists) and claims. For each claim judge ONLY its factual and
numeric statements against the tool results, comparing across results when the claim does.
Verdicts: "supported" (facts match the data), "contradicted" (a stated fact or number conflicts with the
data), "unverifiable" (states a fact that is not in any tool result). Ignore causal interpretation,
hedged speculation and recommendations: do not penalise reasoning, only checkable facts.
Reply with ONLY a JSON list: [{"id": <n>, "verdict": "...", "reason": "<short, cite the numbers>"}]"""


def _json_list(text: str):
    a, b = (text or "").find("["), (text or "").rfind("]")
    try:
        return json.loads(text[a:b + 1]) if 0 <= a < b else None
    except json.JSONDecodeError:
        return None


def verify_claims(verifier: Chat, trace: list[dict], diag: dict) -> tuple[list[dict], dict]:
    """Returns (issues, usage). Each issue: {"claim", "verdict", "reason"} for non-supported claims."""
    claims = [{"id": i, "claim": e["claim"], "cited": e.get("tool_call_id")}
              for i, e in enumerate(diag.get("evidence", []))]
    claims += [{"id": len(claims) + j, "claim": f"{h['cause']} is ruled out: {h['why_rejected']}", "cited": None}
               for j, h in enumerate(diag.get("rejected_hypotheses", []))]
    claims += [{"id": len(claims) + j, "claim": f"test of '{t.get('hypothesis')}' (varied {t.get('factor_varied')}, "
                f"held {t.get('held_fixed')}): {t.get('result')}", "cited": t.get("tool_call_id")}
               for j, t in enumerate(diag.get("hypothesis_tests", []))]
    if not claims:
        return [], {"tokens": 0}
    payload = {"tool_results": [{"call_id": t["id"], "tool": t["tool"], "args": t["args"],
                                 "result": t["result"]} for t in trace], "claims": claims}
    reply = verifier([{"role": "system", "content": VERIFIER_SYSTEM},
                      {"role": "user", "content": json.dumps(payload, default=str)}], [])
    usage = {"tokens": (reply.get("prompt_tokens") or 0) + (reply.get("completion_tokens") or 0)}
    verdicts = {v.get("id"): v for v in (_json_list(reply.get("content") or "") or []) if isinstance(v, dict)}
    issues = []
    for c in claims:
        v = verdicts.get(c["id"])
        if v and v.get("verdict") in ("contradicted", "unverifiable"):
            issues.append({"claim": c["claim"], "verdict": v["verdict"], "reason": v.get("reason", "")})
    return issues, usage


SYSTEM_STRAT = SYSTEM + """
Protocol: before diagnosing, test your TOP TWO competing hypotheses with stratified_latency. For each,
vary the suspected factor while holding another factor fixed (compare within the same stratum, and across
windows when needed). A factor is not responsible if latency does not move with it inside a fixed stratum
of the other factors. Report each test in hypothesis_tests with the call_id of that stratified_latency result."""

# chat(messages, tools) -> assistant message dict {"content": str|None, "tool_calls": [{"id","name","arguments"}]}
Chat = Callable[[list[dict], list[dict]], dict]


@dataclass
class Investigation:
    diagnosis: dict | None = None
    trace: list[dict] = field(default_factory=list)   # every tool call and result
    dropped_evidence: list[dict] = field(default_factory=list)
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    claims_total: int = 0          # claims in the FIRST submission
    claims_unsupported_first: int = 0
    claims_unsupported_final: int = 0
    revisions: int = 0
    verifier_tokens: int = 0
    protocol_retries: int = 0
    schema_retries: int = 0
    label_retries: int = 0
    citation_retries: int = 0
    original_root_cause: str | None = None   # what the model said before the evidence check downgraded it
    tests_valid: int = 0


def nemotron_chat(model: str | None = None) -> Chat:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["NEBIUS_API_KEY"],
                    base_url=os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"))
    model = model or os.environ.get("CD_AGENT_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")

    def chat(messages, tools):
        kwargs = {"tools": tools} if tools else {}
        resp = client.chat.completions.create(model=model, messages=messages, **kwargs)
        m = resp.choices[0].message
        return {"content": m.content,
                "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                               for c in (m.tool_calls or [])],
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0}
    return chat


def investigate(chat: Chat, tools, incident_summary: str, max_steps: int = 10,
                specs: list[dict] = TOOL_SPECS, system: str = SYSTEM,
                verifier: Chat | None = None, max_revisions: int = 2,
                required_tests: int = 0, test_tool: str = "stratified_latency") -> Investigation:
    inv = Investigation()
    registry = tools.registry()
    seen_ids: set[str] = set()
    n_calls = 0
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Incident: {incident_summary}"}]

    while inv.steps < max_steps:
        inv.steps += 1
        reply = chat(messages, specs)
        inv.prompt_tokens += reply.get("prompt_tokens") or 0
        inv.completion_tokens += reply.get("completion_tokens") or 0
        calls = reply.get("tool_calls") or []
        # Replace provider ids with short ones the model can cite reliably.
        for c in calls:
            n_calls += 1
            c["id"] = f"call_{n_calls}"
        messages.append({"role": "assistant", "content": reply.get("content"),
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in calls] or None})
        if not calls:
            messages.append({"role": "user", "content": "Call a tool or submit_diagnosis."})
            continue

        revise = False
        for c in calls:
            if revise:   # a revision was requested earlier in this message: answer remaining calls with a stub
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": "ignored: revise first"})
                continue
            args = json.loads(c["arguments"] or "{}")
            if c["name"] == "submit_diagnosis":
                need = ["root_cause", "confidence", "evidence", "rejected_hypotheses", "uncertainties", "recommended_actions"]
                missing = [k for k in need if k not in args]
                if missing and inv.schema_retries < 2:          # the API does not enforce the schema, so we do
                    inv.schema_retries += 1
                    revise = True
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content":
                                     f"submit_diagnosis is missing required fields: {', '.join(missing)}. Call it again with every field."})
                    continue
                for k, v in (("root_cause", "insufficient_evidence"), ("confidence", "low"), ("evidence", []),
                             ("rejected_hypotheses", []), ("uncertainties", ["incomplete submission"]), ("recommended_actions", [])):
                    args.setdefault(k, v)
                args = _sanitize(args)
                allowed = _allowed_labels(specs)
                if allowed and args["root_cause"] not in allowed and inv.label_retries < 2:
                    inv.label_retries += 1
                    revise = True
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content":
                                     f"root_cause must be exactly one of {allowed}. You wrote: {str(args['root_cause'])[:80]!r}. "
                                     "Call submit_diagnosis again with one of those labels."})
                    continue
                if (args["root_cause"] != "insufficient_evidence" and seen_ids and inv.citation_retries < 1
                        and not any(e.get("tool_call_id") in seen_ids for e in args["evidence"])):
                    inv.citation_retries += 1
                    revise = True
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content":
                                     "Your evidence cites no tool result. Every evidence item needs a tool_call_id that is one of "
                                     f"{sorted(seen_ids, key=lambda x: int(x.split('_')[1]))}. Call submit_diagnosis again with citations."})
                    continue
                if allowed and args["root_cause"] not in allowed:       # retries used up: fall back instead of accepting free text
                    args["uncertainties"] = args["uncertainties"] + [f"root_cause {str(args['root_cause'])[:60]!r} was not an allowed label"]
                    args["root_cause"] = "insufficient_evidence"
                diag = _validate(args, seen_ids, inv)
                strat_ids = {t["id"] for t in inv.trace if t["tool"] == test_tool}
                inv.tests_valid = sum(t.get("tool_call_id") in strat_ids for t in diag.get("hypothesis_tests", []))
                if required_tests and inv.tests_valid < required_tests and inv.protocol_retries < 2:
                    inv.protocol_retries += 1
                    revise = True
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content":
                                     f"Protocol not met: hypothesis_tests must contain at least {required_tests} tests, "
                                     f"each citing the call_id of a {test_tool} result. Run {test_tool} for your top two "
                                     "competing hypotheses, then submit again."})
                    continue
                if verifier is None:
                    inv.diagnosis = diag
                    return inv
                issues, usage = verify_claims(verifier, inv.trace, diag)
                inv.verifier_tokens += usage["tokens"]
                total = (len(diag.get("evidence", [])) + len(diag.get("rejected_hypotheses", []))
                         + len(diag.get("hypothesis_tests", [])))
                if inv.revisions == 0:
                    inv.claims_total, inv.claims_unsupported_first = total, len(issues)
                inv.claims_unsupported_final = len(issues)
                if not issues or inv.revisions >= max_revisions:
                    if issues:   # out of revisions: drop what could not be verified
                        bad = {i["claim"] for i in issues}
                        diag["evidence"] = [e for e in diag["evidence"] if e["claim"] not in bad]
                        diag["rejected_hypotheses"] = [h for h in diag["rejected_hypotheses"]
                                                       if f"{h['cause']} is ruled out: {h['why_rejected']}" not in bad]
                        if diag["root_cause"] != "insufficient_evidence" and not diag["evidence"]:
                            diag["root_cause"], diag["confidence"] = "insufficient_evidence", "low"
                    inv.diagnosis = diag
                    return inv
                inv.revisions += 1
                revise = True
                feedback = "; ".join(f"[{i['verdict']}] {i['claim'][:160]} -> {i['reason'][:200]}" for i in issues)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content":
                                 "Verification FAILED. These claims conflict with your tool results: " + feedback +
                                 ". Re-read the tool results, call more tools if needed, and submit a corrected diagnosis."})
                continue
            fn = registry.get(c["name"])
            try:
                result = fn(**args) if fn else {"error": f"unknown tool {c['name']}"}
            except (KeyError, TypeError, ValueError) as e:       # a bad argument is the model's to fix, not a crash
                result = {"error": f"{type(e).__name__}: {e}. Check the tool's parameters and try again."}
            seen_ids.add(c["id"])
            inv.trace.append({"id": c["id"], "tool": c["name"], "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps({"call_id": c["id"], "result": result}, default=str)})

    inv.diagnosis = {"root_cause": "insufficient_evidence", "confidence": "low", "evidence": [],
                     "rejected_hypotheses": [], "uncertainties": ["step budget exhausted"],
                     "recommended_actions": []}
    return inv


def _allowed_labels(specs: list[dict]) -> list[str] | None:
    for sp in specs:
        if sp["function"]["name"] == "submit_diagnosis":
            return sp["function"]["parameters"]["properties"].get("root_cause", {}).get("enum")
    return None


def _sanitize(args: dict) -> dict:
    """Coerce malformed model output into the expected shapes instead of crashing on it."""
    def objs(items, keys):
        out = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict):
                out.append(it)
            else:                                   # a bare string
                out.append({keys[0]: "", keys[1]: str(it)} if keys[0] != "claim" else {"claim": str(it), "tool_call_id": ""})
        return out
    args["evidence"] = objs(args.get("evidence"), ("claim", "tool_call_id"))
    args["rejected_hypotheses"] = objs(args.get("rejected_hypotheses"), ("cause", "why_rejected"))
    for k in ("uncertainties", "recommended_actions"):
        v = args.get(k)
        args[k] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    return args


def _validate(diag: dict, seen_ids: set[str], inv: Investigation) -> dict:
    kept, dropped = [], []
    for e in diag.get("evidence", []):
        (kept if e.get("tool_call_id") in seen_ids else dropped).append(e)
    inv.dropped_evidence = dropped
    diag["evidence"] = kept
    inv.original_root_cause = diag["root_cause"]
    if diag["root_cause"] != "insufficient_evidence" and not kept:
        diag["uncertainties"] = diag.get("uncertainties", []) + [
            f"original diagnosis '{diag['root_cause']}' cited no valid tool evidence"]
        diag["root_cause"], diag["confidence"] = "insufficient_evidence", "low"
    return diag
