"""Orchestrate one migration: guide -> usages -> patch -> sandbox -> verdict.

Verdicts, deliberately honest:
- "consistent evidence": tests pass on the new version AND the behavior
  snapshot shows no substantive difference from the old version.
  Cosmetic serialization differences (e.g. insignificant JSON
  whitespace) are reported separately, never as regressions. Evidence,
  not proof.
- "behavior changed": tests pass but snapshot output differs in value -
  needs human review; tests alone would have missed it.
- "escalate": anything unparsed, unpatched, or failing - the diff and
  the reason are handed to a human, nothing is applied silently.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from .finder import find_usages
from .guide import load_rules, parse_guide
from .patcher import patch_file
from .sandbox import run_in_sandbox
from .snapdiff import classify


def migrate(client: Path, lib_old: Path, lib_new: Path,
            guide: Path) -> dict:
    report: dict = {"client": str(client), "guide": str(guide)}

    baseline = run_in_sandbox(client, lib_old)
    report["baseline"] = {"tests_passed": baseline.tests_passed,
                          "error": baseline.error}
    if baseline.error or not baseline.tests_passed:
        report["verdict"] = "escalate"
        report["reason"] = ("baseline (old version) is not green; "
                            "migrate a healthy tree, not a broken one")
        return report

    rules = (load_rules(guide) if str(guide).endswith(".json")
             else parse_guide(guide))
    report["rules"] = {"moves": rules.moves,
                       "method_renames": rules.method_renames,
                       "kwarg_renames": {f"{f}({o})": n
                                         for (f, o), n in
                                         rules.kwarg_renames.items()},
                       "unparsed": rules.unparsed}
    if rules.unparsed:
        report["verdict"] = "escalate"
        report["reason"] = ("guide lines this tool cannot parse: "
                            + "; ".join(rules.unparsed))
        return report

    usages = find_usages(client, rules)
    report["usage_count"] = len(usages)
    if not usages:
        report["verdict"] = "no affected call sites"
        return report

    patched: dict[str, str] = {}
    diffs: list[str] = []
    for path in sorted({u.path for u in usages}):
        res = patch_file(path, rules)
        if not res.ok:
            report["verdict"] = "escalate"
            report["reason"] = (f"patch for {path} does not parse; "
                                "edits attempted: " + "; ".join(res.edits))
            return report
        rel = str(path.relative_to(client))
        patched[rel] = res.patched
        diffs.extend(difflib.unified_diff(
            res.original.splitlines(), res.patched.splitlines(),
            fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
    report["diff"] = "\n".join(diffs)

    migrated = run_in_sandbox(client, lib_new, apply=patched)
    report["migrated"] = {"tests_passed": migrated.tests_passed,
                          "error": migrated.error,
                          "test_tail": migrated.test_output[-300:]}
    if migrated.error or not migrated.tests_passed:
        report["verdict"] = "escalate"
        report["reason"] = "patched code fails against the new version"
        return report
    kind, notes = classify(baseline.snapshot, migrated.snapshot)
    if kind == "substantive":
        report["verdict"] = "behavior changed"
        report["reason"] = ("unit tests pass on the new version, but the "
                            "behavior snapshot shows a substantive "
                            "difference - human review required")
        report["snapshot_diff"] = "\n".join(difflib.unified_diff(
            baseline.snapshot.splitlines(), migrated.snapshot.splitlines(),
            fromfile="old-behavior", tofile="new-behavior", lineterm=""))
        report["difference_notes"] = notes
        return report
    report["verdict"] = "consistent evidence"
    report["reason"] = ("tests pass on the new version and observed "
                        "behavior matches the old version; this is "
                        "evidence, not proof - hidden paths and API "
                        "edge cases still warrant review")
    if kind == "cosmetic":
        report["cosmetic_differences"] = notes
        report["snapshot_diff"] = "\n".join(difflib.unified_diff(
            baseline.snapshot.splitlines(), migrated.snapshot.splitlines(),
            fromfile="old-behavior", tofile="new-behavior", lineterm=""))
    return report
