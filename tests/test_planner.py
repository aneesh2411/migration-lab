"""Planner tests: deterministic baseline and model-proposal replay.

ModelPlanner tests replay recorded model responses from tests/replays -
no live model calls. A live client is wired only after paid-usage
approval, separately from this interface.
"""
import json
from pathlib import Path

import pytest

from migrator.guide import Rules
from migrator.planner import (MigrationContext, ModelPlanner, PlannerError,
                              RulePlanner)

CTX = MigrationContext(library="numpy", from_version="1.26.4",
                       to_version="2.2.6",
                       guide_text="alltrue Use np.all instead.",
                       usages=["app/stats.py:5 np.alltrue(...)"])

REPLAYS = sorted((Path(__file__).parent / "replays").glob("*.json"))


def test_rule_planner_returns_parsed_rules():
    rules = Rules(method_renames={"alltrue": "all"})
    assert RulePlanner(rules).propose(CTX) is rules


def test_model_planner_prompt_carries_context():
    seen = {}

    def fake_client(prompt):
        seen["prompt"] = prompt
        return '{"method_renames": {"alltrue": "all"}}'

    out = ModelPlanner(fake_client).propose(CTX)
    assert out.method_renames == {"alltrue": "all"}
    assert "numpy 1.26.4 -> 2.2.6" in seen["prompt"]
    assert "alltrue Use np.all instead." in seen["prompt"]
    assert "np.alltrue(...)" in seen["prompt"]


@pytest.mark.parametrize("replay", REPLAYS, ids=[p.name for p in REPLAYS])
def test_model_planner_replays(replay):
    case = json.loads(replay.read_text())
    planner = ModelPlanner(lambda prompt: case["response"])
    if case["expect"] == "ok":
        rules = planner.propose(CTX)
        assert rules.method_renames == case.get("method_renames", {})
        assert rules.moves == case.get("moves", {})
    else:
        with pytest.raises(PlannerError):
            planner.propose(CTX)
