import base64
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path
from typing import Literal
import zipfile

from pydantic import Field

from engine.campaign import signature
from engine.models import BOUNDS, PROPERTIES, CasePlan, Strict, Verdict
from engine.runner import data_root, run_case, write_json
from fixtures.payment import ROOT


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_digest():
    files = []
    for folder in ("engine", "fixtures", "provider", "worker/src", "worker/build", "worker/lib"):
        files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    files.extend([ROOT / "requirements.lock", ROOT / "worker/dependencies.lock.json"])
    return sha(encoded({p.relative_to(ROOT).as_posix(): sha(p.read_bytes().replace(b"\r\n", b"\n") if p.suffix in (".py", ".java", ".json", ".lock") else p.read_bytes()) for p in sorted(files)}))


def canonical_trace(case):
    """Normalize only OS/process coordinates; preserve effect/key identity relationships."""
    def normalize(value):
        if isinstance(value, list):
            return [normalize(x) for x in value]
        if isinstance(value, dict):
            return {k: ("confirmed_termination" if k == "returncode" else normalize(v))
                    for k, v in value.items() if k not in ("pid", "port")}
        if isinstance(value, str):
            return value.replace(case["worldId"], "WORLD")
        return value
    return normalize(case["events"])


class ReplayManifest(Strict):
    schemaVersion: Literal[1] = 1
    fixtureId: Literal["payment-v1"] = "payment-v1"
    buildDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    properties: dict[str, int]
    bounds: dict[str, int]
    plan: CasePlan
    inputs: dict
    expectedSignature: dict | None
    expectedVerdict: Literal["PASS_WITHIN_BOUNDS", "PROPERTY_VIOLATION"]
    expectedTrace: list[dict] = Field(max_length=512)
    externalOutcomes: list[dict] = Field(max_length=16)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")


def manifest_for(case):
    if case["verdict"] not in (Verdict.PASS, Verdict.VIOLATION):
        raise ValueError("only evaluated cases can define replay expectations")
    payload = {"schemaVersion": 1, "fixtureId": "payment-v1", "buildDigest": case["buildDigest"],
               "properties": PROPERTIES, "bounds": BOUNDS, "plan": case["plan"],
               "inputs": {"clock": "unused by business logic", "randomness": "unique world namespace; attemptId=world:operation:attempt"},
               "expectedSignature": signature(case), "expectedVerdict": case["verdict"],
               "expectedTrace": canonical_trace(case), "externalOutcomes": case["observation"]["ledger"]}
    payload["checksum"] = sha(encoded(payload))
    return ReplayManifest.model_validate(payload).model_dump()


def validate_manifest(raw):
    manifest = ReplayManifest.model_validate(raw)
    value = manifest.model_dump()
    checksum = value.pop("checksum")
    if sha(encoded(value)) != checksum:
        raise ValueError("manifest checksum mismatch")
    if manifest.bounds != BOUNDS or manifest.properties != PROPERTIES:
        raise ValueError("unsupported bounds or property versions")
    return manifest


async def replay(raw, comparison_variant=None, cancel=None):
    manifest = validate_manifest(raw)
    if comparison_variant is None and manifest.buildDigest != build_digest():
        return {"verdict": Verdict.DIVERGED, "diagnostics": ["same-build digest mismatch"], "replayMatched": False}
    plan = manifest.plan
    if comparison_variant:
        plan = CasePlan.model_validate({**plan.model_dump(), "variant": comparison_variant})
    result = await run_case(plan, cancel=cancel)
    result["comparison"] = comparison_variant is not None
    result["sourceBuildDigest"] = manifest.buildDigest
    result["actualBuildDigest"] = build_digest()
    if comparison_variant is None:
        matched = (result["verdict"] == manifest.expectedVerdict and signature(result) == manifest.expectedSignature
                   and canonical_trace(result) == manifest.expectedTrace)
        result["replayMatched"] = matched
        if not matched:
            result["observedVerdict"] = result["verdict"]
            # Keep operational errors visible, never recast them as a pass.
            if result["verdict"] not in (Verdict.ERROR, Verdict.INCONCLUSIVE):
                result["verdict"] = Verdict.DIVERGED
            result["diagnostics"].append("replay evidence contract did not match")
    write_json(data_root() / "replays" / f'{result["worldId"]}.json', result)
    return result


def export_bundle(campaign):
    members = {"campaign.json": encoded(campaign)}
    selected = campaign.get("reduction", {}).get("case") or next((c for c in reversed(campaign["cases"]) if c["verdict"] == Verdict.VIOLATION), None)
    selected = selected or next((c for c in campaign["cases"] if c["verdict"] == Verdict.PASS), None)
    if selected:
        members["replay.json"] = encoded(manifest_for(selected))
    cases = list(campaign["cases"])
    if campaign.get("reduction"):
        cases.append(campaign["reduction"]["case"])
    for case in cases:
        world = case["worldId"]
        members[f"worlds/{world}/result.json"] = encoded(case)
        ledger_path = data_root() / "worlds" / world / "provider.sqlite"
        if ledger_path.exists():
            with sqlite3.connect(ledger_path) as source, sqlite3.connect(":memory:") as snapshot:
                source.backup(snapshot)
                members[f"worlds/{world}/provider.sqlite"] = snapshot.serialize()
    members["checksums.json"] = encoded({name: sha(content) for name, content in members.items()})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, content)
    path = data_root() / "exports" / f'{campaign["id"]}-{sha(stream.getvalue())}.zip'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stream.getvalue())
    return path


def upload_bundle(path: Path, campaign_id):
    import boto3
    from botocore.exceptions import ClientError
    bucket = os.environ["EVIDENCE_BUCKET"]
    payload = path.read_bytes()
    digest = sha(payload)
    key = f"evidence/{build_digest()}/{campaign_id}/{digest}.zip"
    s3 = boto3.client("s3")
    checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=payload, IfNoneMatch="*", ContentType="application/zip",
                      ChecksumSHA256=checksum, Metadata={"sha256": digest, "campaign": campaign_id})
    except ClientError as e:
        if e.response["ResponseMetadata"]["HTTPStatusCode"] != 412:
            raise
    head = s3.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    if head.get("ChecksumSHA256") != checksum:
        raise RuntimeError("S3 checksum verification failed")
    return {"bucket": bucket, "key": key, "sha256": digest,
            "downloadUrl": s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)}
