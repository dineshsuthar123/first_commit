"""Verify exported evidence without starting Java, PostgreSQL or the HTTP provider."""
import argparse
from collections import Counter
import hashlib
import json
import re
import sqlite3
import zipfile

from engine.campaign import signature
from engine.evidence import canonical_outcomes, canonical_trace, validate_manifest
from engine.models import BOUNDS, CasePlan, Observation, Operation, Verdict
from engine.properties import evaluate


WORLD_RESULT = re.compile(r"^worlds/([a-f0-9]{32})/result\.json$")
WORLD_DB = re.compile(r"^worlds/([a-f0-9]{32})/provider\.sqlite$")
EVALUATED = {Verdict.PASS, Verdict.VIOLATION}
TERMINAL_CAMPAIGN = {"FINISHED", "CANCELLED", "FAILED", "INTERRUPTED"}


def _read_json(bundle, name):
    try:
        return json.loads(bundle.read(name))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid or missing {name}") from exc


def _same_case(left, right):
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _manifest_matches_case(manifest, case):
    return (
        manifest.buildDigest == case["buildDigest"]
        and manifest.plan.model_dump() == case["plan"]
        and manifest.expectedVerdict == case["verdict"]
        and manifest.expectedSignature == signature(case)
        and manifest.expectedTrace == canonical_trace(case)
        and manifest.expectedOutcomes == canonical_outcomes(case)
    )


def _validate_campaign(campaign):
    if not isinstance(campaign, dict) or campaign.get("schemaVersion") != 1:
        raise ValueError("unsupported campaign schemaVersion; expected 1")
    if not re.fullmatch(r"[a-f0-9]{32}", str(campaign.get("id", ""))):
        raise ValueError("invalid campaign id")
    if campaign.get("fixtureId") != "payment-v1" or campaign.get("bounds") != BOUNDS:
        raise ValueError("unsupported fixture or campaign bounds")
    if campaign.get("variant") not in {"local_dedup", "per_attempt_key", "mark_before", "stable_key"}:
        raise ValueError("unsupported campaign variant")
    Operation.model_validate(campaign.get("operation"))
    if campaign.get("lifecycle") not in TERMINAL_CAMPAIGN:
        raise ValueError("campaign is not terminal")
    cases = campaign.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("campaign contains no cases")
    direct_ids = [case.get("worldId") for case in cases]
    if len(set(direct_ids)) != len(direct_ids):
        raise ValueError("campaign contains duplicate world ids")
    expected_counts = dict(Counter(case.get("verdict") for case in cases))
    if campaign.get("counts") != expected_counts or campaign.get("executed") != len(cases):
        raise ValueError("campaign counts or executed total contradict its cases")
    return cases


