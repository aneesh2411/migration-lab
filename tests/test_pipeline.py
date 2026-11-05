"""Pipeline tests: parser, finder, patcher, orchestrator verdicts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrator.guide import parse_guide  # noqa: E402
from migrator.finder import find_usages  # noqa: E402
from migrator.patcher import patch_file  # noqa: E402
from migrator.agent import migrate  # noqa: E402

FIX = ROOT / "fixtures"
GUIDE = FIX / "guides" / "textkit-1-to-2.md"


def test_guide_parser_rules_and_no_silent_drops():
    rules = parse_guide(GUIDE)
    assert rules.moves["textkit.slugify"] == "textkit.text.slugify"
    assert rules.kwarg_renames[("slugify", "sep")] == "delimiter"
    assert rules.unparsed == []
    bad = parse_guide(FIX / "guides" / "textkit-unparseable.md")
    assert bad.unparsed  # unparseable instruction is surfaced, not dropped


def test_finder_and_patcher():
    rules = parse_guide(GUIDE)
    usages = find_usages(FIX / "client_app" / "client_app", rules)
    assert len(usages) == 4  # 1 import + 3 call sites
    res = patch_file(FIX / "client_app" / "client_app" / "titles.py", rules)
    assert res.ok
    assert "import textkit.text" in res.patched
    assert 'delimiter="_"' in res.patched
    assert "textkit.text.word_count" in res.patched
    import ast
    ast.parse(res.patched)  # still valid Python


def test_happy_path_is_evidence_not_proof():
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", GUIDE)
    assert r["verdict"] == "consistent evidence"
    assert "not proof" in r["reason"]
    assert r["baseline"]["tests_passed"] and r["migrated"]["tests_passed"]


def test_behavior_change_caught_when_tests_still_pass():
    # v2b passes the client's unit tests but changes word_count behavior
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2b", GUIDE)
    assert r["verdict"] == "behavior changed"
    assert "snapshot_diff" in r


def test_unparseable_guide_escalates():
    r = migrate(FIX / "client_app", FIX / "textkit_v1",
                FIX / "textkit_v2", FIX / "guides" / "textkit-unparseable.md")
    assert r["verdict"] == "escalate"
