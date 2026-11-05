"""Run every benchmark case and check verdicts against expectations.

    python benchmark/run.py

Case layout:
  rules.json  - inputs and provenance only: library, from, to (exact
                pins), guide_url, guide_retrieved, rule_evidence, and
                the rewrite rules. This is what the planner sees.
  case.json   - evaluation expectations: expected_verdict,
                breaks_unpatched, output_contract, notes. The planner
                and migrate() never read this file - expectations
                cannot leak into planning decisions.
  client/     - a small package written against the old API.

Cases run the real published library versions in isolated venvs;
nothing is installed into the ambient environment. When a case
declares breaks_unpatched, the unpatched client is run against the
new version first and MUST fail - otherwise the case proves nothing.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrator.agent import migrate  # noqa: E402
from migrator.sandbox import run_in_sandbox  # noqa: E402


def run_case(case: Path) -> tuple[str, str, str, list[str]]:
    rules = json.loads((case / "rules.json").read_text())
    expect = json.loads((case / "case.json").read_text())
    spec_old = f"{rules['library']}=={rules['from']}"
    spec_new = f"{rules['library']}=={rules['to']}"
    problems = []

    if expect.get("breaks_unpatched"):
        raw = run_in_sandbox(case / "client", spec_new)
        if not raw.error and raw.tests_passed:
            problems.append(
                "case claims the unpatched client breaks on the new "
                "version, but it passed - the case proves nothing")

    report = migrate(case / "client", spec_old, spec_new,
                     case / "rules.json",
                     output_contract=expect.get("output_contract"))
    got = report["verdict"]
    want = expect["expected_verdict"]
    mark = "ok" if got == want and not problems else "MISMATCH"
    return case.name, want, got, mark, problems


def main() -> int:
    rows, all_problems = [], []
    for case in sorted((ROOT / "benchmark" / "cases").iterdir()):
        name, want, got, mark, problems = run_case(case)
        rows.append((name, want, got, mark))
        all_problems.extend(f"{name}: {p}" for p in problems)
    w = max(len(r[0]) for r in rows)
    for name, want, got, mark in rows:
        print(f"{name:<{w}}  expected={want:<22} got={got:<22} {mark}")
    for p in all_problems:
        print("PROBLEM:", p)
    bad = [r for r in rows if r[3] != "ok"]
    print(f"{len(rows) - len(bad)}/{len(rows)} cases as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
