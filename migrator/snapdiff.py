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


def _cosmetic(old: str, new: str) -> str | None:
    """Return why a differing line pair is harmless, else None."""
    if old.split() == new.split():
        return "whitespace-only difference"
    try:
        if json.loads(old) == json.loads(new):
            return "same JSON value, different serialization formatting"
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def classify(old_snapshot: str, new_snapshot: str):
    """Compare two snapshot outputs.

    Returns (classification, notes): 'identical', 'cosmetic' (all
    differences explained by formatting; notes describe each), or
    'substantive' (at least one line pair differs in value).
    """
    old_lines = old_snapshot.splitlines()
    new_lines = new_snapshot.splitlines()
    if old_lines == new_lines:
        return "identical", []
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
