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

- Python clients only; plain imports, `as` aliases and from-imports
  are resolved; dynamic dispatch and relative from-imports are not
  (those escalate or are left unedited so evaluation fails honestly).
  A from-import whose symbol moves to a different MODULE
  (`from textkit import slugify` where slugify is now in
  textkit.text) is not rewritten yet - the import is left unedited
  and the evaluation failure escalates.
- Guides are parsed in a narrow declared format; real-world release
  notes need the LLM planner that is intentionally not wired in yet.
- Sandboxing is local subprocess + venv isolation, not a hardened
  container; untrusted repos would need stronger isolation.

## Benchmark

`benchmark/cases/` holds real-library upgrade cases. Each case splits
inputs from expectations:

- `rules.json` - what the planner sees: exact version pins on both
  sides, the official migration-guide URL with retrieval date, the
  quoted guide row behind every rule, and the rewrite rules.
- `case.json` - what the evaluator checks: the expected verdict,
  whether the unpatched client must break on the new version
  (`breaks_unpatched`: the runner runs the unpatched client against
  the new version first and flags the case if it passes - a case that
  does not break proves nothing), the output contract, and notes.
  `migrate()` never reads this file, so expectations cannot leak into
  planning decisions.
- `client/` - a small package written against the old API.

Snapshot differences are classified as cosmetic or substantive.
Cosmetic means only: both lines parse as JSON and their values compare
equal under type-sensitive equality (a serialized boolean becoming a
number, or whitespace inside a JSON string value, is substantive - it
is content, not formatting), or a plain-text line pair differs only in
whitespace. Byte-level differences the line comparison would erase
(trailing newline, CRLF vs LF) are substantive. Cosmetic differences downgrade to
"consistent evidence" ONLY when the case declares an output contract
allowing it (`allow_serialization_formatting`) - e.g. consumers that
parse the JSON. Formatting changes genuinely break byte-sensitive
consumers (golden files, checksums, log parsers), so the default is
strict and any observable difference escalates to human review.

Current cases:

- **pydantic 1.10.13 -> 2.14.2** - renames from the official guide
  (`dict`/`json`/`parse_obj`); tests pass on v2 and the only snapshot
  difference is v2's `model_dump_json` dropping insignificant
  whitespace, reported as cosmetic under an explicit output contract.
- **numpy 1.26.4 -> 2.2.6** - `np.alltrue` and `np.product` raise
  `AttributeError` on 2.2.6 (verified), so this case breaks for real
  unpatched; the rules fix all call sites and behavior is unchanged.
  numpy 2.2.6 is the newest 2.x supporting the Python 3.10 used here.
- **numpy scalar promotion (1.26.4 -> 2.2.6)** - the NEP 50 change the
  guide documents ("np.float32(3) + 3. now returns a float32"): the
  unit test still passes (the value is 6.0 either way), but the
  snapshot catches the dtype and scalar-repr change and escalates as
  "behavior changed - human review". A substantive difference tests
  alone would call green.
- **numpy no-change (1.26.4 -> 2.2.6)** - a client using only
  untouched APIs gets the honest "no affected call sites" verdict
  instead of invented edits.

    python benchmark/run.py

## Planners

`migrator/planner.py` defines the planner interface. `RulePlanner`
is the deterministic baseline and the default everywhere. Passing a
`ModelPlanner` to `migrate()` enables a bounded
propose -> check -> revise -> escalate loop: the model proposes rules,
the same sandbox evaluation checks them, failures are fed back for a
bounded number of revisions, and if no proposal passes, the run
escalates with the full failure history. Every proposal is validated
strictly (malformed JSON, unknown keys, malformed names, empty
proposals are rejected and counted as failures); sandbox evaluation
remains the authority on whether any proposal actually works.

`migrator/budget.py` enforces pre-call spend limits and fails
closed:

- Worst-case cost is RESERVED before each call: input tokens bounded
  by the prompt's UTF-8 byte length (sound for byte-level BPE
  tokenizers - every token covers at least one byte, so Unicode- or
  code-dense prompts cannot exceed it) plus `max_output_tokens` and a
  per-request framing allowance, at the higher of the input/output
  rates, with a safety multiplier. Models whose tokenizer does not
  satisfy that property are refused, as is non-text input.
  `max_output_tokens` alone is never treated as a cost bound. Scope:
  this bounds the request content this process constructs. It cannot
  bound provider-added tokens (system wrappers, tool schemas,
  serialization) or provider price changes, so it is a conservative
  control on our own requests, not a strict guarantee on billed cost -
  exact accounting requires the provider's usage fields, reconciled in
  `settle()` once a live client exists.
- The cumulative total is persisted in a state file guarded by an
  OS-level advisory lock (`flock`) around every load-modify-store, so
  concurrent processes cannot lose each other's spend; the write
  itself is atomic (temp file + rename). Corrupt or unreadable state
  fails closed by treating the ceiling as fully spent.
- Unknown pricing, a missing ceiling, or an exhausted budget refuse
  the call BEFORE it happens - so retries cannot overrun: each one
  needs its own reservation. A call whose client raises keeps its full
  worst-case reservation, since it may still have been billed.

Provider-side caps are a backstop, not the boundary: enforcement
there is documented as not instantaneous. The reservation above is the
primary bound.

Tests replay scripted/recorded model responses (tests/replays and the
loop tests) and exercise the budget wrapper offline; there are no live
model calls, no stored credentials, and no network in this repo -
wiring a real model client is a separate, explicitly approved step.
