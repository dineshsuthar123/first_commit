import time
import importlib
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


def wait_terminal(client, identifier):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{identifier}").json()
        if result["lifecycle"] != "RUNNING":
            return result
        time.sleep(.1)
    raise AssertionError("job did not become terminal within budget")


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
        reduced_case = reduced["result"]["case"]
        normal = saved["cases"][0]
        explicit_response = client.post("/api/replays", json={"campaignId": identifier, "caseId": normal["worldId"]})
        explicit_initial = explicit_response.json()
        assert explicit_initial["campaignId"] == identifier
        assert explicit_initial["sourceCaseId"] == normal["worldId"]
        explicit = wait_job(client, explicit_initial["id"])
        assert explicit["result"]["plan"] == normal["plan"]
        assert explicit["result"]["replayMatched"]
        fault = next(case for case in saved["cases"] if case["verdict"] == "PROPERTY_VIOLATION")
        fault_initial = client.post("/api/replays", json={"campaignId": identifier, "caseId": fault["worldId"]}).json()
        fault_replay = wait_job(client, fault_initial["id"])
        assert fault_replay["result"]["plan"] == fault["plan"]
        assert fault_replay["result"]["replayMatched"]
        repeated = wait_job(client, client.post("/api/replays", json={"campaignId": identifier}).json()["id"])
        assert repeated["result"]["replayMatched"]
        repaired_initial = client.post("/api/replays", json={"campaignId": identifier, "caseId": reduced_case["worldId"], "comparisonVariant": "stable_key"}).json()
        assert repaired_initial["sourceCaseId"] == reduced_case["worldId"]
        repaired = wait_job(client, repaired_initial["id"])
        assert repaired["result"]["verdict"] == "PASS_WITHIN_BOUNDS"
        app_module = importlib.import_module("api.app")
        foreign_id = "f" * 32
        foreign_case = explicit["result"]
        app_module.write_json(app_module.campaign_path(foreign_id), {
            "schemaVersion": 1, "id": foreign_id, "fixtureId": "payment-v1", "variant": "local_dedup",
            "operation": saved["operation"], "bounds": saved["bounds"], "lifecycle": "FINISHED",
            "cases": [foreign_case], "counts": {foreign_case["verdict"]: 1}, "executed": 1,
            "discoveredCheckpoints": saved["discoveredCheckpoints"],
        })
        assert client.post("/api/replays", json={"campaignId": identifier, "caseId": foreign_case["worldId"]}).status_code == 422
        assert client.post("/api/replays", json={"campaignId": identifier, "caseId": "invalid"}).status_code == 422
        bundle = client.get(f"/api/campaigns/{identifier}/evidence")
        assert bundle.status_code == 200 and bundle.content.startswith(b"PK")

        async def fail_replay(*_args, **_kwargs):
            raise RuntimeError("injected derived failure")
        monkeypatch.setattr(app_module, "replay", fail_replay)
        failed_id = client.post("/api/replays", json={"campaignId": identifier, "caseId": normal["worldId"]}).json()["id"]
        failed = wait_terminal(client, failed_id)
        assert failed["lifecycle"] == "FAILED"
        assert client.get(f"/api/campaigns/{identifier}").json()["lifecycle"] == "FINISHED"


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


def test_campaign_failure_marks_partial_campaign_terminal(monkeypatch):
    app_module = importlib.import_module("api.app")

    async def fail_after_save(_variant, operation, _cancel, identifier):
        app_module.write_json(app_module.campaign_path(identifier), {
            "schemaVersion": 1, "id": identifier, "fixtureId": "payment-v1", "variant": "local_dedup",
            "operation": operation.model_dump(), "bounds": app_module.BOUNDS, "lifecycle": "RUNNING",
            "cases": [], "counts": {}, "executed": 0, "discoveredCheckpoints": [],
        })
        raise RuntimeError("injected campaign failure")

    monkeypatch.setattr(app_module, "explore", fail_after_save)
    with TestClient(app) as client:
        identifier = client.post("/api/campaigns", json={}).json()["id"]
        failed = wait_terminal(client, identifier)
        assert failed["lifecycle"] == "FAILED"
        saved = client.get(f"/api/campaigns/{identifier}").json()
        assert saved["lifecycle"] == "FAILED"
        assert saved["diagnostics"] == ["RuntimeError: injected campaign failure"]
