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


# Independent-review regressions: import detection and patcher spans.

def _tmp_client(tmp_path, source):
    d = tmp_path / "client"
    d.mkdir()
    (d / "main.py").write_text(source)
    return d


def test_finder_from_import_not_false_negative(tmp_path):
    # review P1: `from numpy import alltrue; alltrue(...)` produced a
    # false "no affected call sites" verdict
    from migrator.guide import Rules
    rules = Rules()
    rules.moves["numpy.alltrue"] = "numpy.all"
    d = _tmp_client(tmp_path,
                    "from numpy import alltrue\nalltrue([True])\n")
    usages = find_usages(d, rules)
    kinds = {u.kind for u in usages}
    assert "import" in kinds and "call" in kinds


def test_patcher_from_import_keeps_binding(tmp_path):
    from migrator.guide import Rules
    rules = Rules()
    rules.moves["numpy.alltrue"] = "numpy.all"
    f = _tmp_client(tmp_path,
                    "from numpy import alltrue\nalltrue([True])\n"
                    ) / "main.py"
    res = patch_file(f, rules)
    assert res.ok
    assert "from numpy import all as alltrue" in res.patched
    assert "alltrue([True])" in res.patched  # call site stays valid
    import ast
    ast.parse(res.patched)


def test_patcher_from_import_with_asname(tmp_path):
    from migrator.guide import Rules
    rules = Rules()
    rules.moves["numpy.alltrue"] = "numpy.all"
    f = _tmp_client(tmp_path,
                    "from numpy import alltrue as at\nat([True])\n"
                    ) / "main.py"
    res = patch_file(f, rules)
    assert res.ok
    assert "from numpy import all as at" in res.patched


def test_patcher_aliased_import_submodule_move(tmp_path):
    # review P2: `import textkit as tk` + slugify moving to
    # textkit.text produced `import textkit.text as tk` together with
    # the bogus call `tk.text.slugify(...)`
    from migrator.guide import Rules
    rules = Rules()
    rules.moves["textkit.slugify"] = "textkit.text.slugify"
    f = _tmp_client(tmp_path,
                    'import textkit as tk\ntk.slugify("a b")\n'
                    ) / "main.py"
    res = patch_file(f, rules)
    assert res.ok
    assert "import textkit.text as tk" in res.patched
    assert 'tk.slugify("a b")' in res.patched
    assert "tk.text.slugify" not in res.patched


def test_patcher_unicode_before_edit(tmp_path):
    # review P2: AST column offsets are UTF-8 byte offsets; editing str
    # lines with them corrupted patches on lines containing non-ASCII
    from migrator.guide import Rules
    rules = Rules()
    rules.moves["numpy.alltrue"] = "numpy.all"
    f = _tmp_client(tmp_path,
                    'import numpy as np\nx = "é"; y = np.alltrue([True])\n'
                    ) / "main.py"
    res = patch_file(f, rules)
    assert res.ok
    assert 'x = "é"; y = np.all([True])' in res.patched
    import ast
    ast.parse(res.patched)
