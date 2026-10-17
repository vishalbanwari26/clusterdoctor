import json
import random

from clusterdoctor.agent import investigate
from clusterdoctor.store import Store, Request
from clusterdoctor.tools import Tools


def seeded_store():
    s = Store(":memory:")
    rng = random.Random(2)
    for i in range(100):
        s.add_request(Request(i, "v1", "m", 500, 100, 2 + rng.uniform(-.2, .2), .3, 200, source="simulated"))
    for i in range(100, 200):
        s.add_request(Request(i, "v2", "m", 3000, 100, 8 + rng.uniform(-.2, .2), .3, 200, source="simulated"))
    s.add_event(100, "deploy", "retrieval top_k 2 -> 40")
    return s


def scripted(*turns):
    it = iter(turns)
    return lambda messages, tools: next(it)


def call(i, name, **args):
    return {"id": i, "name": name, "arguments": json.dumps(args)}


def test_valid_diagnosis_is_kept():
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    chat = scripted(
        {"content": None, "tool_calls": [call("x1", "compare_windows")]},
        {"content": None, "tool_calls": [call("x2", "submit_diagnosis", root_cause="prompt_expansion",
            confidence="high", evidence=[{"claim": "input tokens 6x", "tool_call_id": "call_1"}],
            rejected_hypotheses=[], uncertainties=[], recommended_actions=["lower top_k"])]})
    inv = investigate(chat, tools, "p95 up")
    assert inv.diagnosis["root_cause"] == "prompt_expansion"
    assert inv.trace[0]["result"]["incident"]["avg_input_tokens"] == 3000


def test_fabricated_evidence_downgrades_diagnosis():
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    chat = scripted({"content": None, "tool_calls": [call("c9", "submit_diagnosis", root_cause="provider_side",
        confidence="high", evidence=[{"claim": "provider is slow", "tool_call_id": "never-called"}],
        rejected_hypotheses=[], uncertainties=[], recommended_actions=[])]})
    inv = investigate(chat, tools, "p95 up")
    assert inv.diagnosis["root_cause"] == "insufficient_evidence"
    assert len(inv.dropped_evidence) == 1


def test_step_budget_gives_insufficient_evidence():
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    chat = lambda m, t: {"content": "thinking", "tool_calls": []}
    inv = investigate(chat, tools, "p95 up", max_steps=3)
    assert inv.diagnosis["root_cause"] == "insufficient_evidence"


def test_verifier_contradiction_triggers_revision():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    bad = call("x2", "submit_diagnosis", root_cause="prompt_expansion", confidence="high",
               evidence=[{"claim": "latency is 40s", "tool_call_id": "call_1"}],
               rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    good = call("x3", "submit_diagnosis", root_cause="prompt_expansion", confidence="high",
                evidence=[{"claim": "input tokens 6x", "tool_call_id": "call_1"}],
                rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    chat = scripted({"content": None, "tool_calls": [call("x1", "compare_windows")]},
                    {"content": None, "tool_calls": [bad]}, {"content": None, "tool_calls": [good]})
    verdicts = iter([
        '[{"id": 0, "verdict": "contradicted", "reason": "p95 is 8s"}]',
        '[{"id": 0, "verdict": "supported", "reason": "ok"}]'])
    verifier = lambda m, t: {"content": next(verdicts), "prompt_tokens": 10, "completion_tokens": 5}
    inv = investigate(chat, tools, "p95 up", verifier=verifier)
    assert inv.revisions == 1 and inv.claims_unsupported_first == 1 and inv.claims_unsupported_final == 0
    assert inv.diagnosis["evidence"][0]["claim"] == "input tokens 6x"
