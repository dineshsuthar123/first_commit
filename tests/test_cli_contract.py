import pytest

from engine.cli import campaign_exit_code
from engine.models import Verdict


@pytest.mark.parametrize(
    "campaign, expected",
    [
        ({"lifecycle": "FINISHED", "executed": 2, "counts": {Verdict.PASS: 2}}, 0),
        ({"lifecycle": "FINISHED", "executed": 2, "counts": {Verdict.PASS: 1, Verdict.VIOLATION: 1}}, 1),
        ({"lifecycle": "FINISHED", "executed": 1, "counts": {Verdict.DIVERGED: 1}}, 2),
        ({"lifecycle": "FINISHED", "executed": 2, "counts": {Verdict.VIOLATION: 1, Verdict.ERROR: 1}}, 2),
        ({"lifecycle": "FINISHED", "executed": 1, "counts": {Verdict.INCONCLUSIVE: 1}}, 2),
        ({"lifecycle": "FAILED", "executed": 1, "counts": {Verdict.PASS: 1}}, 2),
        ({"lifecycle": "FINISHED", "executed": 0, "counts": {}}, 2),
        ({"lifecycle": "FINISHED", "executed": 2, "counts": {Verdict.PASS: 1}}, 2),
    ],
)
def test_campaign_exit_policy(campaign, expected):
    assert campaign_exit_code(campaign) == expected
