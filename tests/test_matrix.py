import asyncio
import json

import pytest

from engine.campaign import explore
from engine.models import CasePlan, Operation, Verdict
from engine.runner import data_root, run_case, write_json
from provider.server import charge, connect
from tests.test_slice import plan
from fixtures.payment import PaymentFixture
import sys
import os
import subprocess
from threading import Event
from pathlib import Path
from fixtures.payment import ROOT


@pytest.mark.parametrize("variant,property_name", [("local_dedup", "no_duplicate_effect"),
    ("per_attempt_key", "no_duplicate_effect"), ("mark_before", "correct_completion"), ("stable_key", None)])
def test_observed_matrix(variant, property_name):
    campaign = asyncio.run(explore(variant))
    write_json(data_root() / "validation" / f"matrix-{variant}.json", campaign)
    assert len(campaign["discoveredCheckpoints"]) == 6
    assert all(c["verdict"] == Verdict.PASS for c in campaign["cases"][:2])
    assert not any(c["verdict"] in (Verdict.ERROR, Verdict.INCONCLUSIVE, Verdict.DIVERGED) for c in campaign["cases"])
    if property_name:
        assert any(not p["passed"] and p["property"] == property_name for c in campaign["cases"] for p in c["properties"])
    else:
        assert len(campaign["cases"]) == 8
        assert all(c["verdict"] == Verdict.PASS for c in campaign["cases"])


def test_provider_durable_dedup_and_conflict(tmp_path):
    path = tmp_path / "provider.sqlite"
    request = {**Operation().model_dump(), "idempotencyKey": "logical-key"}
    with connect(path) as db:
        assert charge(db, request.copy())[0] == 201
    with connect(path) as db:
        assert charge(db, request.copy())[1]["deduplicated"]
        assert charge(db, {**request, "amountMinor": 200})[0] == 409
        assert charge(db, {**request, "operationId": "different"})[0] == 409
        assert db.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1


def test_boundaries_dependencies_and_changed_configuration(monkeypatch):
    missing = asyncio.run(run_case(plan(checkpoint="nonexistent")))
    assert missing["verdict"] == Verdict.DIVERGED
    custom = plan("stable_key", "after_external_call").model_dump()
    custom["operations"][0].update(operationId="second-capture", amountMinor=22222)
    for a in custom["actions"]:
        a["operationId"] = "second-capture"
        if a["fault"]:
            a["fault"]["operationId"] = "second-capture"
    result = asyncio.run(run_case(CasePlan.model_validate(custom)))
    assert result["verdict"] == Verdict.PASS
    assert result["observation"]["ledger"][0]["amountMinor"] == 22222
    monkeypatch.setenv("PGPORT", "1")
    assert asyncio.run(run_case(plan()))["verdict"] == Verdict.ERROR


def test_unexpected_exit_and_cancellation():
    class Exits(PaymentFixture):
        def worker_command(self):
            return [sys.executable, "-c", "raise SystemExit(7)"]
    crashed = asyncio.run(run_case(plan(), fixture=Exits()))
    assert crashed["verdict"] == Verdict.ERROR
    assert any("unexpected process exit" in d for d in crashed["diagnostics"])
    cancel = Event()
    cancel.set()
    cancelled = asyncio.run(run_case(plan(), cancel=cancel))
    assert cancelled["lifecycle"] == "CANCELLED"
    assert cancelled["verdict"] == Verdict.INCONCLUSIVE


def test_breaking_stable_key_is_detected_without_changing_variant(tmp_path):
    original = (ROOT / "worker/src/PaymentWorker.java").read_text()
    broken = original.replace('"stateproof:payment:v1:" + op.get("operationId").getAsString()',
                              '"stateproof:payment:v1:" + delivery.get("attemptId").getAsString()')
    assert broken != original
    source = tmp_path / "PaymentWorker.java"
    source.write_text(broken)
    javac = str(Path(os.environ["JAVA_HOME"]) / "bin/javac") if os.getenv("JAVA_HOME") else "javac"
    subprocess.run([javac, "--release", "21", "-cp", str(ROOT / "worker/lib/*"), "-d", str(tmp_path), str(source)], check=True)
    class MutatedStable(PaymentFixture):
        def worker_command(self):
            command = super().worker_command()
            command[2] = os.pathsep.join([str(tmp_path), str(ROOT / "worker/lib/*")])
            return command
    case = asyncio.run(run_case(plan("stable_key", "after_external_call"), fixture=MutatedStable()))
    assert case["plan"]["variant"] == "stable_key"
    assert case["verdict"] == Verdict.VIOLATION
    assert any(p["property"] == "no_duplicate_effect" and not p["passed"] for p in case["properties"])


def test_protocol_timeout_is_inconclusive():
    class SilentWorker(PaymentFixture):
        def worker_command(self):
            return [sys.executable, "-c", "import time;time.sleep(60)"]
    result = asyncio.run(run_case(plan(), fixture=SilentWorker()))
    assert result["verdict"] == Verdict.INCONCLUSIVE
    assert any("deadline" in d for d in result["diagnostics"])
