"""Propose -> check -> revise -> escalate loop, fully offline.

Model responses are scripted replays; the wrapped BudgetedClient makes
every call a reserved one. Toy textkit fixtures come from conftest.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrator.agent import migrate  # noqa: E402
from migrator.budget import (Budget, BudgetedClient,  # noqa: E402
                             Pricing, token_bound)
from migrator.planner import ModelPlanner  # noqa: E402

FIX = ROOT / "fixtures"
GUIDE = FIX / "guides" / "textkit-1-to-2.md"

GOOD = ('{"moves": {"textkit.slugify": "textkit.text.slugify",'
        ' "textkit.word_count": "textkit.text.word_count"},'
        ' "kwarg_renames": {"slugify(sep)": "delimiter"}}')
BAD = '{"method_renames": {"slugify": "slg"}}'  # applies, breaks tests


def scripted(responses):
    state = {"prompts": [], "i": 0}

    def client(prompt):
        state["prompts"].append(prompt)
        r = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        return r
    return client, state


def test_revise_after_failed_evaluation_succeeds():
    client, state = scripted([BAD, GOOD])
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", GUIDE,
                planner=ModelPlanner(client))
    assert r["verdict"] == "consistent evidence"
    assert r["planner_attempts"] == 2
    assert len(state["prompts"]) == 2
    assert "fails against the new version" in state["prompts"][1]
    assert "fails against the new version" not in state["prompts"][0]


def test_invalid_proposal_is_fed_back_and_revised():
    client, state = scripted(["not json at all", GOOD])
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", GUIDE,
                planner=ModelPlanner(client))
    assert r["verdict"] == "consistent evidence"
    assert "proposal rejected" in state["prompts"][1]


def test_bounded_attempts_escalate_with_history():
    client, state = scripted([BAD])  # never improves
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", GUIDE,
                planner=ModelPlanner(client), max_attempts=2)
    assert r["verdict"] == "escalate"
    assert len(state["prompts"]) == 2  # bound held
    assert len(r["attempts"]) == 2


def test_budget_exhaustion_stops_loop_fail_closed(tmp_path):
    client, state = scripted([BAD, GOOD])
    # ceiling between the first and second call's reservations, derived
    # the same way migrate() builds its context - environment-independent
    from migrator.planner import MigrationContext
    lib_old, lib_new = FIX / "textkit_v1", FIX / "textkit_v2"
    ctx_sources = {str(p.relative_to(FIX / "client_app")): p.read_text()
                   for p in sorted((FIX / "client_app").rglob("*.py"))}
    ctx = MigrationContext(
        library=str(lib_old).split("==")[0],
        from_version=str(lib_old).split("==")[-1],
        to_version=str(lib_new).split("==")[-1],
        guide_text=GUIDE.read_text(), usages=[],
        client_sources=ctx_sources)
    probe = Budget(tmp_path / "probe.json", 10.0,
                   {"test-model": Pricing(0.10, 0.50, "byte-bpe")})
    planner_probe = ModelPlanner(lambda p: GOOD)
    r1 = probe.reserve("test-model", planner_probe._prompt(ctx), 2000)
    r2 = probe.reserve("test-model",
                       planner_probe._prompt(ctx, ["some failure"]),
                       2000)
    budget = Budget(tmp_path / "b.json", (r1.amount + r2.amount) / 2,
                    {"test-model": Pricing(0.10, 0.50, "byte-bpe")})
    paid = BudgetedClient(client, budget, "test-model", 2000)
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", GUIDE,
                planner=ModelPlanner(paid))
    assert r["verdict"] == "escalate"
    assert paid.calls == 1  # no retry without a reservation
    assert any("budget exhausted" in f for f in r["attempts"])
