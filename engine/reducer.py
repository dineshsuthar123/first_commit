from pydantic import ValidationError

from engine.campaign import signature
from engine.models import CasePlan, Verdict
from engine.runner import run_case


async def reduce_case(original, cancel=None):
    target = signature(original)
    if original["verdict"] != Verdict.VIOLATION or target is None:
        raise ValueError("reduction requires an evaluated property violation")
    current = original
    attempts = []
    incomplete = False
    while True:
        changed = False
        actions = current["plan"]["actions"]
        for index in range(len(actions)):
            if cancel and cancel.is_set():
                incomplete = True
                break
            candidate = {**current["plan"], "actions": actions[:index] + actions[index + 1:]}
            used = {a["operationId"] for a in candidate["actions"]}
            candidate["operations"] = [o for o in candidate["operations"] if o["operationId"] in used]
            try:
                plan = CasePlan.model_validate(candidate)
            except ValidationError:
                attempts.append({"actionCount": len(actions), "deleteIndex": index, "admissible": False})
                continue
            result = await run_case(plan, cancel=cancel)
            same = result["verdict"] == Verdict.VIOLATION and signature(result) == target
            attempts.append({"actionCount": len(actions), "deleteIndex": index, "admissible": True,
                             "worldId": result["worldId"], "verdict": result["verdict"], "sameViolation": same})
            if result["verdict"] not in (Verdict.PASS, Verdict.VIOLATION):
                incomplete = True
                break
            if same:
                current = result
                changed = True
                break
        if incomplete or not changed:
            break
    return {"beforeActions": len(original["plan"]["actions"]), "afterActions": len(current["plan"]["actions"]),
            "oneMinimal": not incomplete, "grammar": "single action deletion preserving consecutive attempts and admission",
            "signature": target, "trials": attempts, "case": current}
