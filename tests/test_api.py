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
