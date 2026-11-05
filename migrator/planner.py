"""Planners: who turns a migration guide + affected call sites into
rewrite rules.

RulePlanner is deterministic - today's behavior: rules come from the
parsed guide (or a machine-authored rules.json), nothing is invented.

ModelPlanner asks a model to PROPOSE rules, then validates the
proposal hard before anything is applied. The model is never trusted:
the sandbox evaluation in agent.migrate is unchanged and remains the
authority - a model proposal that rewrites the wrong thing fails
evaluation and escalates, exactly like a bad hand-written rule.

The model client is injected as a plain callable (prompt -> text), so
tests replay recorded responses and no network or credentials are
involved until a paid-usage approval exists. Live use also requires
wiring a real client - none is provided here on purpose.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .guide import Rules

_NAME_RE = re.compile(r"^\w+(\.\w+)*$")
_KNOWN_KEYS = {"moves", "method_renames", "kwarg_renames"}


class PlannerError(Exception):
    """A model proposal was unusable; escalate, never guess."""


@dataclass
class MigrationContext:
    library: str
    from_version: str
    to_version: str
    guide_text: str
    usages: list[str]  # rendered affected call sites
    client_sources: dict[str, str] = None  # relpath -> source


class RulePlanner:
    """Deterministic baseline: return the already-parsed rules."""

    def __init__(self, rules: Rules):
        self.rules = rules

    def propose(self, context: MigrationContext) -> Rules:
        return self.rules


_PROMPT_TEMPLATE = """Library: {library} {from_version} -> {to_version}

Migration guide excerpt:
{guide_text}

Affected call sites found in the client:
{usages}

Propose rewrite rules as JSON with optional keys "moves"
(old dotted name -> new dotted name), "method_renames" (old method ->
new method), "kwarg_renames" ("func(old_kw)" -> new_kw). Propose only
renames the guide excerpt supports. Respond with JSON only."""


def validate_proposal(raw: str) -> Rules:
    """Parse and validate a model proposal into Rules.

    Rejects: non-JSON, non-object, unknown keys, non-dict sections,
    non-string or malformed names. Anything rejected raises
    PlannerError so the caller escalates instead of applying guesses.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlannerError(f"proposal is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PlannerError("proposal is not a JSON object")
    unknown = set(data) - _KNOWN_KEYS
    if unknown:
        raise PlannerError(f"proposal has unknown keys: {sorted(unknown)}")
    rules = Rules()
    for old, new in (data.get("moves") or {}).items():
        if not (_NAME_RE.match(str(old)) and _NAME_RE.match(str(new))
                and "." in str(old) and "." in str(new)):
            raise PlannerError(f"malformed move: {old!r} -> {new!r}")
        rules.moves[str(old)] = str(new)
    for old, new in (data.get("method_renames") or {}).items():
        if not (str(old).isidentifier() and str(new).isidentifier()):
            raise PlannerError(
                f"malformed method rename: {old!r} -> {new!r}")
        rules.method_renames[str(old)] = str(new)
    for spec, new in (data.get("kwarg_renames") or {}).items():
        m = re.match(r"^(\w+)\((\w+)\)$", str(spec))
        if not (m and str(new).isidentifier()):
            raise PlannerError(f"malformed kwarg rename: {spec!r}")
        rules.kwarg_renames[(m.group(1), m.group(2))] = str(new)
    if not (rules.moves or rules.method_renames or rules.kwarg_renames):
        raise PlannerError("proposal contains no rules")
    return rules


class ModelPlanner:
    """Propose rules via an injected model client; validate strictly."""

    def __init__(self, client):
        # client: callable(prompt: str) -> str. Injection keeps tests
        # offline (replay recorded responses) and keeps live use an
        # explicit, separately-approved step.
        self.client = client

    def _prompt(self, context: MigrationContext,
                failures: list[str] | None = None) -> str:
        prompt = _PROMPT_TEMPLATE.format(
            library=context.library, from_version=context.from_version,
            to_version=context.to_version, guide_text=context.guide_text,
            usages="\n".join(context.usages) or "(none)")
        if context.client_sources:
            prompt += "\n\nClient sources:\n" + "\n".join(
                f"--- {p} ---\n{s}" for p, s
                in sorted(context.client_sources.items()))
        if failures:
            prompt += ("\n\nPrevious proposal(s) failed evaluation. "
                       "Failures:\n" + "\n".join(failures)
                       + "\nPropose corrected rules.")
        return prompt

    def propose(self, context: MigrationContext) -> Rules:
        return validate_proposal(self.client(self._prompt(context)))

    def revise(self, context: MigrationContext,
               failures: list[str]) -> Rules:
        """Retry with evaluation feedback. Callers bound the count;
        each call is another (reserved, billed) model request."""
        return validate_proposal(
            self.client(self._prompt(context, failures)))
