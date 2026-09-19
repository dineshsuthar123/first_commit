from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Verdict(StrEnum):
    PASS = "PASS_WITHIN_BOUNDS"
    VIOLATION = "PROPERTY_VIOLATION"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "HARNESS_ERROR"
    DIVERGED = "DIVERGED"


Variant = Literal["local_dedup", "per_attempt_key", "mark_before", "stable_key"]


class Operation(Strict):
    operationId: str = Field(default="capture-001", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    orderId: str = Field(default="order-001", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    amountMinor: int = Field(default=100000, ge=1, le=100000000, strict=True)
    currency: Literal["INR", "USD", "EUR"] = "INR"


class Checkpoint(Strict):
    operationId: str
    checkpoint: str = Field(pattern=r"^[a-z_]{1,64}$")
    attempt: int = Field(ge=1, le=2)
    occurrence: int = Field(default=1, ge=1, le=16)


class FaultPlan(Checkpoint):
    decision: Literal["kill"] = "kill"


class Action(Strict):
    operationId: str
    attempt: int = Field(ge=1, le=2)
    fault: FaultPlan | None = None


class CasePlan(Strict):
    variant: Variant = "local_dedup"
    operations: list[Operation] = Field(min_length=1, max_length=4)
    actions: list[Action] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def prerequisites(self):
        ids = [o.operationId for o in self.operations]
        if len(set(ids)) != len(ids):
            raise ValueError("operation IDs must be unique")
        seen: dict[str, int] = {}
        faults = 0
        for a in self.actions:
            if a.operationId not in ids or a.attempt != seen.get(a.operationId, 0) + 1:
                raise ValueError("deliveries require an admitted operation and consecutive attempts")
            seen[a.operationId] = a.attempt
            if a.fault:
                faults += 1
                if a.fault.operationId != a.operationId or a.fault.attempt != a.attempt:
                    raise ValueError("fault boundary must belong to its action")
        if faults > 1:
            raise ValueError("at most one injected crash")
        return self


class Observation(Strict):
    ledger: list[dict]
    application: list[dict]
    dependenciesHealthy: bool


class PropertyResult(Strict):
    property: str
    version: int = 1
    operationId: str
    passed: bool
    detail: str


BOUNDS = {"consumers": 1, "providers": 1, "maxCrashes": 1, "maxAttempts": 2,
          "attemptTimeoutSeconds": 15, "maxOperations": 4, "maxActions": 8}
PROPERTIES = {"no_duplicate_effect": 1, "correct_completion": 1, "bounded_progress": 1}
