import uuid
from collections import Counter

from engine.models import Action, BOUNDS, CasePlan, FaultPlan, Operation, Verdict
from engine.runner import data_root, run_case, write_json


def signature(case):
    for name in ("no_duplicate_effect", "correct_completion", "bounded_progress"):
        for p in case["properties"]:
            if not p["passed"] and p["property"] == name:
                return {"property": name, "version": p["version"], "operationId": p["operationId"]}
    return None


async def explore(variant="local_dedup", operation=None, cancel=None, campaign_id=None, progress=None):
    operation = operation or Operation()
    campaign_id = campaign_id or uuid.uuid4().hex
    campaign = {"schemaVersion": 1, "id": campaign_id, "fixtureId": "payment-v1", "variant": variant,
                "operation": operation.model_dump(), "bounds": BOUNDS, "lifecycle": "RUNNING",
                "cases": [], "discoveredCheckpoints": [], "counts": {}, "coverage": {
                    "method": "normal execution checkpoint enumeration",
                    "notCovered": ["unobserved recovery-only boundaries", "concurrency", "network faults", "multiple crashes"]}}

    def save():
        campaign["counts"] = dict(Counter(c["verdict"] for c in campaign["cases"]))
        campaign["executed"] = len(campaign["cases"])
        write_json(data_root() / "campaigns" / f"{campaign_id}.json", campaign)
        if progress:
            progress(campaign)

    async def execute(label, actions, operations=None):
        case = await run_case(CasePlan(variant=variant, operations=operations or [operation], actions=actions), cancel=cancel)
        case["label"] = label
        campaign["cases"].append(case)
        save()
        return case

    save()
    first = Action(operationId=operation.operationId, attempt=1)
    second = Action(operationId=operation.operationId, attempt=2)
    normal = await execute("normal delivery", [first])
    duplicate = await execute("ordinary duplicate delivery", [first, second])
    if normal["verdict"] == duplicate["verdict"] == Verdict.PASS:
        boundaries = [e for e in normal["events"] if e["type"] == "checkpoint"]
        campaign["discoveredCheckpoints"] = [e["checkpoint"] for e in boundaries]
        for boundary in boundaries:
            if cancel and cancel.is_set():
                break
            fault = FaultPlan(**{k: boundary[k] for k in ("operationId", "checkpoint", "attempt", "occurrence")})
            await execute("crash at " + fault.checkpoint, [first.model_copy(update={"fault": fault}), second])
        failure = next((c for c in campaign["cases"] if c["verdict"] == Verdict.VIOLATION), None)
        if failure and not (cancel and cancel.is_set()):
            # Useful unrelated work and its ordinary duplicate precede the failing payment.
            other_id = "unrelated-002" if operation.operationId != "unrelated-002" else "unrelated-003"
            unrelated = Operation(operationId=other_id, orderId="order-other", amountMinor=4200, currency=operation.currency)
            mixed = [Action(operationId=other_id, attempt=1), Action(operationId=other_id, attempt=2)]
            mixed += CasePlan.model_validate(failure["plan"]).actions
            await execute("mixed workload", mixed, [unrelated, operation])
    campaign["lifecycle"] = "CANCELLED" if cancel and cancel.is_set() else "FINISHED"
    save()
    return campaign
