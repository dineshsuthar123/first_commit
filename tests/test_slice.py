import asyncio

from engine.models import Action, CasePlan, FaultPlan, Operation, Verdict
from engine.runner import run_case


def plan(variant="local_dedup", checkpoint=None, duplicate=True):
    op = Operation()
    fault = FaultPlan(operationId=op.operationId, checkpoint=checkpoint, attempt=1) if checkpoint else None
    actions = [Action(operationId=op.operationId, attempt=1, fault=fault)]
    if duplicate:
        actions.append(Action(operationId=op.operationId, attempt=2))
    return CasePlan(variant=variant, operations=[op], actions=actions)


def test_real_failure_and_repair():
    normal = asyncio.run(run_case(plan(duplicate=False)))
    duplicate = asyncio.run(run_case(plan()))
    broken = asyncio.run(run_case(plan(checkpoint="after_external_call")))
    fixed = asyncio.run(run_case(plan("stable_key", "after_external_call")))
    assert normal["verdict"] == duplicate["verdict"] == fixed["verdict"] == Verdict.PASS, [normal, duplicate, fixed]
    assert broken["verdict"] == Verdict.VIOLATION, broken
    assert sum(r["amountMinor"] for r in broken["observation"]["ledger"]) == 200000
    killed = next(e for e in broken["events"] if e["type"] == "worker_terminated")
    assert killed["returncode"] != 0 and len(killed["survivingLedger"]) == 1
    assert len(fixed["observation"]["ledger"]) == 1
    assert len({r["worldId"] for r in [normal, duplicate, broken, fixed]}) == 4
