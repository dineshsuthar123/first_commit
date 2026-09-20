import time
import pytest

from fastapi.testclient import TestClient

from api.app import app


@pytest.fixture(autouse=True)
def isolate_api_storage(monkeypatch, tmp_path):
    # A TestClient lifespan must never reconcile the live server's job files.
    monkeypatch.setenv("STATEPROOF_DATA", str(tmp_path))


def wait_job(client, identifier):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{identifier}").json()
        if result["lifecycle"] != "RUNNING":
            assert result["lifecycle"] == "FINISHED", result
            return result
        time.sleep(.1)
    raise AssertionError("job did not finish within budget")


def test_real_api_workflow(monkeypatch):
    monkeypatch.delenv("STATEPROOF_TOKEN", raising=False)
    monkeypatch.setenv("STATEPROOF_READ_ONLY", "0")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/fixtures").json()["fixtures"][0]["seededBenchmark"]
        response = client.post("/api/campaigns", json={"variant": "local_dedup"})
        assert response.status_code == 202
        identifier = response.json()["id"]
        assert client.post("/api/campaigns", json={}).status_code == 409
        wait_job(client, identifier)
        saved = client.get(f"/api/campaigns/{identifier}").json()
        assert saved["counts"]["PROPERTY_VIOLATION"] > 0
        events = client.get(f"/api/campaigns/{identifier}/events").json()
        assert any(e["type"] == "worker_terminated" for e in events["events"])
        reduced = wait_job(client, client.post(f"/api/campaigns/{identifier}/reduce").json()["id"])
        assert reduced["result"]["oneMinimal"]
        repeated = wait_job(client, client.post("/api/replays", json={"campaignId": identifier}).json()["id"])
        assert repeated["result"]["replayMatched"]
        repaired = wait_job(client, client.post("/api/replays", json={"campaignId": identifier, "comparisonVariant": "stable_key"}).json()["id"])
        assert repaired["result"]["verdict"] == "PASS_WITHIN_BOUNDS"
        bundle = client.get(f"/api/campaigns/{identifier}/evidence")
        assert bundle.status_code == 200 and bundle.content.startswith(b"PK")


def test_public_access_and_validation(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setenv("STATEPROOF_READ_ONLY", "1")
        assert client.post("/api/campaigns", json={}).status_code == 403
        monkeypatch.setenv("STATEPROOF_READ_ONLY", "0")
        monkeypatch.setenv("STATEPROOF_TOKEN", "test-only")
        assert client.post("/api/campaigns", json={}).status_code == 401
        headers = {"Authorization": "Bearer test-only"}
        assert client.post("/api/campaigns", json={"command": "not-allowed"}, headers=headers).status_code == 422
        assert client.post("/api/campaigns", json={"operation": {"amountMinor": -1}}, headers=headers).status_code == 422
        assert client.post("/api/campaigns", json={}, headers={**headers, "Origin": "https://other.example"}).status_code == 403
        assert client.get("/api/campaigns/invalid").status_code == 404
