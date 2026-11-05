"""Parse a migration guide (markdown) into structured rewrite rules.

The guide format this parser understands is deliberately narrow and
declared up front (see parse_guide docstring): numbered breaking-change
lines naming a moved symbol or a renamed keyword. Anything it cannot
parse is collected as an unparsed line so the caller can escalate
instead of guessing - a silent half-parse is worse than none.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MOVE_RE = re.compile(r"`([\w.]+)`\s+moved to\s+`([\w.]+)`")
_KWARG_RE = re.compile(r"`(\w+)`\s+keyword of\s+`(\w+)`\s+(?:was\s+)?renamed to\s+`(\w+)`")


@dataclass
class Rules:
    moves: dict[str, str] = field(default_factory=dict)        # old dotted -> new dotted
    kwarg_renames: dict[tuple[str, str], str] = field(default_factory=dict)  # (func, old) -> new
    # bare-method renames, e.g. pydantic .dict() -> .model_dump();
    # matched on any receiver - benchmark clients must not use the old
    # name on unrelated objects, and evaluation is the safety net
    method_renames: dict[str, str] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)


def load_rules(path) -> Rules:
    """Load a benchmark rules JSON file (precise, machine-authored).

    Shape: {"moves": {old: new}, "kwarg_renames": {"func(old)": new},
            "method_renames": {old: new}} - all optional.
    """
    import json

    data = json.loads(open(path).read())
    rules = Rules()
    rules.moves = dict(data.get("moves") or {})
    rules.method_renames = dict(data.get("method_renames") or {})
    for spec, new in (data.get("kwarg_renames") or {}).items():
        func, old = spec[:-1].split("(", 1)
        rules.kwarg_renames[(func, old)] = new
    return rules


def parse_guide(path) -> Rules:
    """Parse the guide at path. Unmatched numbered lines land in .unparsed."""
    rules = Rules()
    for line in open(path):
        text = line.strip()
        if not re.match(r"^\d+\.", text):
            continue
        m = _MOVE_RE.search(text)
        if m:
            rules.moves[m.group(1)] = m.group(2)
            continue
        k = _KWARG_RE.search(text)
        if k:
            rules.kwarg_renames[(k.group(2), k.group(1))] = k.group(3)
            continue
        rules.unparsed.append(text)
    return rules
