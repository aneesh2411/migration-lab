"""Run every benchmark case and compare verdicts to expectations.

    python benchmark/run.py

Each case directory holds: rules.json (library, from, to,
expected_verdict, rewrite rules) and client/ (a small package pinned
to the old API). Cases run the real published library versions in
isolated venvs; nothing is installed into the ambient environment.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from migrator.agent import migrate  # noqa: E402


def main() -> int:
    rows = []
    for case in sorted((ROOT / "benchmark" / "cases").iterdir()):
        rules = json.loads((case / "rules.json").read_text())
        spec_old = f"{rules['library']}=={rules['from']}"
        spec_new = f"{rules['library']}=={rules['to']}"
        report = migrate(case / "client", spec_old, spec_new,
                         case / "rules.json")
        got = report["verdict"]
        want = rules.get("expected_verdict")
        rows.append((case.name, want, got,
                     "ok" if got == want else "MISMATCH"))
    w = max(len(r[0]) for r in rows)
    for name, want, got, mark in rows:
        print(f"{name:<{w}}  expected={want:<22} got={got:<22} {mark}")
    bad = [r for r in rows if r[3] != "ok"]
    print(f"{len(rows) - len(bad)}/{len(rows)} cases as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
