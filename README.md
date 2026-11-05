# migration-agent (working title, local prototype)

An evaluated workflow for library major-version migrations: read the
migration guide, find affected call sites, patch them, and verify the
result in a sandbox - escalating to a human with a diff whenever
confidence runs out.

Status: local vertical slice. No LLM calls yet (any paid model usage
needs explicit approval first); the current planner is a deterministic
rule engine so the pipeline, sandboxing and evaluation can be built and
tested without one. A model-backed planner will slot in behind the same
"propose edits, never apply blindly" contract.

## Why it exists

Dependency tools bump versions; coding agents can attempt upgrades ad
hoc. The distinction explored here is a narrow, evaluated migration
workflow: every suggested change is checked against the repo's own
tests AND a behavior snapshot taken on the old version, and ambiguous
or unparseable guidance is escalated rather than guessed.

## Pipeline

1. `guide.py` - parses the migration guide into structured rules
   (symbol moves, keyword renames). Lines it cannot parse are
   surfaced, never silently dropped.
2. `finder.py` - AST scan of the client repo for affected imports and
   call sites (no regex guessing on code).
3. `patcher.py` - AST-precise span edits; the result must still parse
   or the whole patch is rejected.
4. `sandbox.py` - fresh venv per run; installs the target library
   build from a local path, runs the client's tests and its behavior
   snapshot. The original repo is never touched.
5. `agent.py` - orchestrates and issues an honest verdict:
   - `consistent evidence` - tests pass on the new version and the
     observed behavior matches the old version. Evidence, not proof.
   - `behavior changed` - tests pass but the snapshot differs; unit
     tests alone would have missed it (this path is tested).
   - `escalate` - broken baseline, unparseable guide, or failing
     patch; the human gets the diff and the reason.

## Demo

    python run_migration.py fixtures/client_app fixtures/textkit_v1 \
        fixtures/textkit_v2 fixtures/guides/textkit-1-to-2.md

`fixtures/` contains a toy library (`textkit` v1 -> v2: moved module,
renamed keyword), a client app pinned to the v1 API, and a v2b variant
whose behavior silently differs - used to prove the evaluator catches
what tests miss.

## Tests

    python -m pytest tests -q

## Deliberate limits (current scope)

- Python clients only; import/attribute call patterns, no aliased
  imports or dynamic dispatch (those escalate).
- Guides are parsed in a narrow declared format; real-world release
  notes need the LLM planner that is intentionally not wired in yet.
- Sandboxing is local subprocess + venv isolation, not a hardened
  container; untrusted repos would need stronger isolation.

## Benchmark

`benchmark/cases/` holds real-library upgrade cases: each pins actual
published versions (installed from PyPI into throwaway venvs), a small
client package written against the old API, rules distilled from the
library's official migration guide, and the expected verdict. The
first case, pydantic v1 -> v2, shows the evaluator working on a real
library: the rule engine applies the `dict`/`json`/`parse_obj`
renames, the client's unit tests pass on v2 - and the behavior
snapshot still catches that v2's `model_dump_json` drops insignificant
whitespace, so the run ends in "behavior changed - human review"
rather than a false green. That is the intended demonstration:
verification beyond tests.

    python benchmark/run.py
