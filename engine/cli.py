import argparse
import asyncio
import json
from pathlib import Path
import sys

from engine.campaign import explore
from engine.evidence import export_bundle, manifest_for, replay, upload_bundle
from engine.models import Operation, Verdict
from engine.reducer import reduce_case
from engine.runner import data_root, write_json


def campaign_path(identifier):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("invalid campaign ID")
    return data_root() / "campaigns" / f"{identifier}.json"


def load_campaign(identifier):
    return json.loads(campaign_path(identifier).read_text(encoding="utf-8"))


def failure_case(campaign):
    if campaign.get("reduction"):
        return campaign["reduction"]["case"]
    return next((c for c in reversed(campaign["cases"]) if c["verdict"] == Verdict.VIOLATION), None)


def campaign_exit_code(result):
    """Classify campaign completion for CI without treating missing work as success."""
    counts = result.get("counts") or {}
    executed = result.get("executed")
    if result.get("lifecycle") != "FINISHED" or not isinstance(executed, int) or executed < 1:
        return 2
    known = {verdict.value for verdict in Verdict}
    if any(name not in known or not isinstance(count, int) or count < 0 for name, count in counts.items()):
        return 2
    if sum(counts.values()) != executed:
        return 2
    if any(counts.get(verdict, 0) for verdict in (Verdict.DIVERGED, Verdict.ERROR, Verdict.INCONCLUSIVE)):
        return 2
    if counts.get(Verdict.VIOLATION, 0):
        return 1
    return 0 if counts.get(Verdict.PASS, 0) == executed else 2


async def main_async(args):
    if args.command == "campaign":
        result = await explore(args.variant, Operation(operationId=args.operation, amountMinor=args.amount))
        print(json.dumps({"id": result["id"], "counts": result["counts"], "executed": result["executed"]}))
        return campaign_exit_code(result)
    if args.command == "replay":
        result = await replay(json.loads(Path(args.manifest).read_text()), args.compare)
        print(json.dumps(result, indent=2))
        if result["verdict"] in (Verdict.DIVERGED, Verdict.ERROR, Verdict.INCONCLUSIVE):
            return 2
        return 0 if result.get("replayMatched") or result["verdict"] == Verdict.PASS else 1
    campaign = load_campaign(args.id)
    if args.command == "show":
        print(json.dumps(campaign, indent=2))
    elif args.command == "reduce":
        case = failure_case(campaign)
        if not case:
            raise ValueError("campaign has no violation")
        campaign["reduction"] = await reduce_case(case)
        write_json(campaign_path(args.id), campaign)
        print(json.dumps({k: v for k, v in campaign["reduction"].items() if k != "case"}, indent=2))
    elif args.command == "manifest":
        case = failure_case(campaign) or campaign["cases"][0]
        write_json(Path(args.output), manifest_for(case))
        print(args.output)
    elif args.command == "export":
        path = export_bundle(campaign)
        print(json.dumps(upload_bundle(path, args.id) if args.s3 else {"path": str(path)}))
    return 0


def main():
    parser = argparse.ArgumentParser(description="StateProof: bounded retry correctness benchmark")
    subs = parser.add_subparsers(dest="command", required=True)
    campaign = subs.add_parser("campaign")
    campaign.add_argument("--variant", choices=["local_dedup", "per_attempt_key", "mark_before", "stable_key"], default="local_dedup")
    campaign.add_argument("--operation", default="capture-001")
    campaign.add_argument("--amount", type=int, default=100000)
    for name in ("show", "reduce", "manifest", "export"):
        p = subs.add_parser(name)
        p.add_argument("id")
        if name == "manifest":
            p.add_argument("--output", default="data/replay.json")
        if name == "export":
            p.add_argument("--s3", action="store_true")
    p = subs.add_parser("replay")
    p.add_argument("manifest")
    p.add_argument("--compare", choices=["stable_key", "local_dedup", "per_attempt_key", "mark_before"])
    try:
        return asyncio.run(main_async(parser.parse_args()))
    except (ValueError, OSError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
