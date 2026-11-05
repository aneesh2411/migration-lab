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

from .budget import BudgetExceeded
from .finder import find_usages
from .guide import load_rules, parse_guide
from .patcher import patch_file
from .planner import MigrationContext, PlannerError
from .sandbox import run_in_sandbox
from .snapdiff import classify


def migrate(client: Path, lib_old: Path, lib_new: Path,
            guide: Path, output_contract: dict | None = None,
            planner=None, max_attempts: int = 2) -> dict:
    """output_contract declares what the client's output consumers
    tolerate. {"allow_serialization_formatting": True} means consumers
    parse structured output, so cosmetically-reformatted-but-equal
    values are acceptable. Default is strict: any observable
    difference escalates, because byte-level changes (JSON whitespace,
    scalar reprs) genuinely break byte-sensitive consumers such as
    golden files, checksums, and log parsers.
    """
    report: dict = {"client": str(client), "guide": str(guide)}
    allow_fmt = bool((output_contract or {})
                     .get("allow_serialization_formatting"))
    # planner=None keeps the deterministic single-attempt path; a
    # planner enables propose -> check -> revise -> escalate, bounded
    # by max_attempts (every proposal is a separate, reserved call)
    attempts = max(1, max_attempts if planner else 1)

    baseline = run_in_sandbox(client, lib_old)
    report["baseline"] = {"tests_passed": baseline.tests_passed,
                          "error": baseline.error}
    if baseline.error or not baseline.tests_passed:
        report["verdict"] = "escalate"
        report["reason"] = ("baseline (old version) is not green; "
                            "migrate a healthy tree, not a broken one")
        return report

    context = None
    if planner is not None:
        sources = {str(p.relative_to(client)): p.read_text()
                   for p in sorted(client.rglob("*.py"))}
        context = MigrationContext(
            library=str(lib_old).split("==")[0],
            from_version=str(lib_old).split("==")[-1],
            to_version=str(lib_new).split("==")[-1],
            guide_text=Path(guide).read_text(), usages=[],
            client_sources=sources)
    failures: list[str] = []
    rules = usages = patched = migrated = None
    passed = False
    for attempt in range(attempts):
        if planner is None:
            rules = (load_rules(guide) if str(guide).endswith(".json")
                     else parse_guide(guide))
        else:
            try:
                rules = (planner.revise(context, failures) if failures
                         else planner.propose(context))
            except PlannerError as e:
                failures.append(f"proposal rejected: {e}")
                continue
            except BudgetExceeded as e:
                # fail closed: no reservation, no call, stop here -
                # retrying would spend past the ceiling
                failures.append(f"budget exhausted: {e}")
                break
        report["rules"] = {"moves": rules.moves,
                           "method_renames": rules.method_renames,
                           "kwarg_renames": {f"{f}({o})": n
                                             for (f, o), n in
                                             rules.kwarg_renames.items()},
                           "unparsed": rules.unparsed}
        if rules.unparsed:
            # deterministic path only: escalate on unparseable guide
            report["verdict"] = "escalate"
            report["reason"] = ("guide lines this tool cannot parse: "
                                + "; ".join(rules.unparsed))
            return report

        usages = find_usages(client, rules)
        report["usage_count"] = len(usages)
        if not usages:
            if planner is None:
                report["verdict"] = "no affected call sites"
                return report
            failures.append("proposed rules match no call sites")
            continue

        patched = {}
        diffs = []
        patch_failed = False
        for path in sorted({u.path for u in usages}):
            res = patch_file(path, rules)
            if not res.ok:
                if planner is None:
                    report["verdict"] = "escalate"
                    report["reason"] = (
                        f"patch for {path} does not parse; edits "
                        "attempted: " + "; ".join(res.edits))
                    return report
                failures.append(
                    f"patch for {path.name} does not parse; edits "
                    "attempted: " + "; ".join(res.edits))
                patch_failed = True
                break
            rel = str(path.relative_to(client))
            patched[rel] = res.patched
            diffs.extend(difflib.unified_diff(
                res.original.splitlines(), res.patched.splitlines(),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
        if patch_failed:
            continue
        report["diff"] = "\n".join(diffs)

        migrated = run_in_sandbox(client, lib_new, apply=patched)
        report["migrated"] = {"tests_passed": migrated.tests_passed,
                              "error": migrated.error,
                              "test_tail": migrated.test_output[-300:]}
        if migrated.error or not migrated.tests_passed:
            if planner is None:
                report["verdict"] = "escalate"
                report["reason"] = ("patched code fails against the "
                                    "new version")
                return report
            failures.append(
                "patched code fails against the new version: "
                + (migrated.error or migrated.test_output[-200:]))
            continue
        passed = True
        break  # evaluation passed; verdict decided below
    if not passed:
        report["verdict"] = "escalate"
        report["reason"] = ("no proposal passed evaluation; escalating "
                            "with the failure history")
        report["attempts"] = failures
        return report
    if planner is not None:
        report["planner_attempts"] = len(failures) + 1
        if failures:
            report["prior_failures"] = failures
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
    if kind == "cosmetic" and allow_fmt:
        report["cosmetic_differences"] = notes
        report["snapshot_diff"] = "\n".join(difflib.unified_diff(
            baseline.snapshot.splitlines(), migrated.snapshot.splitlines(),
            fromfile="old-behavior", tofile="new-behavior", lineterm=""))
        return report
    if kind == "cosmetic":
        report["verdict"] = "behavior changed"
        report["reason"] = ("unit tests pass on the new version; the "
                            "snapshot differences look like serialization "
                            "formatting, but this case declares no output "
                            "contract allowing that - byte-sensitive "
                            "consumers (golden files, checksums, log "
                            "parsers) can break on exactly these changes, "
                            "so a human must confirm before accepting")
        report["cosmetic_differences"] = notes
        report["snapshot_diff"] = "\n".join(difflib.unified_diff(
            baseline.snapshot.splitlines(), migrated.snapshot.splitlines(),
            fromfile="old-behavior", tofile="new-behavior", lineterm=""))
        return report
    return report
