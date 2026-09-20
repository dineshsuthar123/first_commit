import asyncio
import copy
import io
import json
import zipfile
import sqlite3

import pytest

from engine.campaign import explore
from engine.evidence import canonical_outcomes, encoded, export_bundle, manifest_for, replay, sha, validate_manifest
from engine.models import Verdict
from engine.reducer import reduce_case
from engine.runner import run_case
from tests.test_slice import plan
from scripts.verify_evidence import verify


def reseal(manifest):
    manifest["checksum"] = sha(encoded({k: v for k, v in manifest.items() if k != "checksum"}))
    return manifest


def rewrite_bundle(source, target, mutate):
    with zipfile.ZipFile(source) as bundle:
        members = {name: bundle.read(name) for name in bundle.namelist() if name != "checksums.json"}
    mutate(members)
    members["checksums.json"] = encoded({name: sha(content) for name, content in members.items()})
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in members.items():
            bundle.writestr(name, content)


def test_reduction_replay_and_evidence(tmp_path):
    campaign = asyncio.run(explore())
    mixed = campaign["cases"][-1]
    reduced = asyncio.run(reduce_case(mixed))
    assert reduced["beforeActions"] == 4 and reduced["afterActions"] == 2
    assert reduced["oneMinimal"]
    assert not any(t.get("sameViolation") for t in reduced["trials"] if t["actionCount"] == 2)
    campaign["reduction"] = reduced
    manifest = manifest_for(reduced["case"])
    assert asyncio.run(replay(manifest))["replayMatched"]
    fixed = asyncio.run(replay(manifest, "stable_key"))
    assert fixed["verdict"] == Verdict.PASS and fixed["comparison"]
    bundle_path = export_bundle(campaign)
    assert verify(bundle_path)["businessEvaluation"] == "evaluated"
    with zipfile.ZipFile(bundle_path) as bundle:
        checksums = json.loads(bundle.read("checksums.json"))
        assert all(sha(bundle.read(name)) == digest for name, digest in checksums.items())
        assert validate_manifest(json.loads(bundle.read("replay.json")))
        for name in checksums:
            if name.endswith("provider.sqlite"):
                with sqlite3.connect(":memory:") as db:
                    db.deserialize(bundle.read(name))
                    rows = db.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
                    result = json.loads(bundle.read(name.replace("provider.sqlite", "result.json")))
                    assert rows == len(result["observation"]["ledger"])

    contradictory = tmp_path / "contradictory.zip"
    def contradict_campaign(members):
        recorded = json.loads(members["campaign.json"])
        for item in recorded["cases"]:
            item["verdict"] = Verdict.PASS
        recorded["counts"] = {Verdict.PASS: len(recorded["cases"])}
        members["campaign.json"] = encoded(recorded)
    rewrite_bundle(bundle_path, contradictory, contradict_campaign)
    with pytest.raises(ValueError, match="contradicts"):
        verify(contradictory)

    missing = tmp_path / "missing.zip"
    def remove_world(members):
        name = next(name for name in members if name.endswith("/result.json"))
        members.pop(name)
        members.pop(name.replace("result.json", "provider.sqlite"), None)
    rewrite_bundle(bundle_path, missing, remove_world)
    with pytest.raises(ValueError, match="world results"):
        verify(missing)

    checksums_only = tmp_path / "checksums-only.zip"
    with zipfile.ZipFile(checksums_only, "w") as bundle:
        bundle.writestr("checksums.json", "{}")
    with pytest.raises(ValueError, match="campaign.json"):
        verify(checksums_only)

    contradictory_manifest = tmp_path / "contradictory-manifest.zip"
    def change_outcomes(members):
        manifest = json.loads(members["replay.json"])
        manifest["expectedOutcomes"] = []
        members["replay.json"] = encoded(reseal(manifest))
    rewrite_bundle(bundle_path, contradictory_manifest, change_outcomes)
    with pytest.raises(ValueError, match="manifest does not match"):
        verify(contradictory_manifest)

    operational = tmp_path / "operational.zip"
    def keep_operational_only(members):
        recorded = json.loads(members["campaign.json"])
        case = copy.deepcopy(recorded["cases"][0])
        case["verdict"] = Verdict.ERROR
        recorded.update(cases=[case], counts={Verdict.ERROR: 1}, executed=1)
        recorded.pop("reduction", None)
        members.clear()
        members["campaign.json"] = encoded(recorded)
        members[f'worlds/{case["worldId"]}/result.json'] = encoded(case)
    rewrite_bundle(bundle_path, operational, keep_operational_only)
    operational_result = verify(operational)
    assert operational_result["businessEvaluation"] == "not_evaluated"
    assert operational_result["independentlyEvaluatedWorlds"] == 0


def test_invalid_or_incompatible_manifest_never_passes():
    case = asyncio.run(run_case(plan(checkpoint="after_external_call")))
    manifest = manifest_for(case)
    corrupt = copy.deepcopy(manifest)
    corrupt["plan"]["operations"][0]["amountMinor"] = 1
    with pytest.raises(ValueError, match="checksum"):
        validate_manifest(corrupt)
    mismatch = reseal({**manifest, "buildDigest": "0" * 64})
    assert asyncio.run(replay(mismatch))["verdict"] == Verdict.DIVERGED
    missing = copy.deepcopy(manifest)
    missing["plan"]["actions"][0]["fault"]["checkpoint"] = "missing_site"
    assert asyncio.run(replay(reseal(missing)))["verdict"] == Verdict.DIVERGED


def test_replay_rejects_old_schema_and_matches_durable_outcomes(monkeypatch):
    case = asyncio.run(run_case(plan(checkpoint="after_external_call")))
    manifest = manifest_for(case)
    old = {**manifest, "schemaVersion": 1}
    with pytest.raises(ValueError, match="schemaVersion"):
        validate_manifest(reseal(old))

    async def recorded_result(*_args, **_kwargs):
        return copy.deepcopy(case)

    monkeypatch.setattr("engine.evidence.run_case", recorded_result)
    contradictory = copy.deepcopy(manifest)
    contradictory["expectedOutcomes"] = []
    result = asyncio.run(replay(reseal(contradictory)))
    assert result["verdict"] == Verdict.DIVERGED
    assert not result["replayMatched"]


def test_per_attempt_outcomes_normalize_only_world_namespace():
    case = asyncio.run(run_case(plan(variant="per_attempt_key", checkpoint="after_external_call")))
    moved = copy.deepcopy(case)
    moved["worldId"] = "f" * 32
    moved["observation"]["ledger"] = [
        {**row, "idempotencyKey": row["idempotencyKey"].replace(case["worldId"], moved["worldId"])}
        for row in case["observation"]["ledger"]
    ]
    assert canonical_outcomes(case) == canonical_outcomes(moved)
    changed = copy.deepcopy(moved)
    changed["observation"]["ledger"][0]["amountMinor"] += 1
    assert canonical_outcomes(case) != canonical_outcomes(changed)
