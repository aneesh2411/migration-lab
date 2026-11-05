"""Classify behavior-snapshot differences: cosmetic vs substantive.

Not every byte difference is a behavior regression. Serialization
formatting changes - insignificant JSON whitespace, spacing inside an
otherwise identical value - are real observable differences worth
reporting, but they are not evidence that behavior changed. This
module separates the two so the verdict stays honest in both
directions: a substantive diff is never waved through, and a cosmetic
diff is never reported as a regression.
"""
from __future__ import annotations

import json


def _json_equal(a, b) -> bool:
    """Type-sensitive JSON equality.

    Plain Python equality treats True == 1 and 1 == 1.0 as equal; a
    serialized boolean becoming a number IS a behavior change. String
    contents compare exactly - whitespace inside a JSON string value is
    content, not formatting.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(
            _json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(
            _json_equal(x, y) for x, y in zip(a, b))
    return a == b


def _cosmetic(old: str, new: str) -> str | None:
    """Return why a differing line pair is harmless, else None."""
    try:
        jo, jn = json.loads(old), json.loads(new)
    except (json.JSONDecodeError, ValueError):
        pass  # not both JSON; try the plain-text formatting rule below
    else:
        # Both lines parse as JSON: only a type-sensitive value match is
        # cosmetic. Never fall through to whitespace collapsing for
        # JSON - it would erase real string-content changes.
        if _json_equal(jo, jn):
            return "same JSON value, different serialization formatting"
        return None
    if old.split() == new.split():
        return "whitespace-only difference"
    return None


def classify(old_snapshot: str, new_snapshot: str):
    """Compare two snapshot outputs.

    Returns (classification, notes): 'identical', 'cosmetic' (all
    differences explained by formatting; notes describe each), or
    'substantive' (at least one line pair differs in value).
    """
    if old_snapshot == new_snapshot:
        return "identical", []
    old_lines = old_snapshot.splitlines()
    new_lines = new_snapshot.splitlines()
    if old_lines == new_lines:
        # splitlines() erases trailing-newline and CRLF/LF differences;
        # those are real byte changes a strict consumer can observe.
        return "substantive", [
            "snapshots differ only in bytes: line endings or trailing "
            "newline changed"]
    if len(old_lines) != len(new_lines):
        return "substantive", [
            f"snapshot line count changed: {len(old_lines)} -> "
            f"{len(new_lines)}"]
    notes = []
    for i, (o, n) in enumerate(zip(old_lines, new_lines)):
        if o == n:
            continue
        why = _cosmetic(o, n)
        if why is None:
            notes.append(f"line {i + 1}: {o!r} -> {n!r}")
            return "substantive", notes
        notes.append(f"line {i + 1}: {why}")
    return "cosmetic", notes
