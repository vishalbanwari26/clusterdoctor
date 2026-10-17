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


def test_tool_argument_error_goes_back_to_the_model_not_a_crash():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    chat = scripted(
        {"content": None, "tool_calls": [call("x1", "latency_by_input_size", window="nonsense_window")]},
        {"content": None, "tool_calls": [call("x2", "submit_diagnosis", root_cause="insufficient_evidence", confidence="low",
                                              evidence=[], rejected_hypotheses=[], uncertainties=["bad arg"], recommended_actions=[])]})
    inv = investigate(chat, tools, "p95 up")
    assert "error" in str(inv.trace[0]["result"]).lower() and inv.diagnosis["root_cause"] == "insufficient_evidence"


def test_incomplete_submit_is_sent_back_then_defaults():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    bad = call("x1", "submit_diagnosis", confidence="high")          # no root_cause
    good = call("x2", "submit_diagnosis", root_cause="prompt_expansion", confidence="high", evidence=[],
                rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    inv = investigate(scripted({"content": None, "tool_calls": [bad]}, {"content": None, "tool_calls": [good]}), tools, "x")
    assert inv.schema_retries == 1
    inv2 = investigate(scripted(*[{"content": None, "tool_calls": [call(f"y{i}", "submit_diagnosis", confidence="high")]} for i in range(3)]), tools, "x")
    assert inv2.diagnosis["root_cause"] == "insufficient_evidence" and inv2.schema_retries == 2


def test_malformed_evidence_shapes_do_not_crash():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    sub = call("x1", "submit_diagnosis", root_cause="prompt_expansion", confidence="high", evidence=["input grew 6x", "latency up"],
               rejected_hypotheses=["retry_storm: no retries"], uncertainties="none", recommended_actions=[])
    inv = investigate(scripted({"content": None, "tool_calls": [sub]}), tools, "x")
    assert inv.diagnosis["root_cause"] == "insufficient_evidence"        # strings carry no valid citation, so no evidence survives
    assert inv.diagnosis["uncertainties"][0].startswith("none") or inv.diagnosis["uncertainties"]


def test_bad_label_and_uncited_evidence_are_sent_back_before_downgrading():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    first = call("x2", "compare_windows")
    free_text = call("x3", "submit_diagnosis", root_cause="The app sent huge prompts after a deploy", confidence="high",
                     evidence=[{"claim": "tokens 6x", "tool_call_id": "call_1"}], rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    uncited = call("x4", "submit_diagnosis", root_cause="prompt_expansion", confidence="high",
                   evidence=[{"claim": "tokens 6x", "tool_call_id": ""}], rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    good = call("x5", "submit_diagnosis", root_cause="prompt_expansion", confidence="high",
                evidence=[{"claim": "tokens 6x", "tool_call_id": "call_1"}], rejected_hypotheses=[], uncertainties=[], recommended_actions=[])
    chat = scripted({"content": None, "tool_calls": [first]}, {"content": None, "tool_calls": [free_text]},
                    {"content": None, "tool_calls": [uncited]}, {"content": None, "tool_calls": [good]})
    inv = investigate(chat, tools, "p95 up")
    assert (inv.label_retries, inv.citation_retries) == (1, 1)
    assert inv.diagnosis["root_cause"] == "prompt_expansion"


def test_label_retries_exhausted_falls_back_to_insufficient_evidence():
    from clusterdoctor.agent import investigate
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    bad = [{"content": None, "tool_calls": [call(f"b{i}", "submit_diagnosis", root_cause="free text", confidence="high", evidence=[],
                                                 rejected_hypotheses=[], uncertainties=[], recommended_actions=[])]} for i in range(3)]
    inv = investigate(scripted(*bad), tools, "x")
    assert inv.label_retries == 2 and inv.diagnosis["root_cause"] == "insufficient_evidence"


def _report(label="prompt_expansion", conf="high", cite="pack_windows"):
    return json.dumps({"root_cause": label, "confidence": conf, "evidence": [{"claim": "input tokens grew", "tool_call_id": cite}],
                       "rejected_hypotheses": [], "uncertainties": [], "recommended_actions": []})


class _Esc:
    diagnosis = {"root_cause": "retry_storm", "confidence": "high", "evidence": []}
    prompt_tokens = completion_tokens = verifier_tokens = 1


def _hy(replies, verdicts):
    from clusterdoctor.hybrid import hybrid_investigate
    rep, ver = iter(replies), iter(verdicts)
    chat = lambda m, t: {"content": next(rep), "prompt_tokens": 10, "completion_tokens": 5}
    verifier = lambda m, t: {"content": next(ver), "prompt_tokens": 1, "completion_tokens": 1}
    return hybrid_investigate(chat, verifier, Tools(seeded_store(), (0, 100), (100, 200)), "p95 up", lambda: _Esc())


def test_hybrid_confident_checked_answer_does_not_escalate():
    out = _hy([_report()], ["[]"])
    assert not out["escalated"] and out["diagnosis"]["root_cause"] == "prompt_expansion" and out["tokens"]["calls"] == 1


def test_hybrid_escalates_on_low_confidence_abstention_and_failed_claim_check():
    assert _hy([_report(conf="low")], ["[]"])["reasons"] == ["low_confidence"]
    assert _hy([_report(label="insufficient_evidence", conf="medium")], ["[]"])["reasons"] == ["abstained"]
    bad = '[{"id": 0, "verdict": "contradicted", "reason": "no"}]'
    out = _hy([_report(), _report()], [bad, bad])                    # one revision, still failing
    assert out["escalated"] and out["reasons"] == ["claim_check_failed"] and out["tokens"]["calls"] == 2


def test_hybrid_one_revision_can_fix_a_failed_check_and_bad_format_is_retried_once():
    bad = '[{"id": 0, "verdict": "contradicted", "reason": "no"}]'
    out = _hy([_report(), _report()], [bad, "[]"])
    assert not out["escalated"] and out["tokens"]["calls"] == 2
    out = _hy(["not json", _report()], ["[]"])                       # bad format once, then fine
    assert not out["escalated"] and out["tokens"]["calls"] == 2
    assert _hy(["not json", "still not json"], [])["reasons"] == ["unparseable"]


def test_effect_split_separates_a_factor_that_varies_from_one_that_does_not():
    from clusterdoctor.evidence import effect_split
    s = Store(":memory:")
    for i in range(60):                                   # baseline: small prompts, no retries, fast
        s.add_request(Request(i, "v1", "m", 200, 50, 0.4, .3, 200, retries=0, concurrency=1))
    for i in range(60, 160):                              # incident: prompt size constant, retries 0 or 2, latency driven by retries
        r = 2 if i % 3 == 0 else 0
        s.add_request(Request(i, "v2", "m", 4000, 50, 0.5 + 2.0 * r, .3, 200, retries=r, concurrency=1))
    e = effect_split(Tools(s, (0, 60), (60, 160)))
    f = {x["factor"]: x for x in e["factors"]}
    assert f["retries"]["varies_in_incident_window"] and not f["prompt_size"]["varies_in_incident_window"]
    assert abs(f["retries"]["slope"] - 2.0) < 0.05 and f["retries"]["explained_rise_s"] > 0.8
    assert e["r2_within_window"] > 0.99


def test_workflow_to_dict_matches_the_dashboard_shape_and_strict_schema_restricts_citations():
    from clusterdoctor.hybrid import hybrid_investigate, inference_pack, report_schema
    from clusterdoctor.replay import workflow_to_dict
    tools = Tools(seeded_store(), (0, 100), (100, 200))
    pack = inference_pack(tools)
    sch = report_schema(sorted(pack), ["prompt_expansion", "insufficient_evidence"])["json_schema"]["schema"]
    assert sch["properties"]["evidence"]["items"]["properties"]["tool_call_id"]["enum"] == sorted(pack)
    rep = iter([_report()]); ver = iter(["[]"])
    out = hybrid_investigate(lambda m, t, **k: {"content": next(rep), "prompt_tokens": 1, "completion_tokens": 1},
                             lambda m, t: {"content": next(ver), "prompt_tokens": 1, "completion_tokens": 1},
                             tools, "x", lambda: None, pack=pack, strict=True)
    d = workflow_to_dict(out, 1.0)
    assert {"diagnosis", "trace", "claims_total", "tokens", "cost_usd", "model", "workflow"} <= set(d)
    assert d["workflow"]["escalated"] is False and d["trace"][0]["id"].startswith("pack_")


def test_failed_strict_call_is_retried_without_the_strict_schema():
    from clusterdoctor.hybrid import hybrid_investigate, inference_pack
    tools = Tools(seeded_store(), (0, 100), (100, 200)); calls = []
    def chat(m, t, response_format=None, max_tokens=None):
        calls.append(response_format is not None)
        return {"content": "" if len(calls) == 1 else _report(), "prompt_tokens": 1, "completion_tokens": 1}
    ver = iter(["[]"])
    out = hybrid_investigate(chat, lambda m, t: {"content": next(ver), "prompt_tokens": 1, "completion_tokens": 1},
                             tools, "x", lambda: None, pack=inference_pack(tools), strict=True)
    assert calls == [True, False] and not out["escalated"]
