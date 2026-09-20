import asyncio
import copy
import json
import zipfile

import pytest

from engine.campaign import explore
from engine.evidence import encoded, export_bundle, manifest_for, replay, sha, validate_manifest
from engine.models import Verdict
from engine.reducer import reduce_case
from engine.runner import run_case
from tests.test_slice import plan


def reseal(manifest):
    manifest["checksum"] = sha(encoded({k: v for k, v in manifest.items() if k != "checksum"}))
    return manifest


def test_reduction_replay_and_evidence():
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
    with zipfile.ZipFile(export_bundle(campaign)) as bundle:
        checksums = json.loads(bundle.read("checksums.json"))
        assert all(sha(bundle.read(name)) == digest for name, digest in checksums.items())
        assert validate_manifest(json.loads(bundle.read("replay.json")))


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
