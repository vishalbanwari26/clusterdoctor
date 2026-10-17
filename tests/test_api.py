import json
import pytest
from fastapi.testclient import TestClient

from clusterdoctor import api

pytestmark = pytest.mark.skipif(not api._ids(), reason="no replays built")
client = TestClient(api.app)


def test_list_hides_ground_truth():
    rows = client.get("/api/incidents").json()
    assert rows and all("truth" not in r for r in rows)


def test_detail_and_truth_endpoint():
    rid = client.get("/api/incidents").json()[0]["id"]
    d = client.get(f"/api/incidents/{rid}").json()
    assert d["id"] == rid and "chart" in d and "truth" not in d and "telemetry" not in d
    assert "root_cause" in client.get(f"/api/incidents/{rid}/truth").json()


def test_unknown_and_traversal_are_404():
    assert client.get("/api/incidents/nope").status_code == 404
    assert client.get("/api/nope").status_code == 404
    for url in ("/api/incidents/..%2F..%2Fpyproject", "/../pyproject.toml", "/%2e%2e/pyproject.toml"):
        assert "[project]" not in client.get(url).text      # never serves files outside the data/web dirs


def test_live_rerun_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CD_ALLOW_LIVE", raising=False)
    rid = client.get("/api/incidents").json()[0]["id"]
    assert client.post(f"/api/incidents/{rid}/rerun").status_code == 403


def _stub_live(monkeypatch, fail=False):
    from clusterdoctor import agent, replay
    from clusterdoctor.agent import Investigation
    monkeypatch.setenv("CD_ALLOW_LIVE", "1"); monkeypatch.setenv("NEBIUS_API_KEY", "test-key-not-real")
    monkeypatch.setattr(agent, "nemotron_chat", lambda *a, **k: None)
    def run(*a, **k):
        if fail:
            raise RuntimeError("secret-looking provider detail test-key-not-real")
        return Investigation(diagnosis={"root_cause": "retry_storm", "confidence": "high", "evidence": [],
                                        "rejected_hypotheses": [], "uncertainties": [], "recommended_actions": []})
    monkeypatch.setattr(replay, "run_app_investigation", run)
    monkeypatch.setattr(replay, "run_gpu_investigation", run)
    from clusterdoctor.limits import LiveGuard
    monkeypatch.setattr(api, "guard", LiveGuard(daily_cap=3, per_ip=1, max_concurrent=2))


def test_live_rerun_enforces_per_ip_limit(monkeypatch):
    _stub_live(monkeypatch)
    rid = client.get("/api/incidents").json()[0]["id"]
    ok = client.post(f"/api/incidents/{rid}/rerun", headers={"x-forwarded-for": "5.5.5.5"})
    assert ok.status_code == 200 and ok.json()["diagnosis"]["root_cause"] == "retry_storm"
    again = client.post(f"/api/incidents/{rid}/rerun", headers={"x-forwarded-for": "5.5.5.5"})
    assert again.status_code == 429 and "per visitor" in again.json()["detail"]
    assert client.post(f"/api/incidents/{rid}/rerun", headers={"x-forwarded-for": "6.6.6.6"}).status_code == 200


def test_live_failure_does_not_leak_details(monkeypatch):
    _stub_live(monkeypatch, fail=True)
    rid = client.get("/api/incidents").json()[0]["id"]
    r = client.post(f"/api/incidents/{rid}/rerun", headers={"x-forwarded-for": "7.7.7.7"})
    assert r.status_code == 502 and "test-key-not-real" not in r.text and "RuntimeError" in r.text


def test_real_incidents_are_listed_in_their_own_group_with_attribution():
    rows = {r["id"]: r for r in client.get("/api/incidents").json()}
    if "real-xid94-a" not in rows:
        pytest.skip("real replays not built")
    assert rows["real-xid94-a"]["group"] == "Real GPU data (AcmeTrace Kalos)"
    d = client.get("/api/incidents/real-xid94-a").json()
    assert d["chart"]["simulated"] is False and "CC-BY" in d["attribution"]["license"]
    assert client.get("/api/incidents/real-xid94-a/truth").json()["real"] is True
