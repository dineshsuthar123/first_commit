from engine.models import Observation, Operation, PropertyResult


def evaluate(operations: list[Operation], observation: Observation) -> list[PropertyResult]:
    """Only the admitted contract and durable evidence enter this evaluator."""
    if not observation.dependenciesHealthy:
        raise ValueError("cannot evaluate without healthy dependencies and complete evidence")
    results = []
    for op in operations:
        captures = [r for r in observation.ledger if r["operationId"] == op.operationId]
        local = [r for r in observation.application if r["operation_id"] == op.operationId]
        paid = any(r["status"] == "paid" for r in local)
        matching = [r for r in captures if all(r[k] == v for k, v in op.model_dump().items())]
        checks = {
            "no_duplicate_effect": (len(captures) <= 1, f"{len(captures)} committed captures; maximum 1"),
            "correct_completion": (not paid or len(captures) == len(matching) == 1,
                                   f"paid={paid}; {len(matching)} matching captures"),
            "bounded_progress": (paid and len(matching) == 1,
                                 "paid with one matching effect required after the declared delivery budget"),
        }
        for name, (passed, detail) in checks.items():
            results.append(PropertyResult(property=name, operationId=op.operationId, passed=passed, detail=detail))
    return results
