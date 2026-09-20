"""Verify exported evidence without starting Java, PostgreSQL or the HTTP provider."""
import argparse
import hashlib
import json
import sqlite3
import zipfile

from engine.evidence import validate_manifest
from engine.models import Observation, Operation, Verdict
from engine.properties import evaluate


def verify(path):
    evaluated = 0
    operational = []
    with zipfile.ZipFile(path) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 100_000_000:
            raise ValueError("evidence exceeds the 100 MB verification budget")
        checksums = json.loads(bundle.read("checksums.json"))
        if set(bundle.namelist()) != set(checksums) | {"checksums.json"}:
            raise ValueError("unexpected or missing bundle members")
        for name, expected in checksums.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise ValueError(f"checksum mismatch: {name}")
        if "replay.json" in checksums:
            validate_manifest(json.loads(bundle.read("replay.json")))
        cases = [n for n in checksums if n.endswith("/result.json")]
        for name in cases:
            case = json.loads(bundle.read(name))
            if case["verdict"] not in (Verdict.PASS, Verdict.VIOLATION):
                operational.append({"worldId": case["worldId"], "verdict": case["verdict"]})
                continue
            db = sqlite3.connect(":memory:")
            try:
                db.row_factory = sqlite3.Row
                db.deserialize(bundle.read(name.replace("result.json", "provider.sqlite")))
                ledger = [dict(row) for row in db.execute("SELECT * FROM captures ORDER BY effectId")]
            finally:
                db.close()
            if ledger != case["observation"]["ledger"]:
                raise ValueError("ledger snapshot differs from recorded observation")
            admitted = {e["operationId"] for e in case["events"] if e["type"] == "delivery"}
            ops = [Operation.model_validate(o) for o in case["plan"]["operations"] if o["operationId"] in admitted]
            properties = [p.model_dump() for p in evaluate(ops, Observation.model_validate(case["observation"]))]
            verdict = Verdict.VIOLATION if any(not p["passed"] for p in properties) else Verdict.PASS
            if properties != case["properties"] or verdict != case["verdict"]:
                raise ValueError("independent property evaluation differs from recorded result")
            evaluated += 1
    return {"integrityVerified": True, "independentlyEvaluatedWorlds": evaluated,
            "operationalWorlds": operational, "note": "Evidence consistency does not mean all business properties passed."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    print(json.dumps(verify(parser.parse_args().bundle), indent=2))
