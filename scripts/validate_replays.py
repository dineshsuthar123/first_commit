"""Measured 30+30 fresh-world replay gate. Stores every run, not just a claim."""
import asyncio
import json
import platform
import subprocess

from engine.campaign import explore
from engine.evidence import build_digest, export_bundle, manifest_for, replay
from engine.models import Verdict
from engine.reducer import reduce_case
from engine.runner import data_root, write_json


async def main():
    campaign = await explore()
    campaign["reduction"] = await reduce_case(campaign["cases"][-1])
    assert campaign["reduction"]["oneMinimal"]
    manifest = manifest_for(campaign["reduction"]["case"])
    out = data_root() / "validation"
    write_json(out / "replay.json", manifest)
    results = []
    for index in range(30):
        for variant in (None, "stable_key"):
            result = await replay(manifest, variant)
            results.append({"index": index + 1, "variant": variant or manifest["plan"]["variant"],
                            "worldId": result.get("worldId"), "verdict": result["verdict"],
                            "matched": result.get("replayMatched"), "elapsedSeconds": result.get("elapsedSeconds")})
            print(json.dumps(results[-1]), flush=True)
    report = {"buildDigest": build_digest(), "python": platform.python_version(), "platform": platform.platform(),
              "java": subprocess.run(["java", "-version"], capture_output=True, text=True).stderr,
              "faultyMatched": sum(r["matched"] is True for r in results),
              "fixedPassed": sum(r["variant"] == "stable_key" and r["verdict"] == Verdict.PASS for r in results),
              "results": results}
    write_json(out / "replay-validation.json", report)
    write_json(data_root() / "campaigns" / f'{campaign["id"]}.json', campaign)
    print(export_bundle(campaign), flush=True)
    assert report["faultyMatched"] == report["fixedPassed"] == 30, report


if __name__ == "__main__":
    asyncio.run(main())