def verify(path):
    evaluated = 0
    operational = []
    with zipfile.ZipFile(path) as bundle:
        infos = bundle.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        if sum(item.file_size for item in infos) > 100_000_000:
            raise ValueError("evidence exceeds the 100 MB verification budget")
        if "campaign.json" not in names or "checksums.json" not in names:
            raise ValueError("bundle must contain campaign.json and checksums.json")
        checksums = _read_json(bundle, "checksums.json")
        if not isinstance(checksums, dict) or not checksums:
            raise ValueError("checksums.json must contain member digests")
        if set(names) != set(checksums) | {"checksums.json"}:
            raise ValueError("unexpected or missing bundle members")
        for name, expected in checksums.items():
            if not isinstance(expected, str) or hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError(f"checksum mismatch: {name}")
        allowed_names = {"campaign.json", "replay.json"}
        unknown = set(checksums) - allowed_names - {
            name for name in checksums if WORLD_RESULT.fullmatch(name) or WORLD_DB.fullmatch(name)
        }
        if unknown:
            raise ValueError("unexpected evidence member type")

        campaign = _read_json(bundle, "campaign.json")
        direct_cases = _validate_campaign(campaign)
        referenced = {}
        supported_verdicts = {verdict.value for verdict in Verdict}

        def reference(case):
            if not isinstance(case, dict):
                raise ValueError("world result must be an object")
            world_id = case.get("worldId")
            if not re.fullmatch(r"[a-f0-9]{32}", str(world_id or "")):
                raise ValueError("invalid world id")
            if case.get("verdict") not in supported_verdicts:
                raise ValueError("unsupported world verdict")
            if case.get("lifecycle") not in {"FINISHED", "CANCELLED", "INTERRUPTED"}:
                raise ValueError("world result is not terminal")
            if not re.fullmatch(r"[a-f0-9]{64}", str(case.get("buildDigest", ""))):
                raise ValueError("invalid world build digest")
            plan = CasePlan.model_validate(case.get("plan"))
            if plan.variant != campaign["variant"]:
                raise ValueError("world plan variant contradicts campaign")
            if campaign["operation"] not in case["plan"]["operations"]:
                raise ValueError("world plan omits the campaign operation")
            if world_id in referenced and not _same_case(referenced[world_id], case):
                raise ValueError("contradictory representations for one world")
            referenced[world_id] = case

        for case in direct_cases:
            reference(case)
        reduction = campaign.get("reduction")
        if reduction is not None:
            reduced = reduction.get("case")
            if not isinstance(reduced, dict):
                raise ValueError("reduction is missing its case")
            reference(reduced)
            if (reduced.get("verdict") != Verdict.VIOLATION
                    or reduction.get("afterActions") != len(reduced["plan"]["actions"])
                    or reduction.get("signature") != signature(reduced)):
                raise ValueError("reduction summary contradicts its case")
            for trial in reduction.get("trials", []):
                world_id = trial.get("worldId")
                if world_id:
                    name = f"worlds/{world_id}/result.json"
                    if name not in checksums:
                        raise ValueError("reduction trial result is missing")
                    trial_case = _read_json(bundle, name)
                    if trial.get("verdict") != trial_case.get("verdict"):
                        raise ValueError("reduction trial contradicts its result")
                    reference(trial_case)

        result_names = {name for name in checksums if WORLD_RESULT.fullmatch(name)}
        expected_names = {f"worlds/{world_id}/result.json" for world_id in referenced}
        if result_names != expected_names:
            raise ValueError("world results do not match campaign and reduction references")
        database_names = {name for name in checksums if WORLD_DB.fullmatch(name)}
        for world_id, recorded in referenced.items():
            name = f"worlds/{world_id}/result.json"
            case = _read_json(bundle, name)
            if case.get("worldId") != world_id or not _same_case(case, recorded):
                raise ValueError("world result contradicts its campaign representation")
            if case.get("verdict") not in EVALUATED:
                operational.append({"worldId": world_id, "verdict": case.get("verdict")})
                continue
            db_name = f"worlds/{world_id}/provider.sqlite"
            if db_name not in checksums:
                raise ValueError(f"evaluated world is missing provider snapshot: {world_id}")
            db = sqlite3.connect(":memory:")
            try:
                db.row_factory = sqlite3.Row
                db.deserialize(bundle.read(db_name))
                ledger = [dict(row) for row in db.execute("SELECT * FROM captures ORDER BY effectId")]
            finally:
                db.close()
            if ledger != case["observation"]["ledger"]:
                raise ValueError("ledger snapshot differs from recorded observation")
            admitted = {event["operationId"] for event in case["events"] if event["type"] == "delivery"}
            operations = [Operation.model_validate(item) for item in case["plan"]["operations"] if item["operationId"] in admitted]
            properties = [item.model_dump() for item in evaluate(operations, Observation.model_validate(case["observation"]))]
            verdict = Verdict.VIOLATION if any(not item["passed"] for item in properties) else Verdict.PASS
            if properties != case["properties"] or verdict != case["verdict"]:
                raise ValueError("independent property evaluation differs from recorded result")
            evaluated += 1

        known_databases = {f"worlds/{world_id}/provider.sqlite" for world_id in referenced}
        if not database_names <= known_databases:
            raise ValueError("provider snapshot has no referenced world result")

        if "replay.json" in checksums:
            manifest = validate_manifest(_read_json(bundle, "replay.json"))
            evaluated_cases = [case for case in referenced.values() if case.get("verdict") in EVALUATED]
            if not any(_manifest_matches_case(manifest, case) for case in evaluated_cases):
                raise ValueError("replay manifest does not match an exported evaluated case")
        elif evaluated:
            raise ValueError("evaluated evidence is missing replay.json")

    return {
        "integrityVerified": True,
        "businessEvaluation": "evaluated" if evaluated else "not_evaluated",
        "independentlyEvaluatedWorlds": evaluated,
        "operationalWorlds": operational,
        "note": "Evidence consistency does not mean all business properties passed.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    print(json.dumps(verify(parser.parse_args().bundle), indent=2))
