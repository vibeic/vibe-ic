---
name: full-test-audit
description: >-
  Run when the user says "have full test", "full test", "run the full audit", or
  asks to check D1/D2/D3. "Full test" is NOT just pytest — it is the four-part
  plugin health check: (full test) the whole test suite the CI way + chip-AGNOSTIC
  source guard, (D1) every program has a test, (D2) every flow step has a
  compliance checker, (D3) every skill has no deterministic rule still hiding in
  prose (program-first residual). D1+D2 are deterministic (delegated to
  programs/plugin_full_audit.py); D3 is the LLM-judgment dimension run here.
---

# full-test-audit — "have full test" = full test + D1 + D2 + D3

When the user says **"have full test"** (or "full test" / "run the full audit" /
"check D1 D2 D3"), they do NOT mean "just run pytest". They mean this **four-part**
plugin-health audit. Run ALL four and report each verdict; never report only the
pytest number.

The split honours the program-first doctrine: the DETERMINISTIC dimensions live
in a program (`programs/plugin_full_audit.py`); only D3 (skill-rule
extractability) needs LLM judgment and is run as a fan-out here.

## Part 1 — Full test (the CI way, not a subset)

**`./run_tests.sh` IS the full suite. A bare `pytest` is NOT.** `pytest.ini`
declares ONE testpath on purpose (`single_testpath_guard.py` pins it), so a bare
`pytest` reaches `programs/tests` and stops there. MEASURED at e37d10e1e that
leaves 141 of 3117 tracked test files unrun — `skills/*/tests` 82,
`mcp-eda/test` 48, `tools/phase1_engine/tests` 8, `_shared` 3 — while the 74
tiers `run_tests.sh` discovers leave none. This section used to instruct the
opposite ("bare pytest from the plugin root, single tree"), which is the
shortcut the owner-level ruling of 2026-08-31 closed:
`full_suite_run_check.py` now classifies an invocation by the population it
COVERS, so the command below is the one it accepts and the bare one is refused.

```bash
# chip-AGNOSTIC source guard (CI step 1a)
python3 <plugin>/programs/source_chip_agnostic_check.py <plugin>
# full suite (CI step 1b) — every tier, not one tree
cd <plugin> && ./run_tests.sh
# and confirm the command you actually ran counts as full:
python3 <plugin>/programs/full_suite_run_check.py --command "./run_tests.sh"
```
Report: passed / failed / skipped, and the guard verdict. A single FAILED is a
fail — surface the failing test, do not round it away. `run_tests.sh` prints the
tier census it discovered first; a tier count that has SHRUNK is itself a
finding, because the cheapest way to make a suite green is to stop running part
of it.

## Part 2 — D1: every program has a test  ·  Part 3 — D2: every step has a checker

Both are deterministic — delegate to the program (do NOT hand-roll the scan):

```bash
python3 <plugin>/programs/plugin_full_audit.py <plugin> --json reports/full_audit.json
```
- **D1** PASS iff every non-helper `programs/*.py` is referenced by some
  `programs/tests/` test. `*_protocol_synth` modules are covered generically by
  `test_all_protocol_synth_overlay.py` (reported separately, not a gap). Any
  OTHER unreferenced program is a real D1 gap → write a dedicated test.
- **D2** PASS iff: `gate_self_assertion_check` finds 0 anti-fabrication
  self-assertion holes; `single_testpath_guard` confirms one test tree; no flow
  step is gated on `files_exist` only WITHOUT an explicit `AUDIT NOTE (by-design`
  marker; and every `program_exit_zero` gate target exists on disk (no dangling).

`plugin_full_audit.py` exits 0 only when D1 AND D2 are both clean.

## Part 4 — D3: every skill has no deterministic rule still in prose

This is the irreducible LLM-judgment dimension — there is no deterministic
"is this prose actually a program" detector. Audit **every** `skills/*/SKILL.md`
(fan out, e.g. 5 skills per agent). For each skill decide:
`FULLY_JUDGMENT` (no extractable rule, or genuinely pure judgment like
`spec-to-rtl` / `phase1`) · `HAS_EXTRACTABLE_RULES` (a few prose rules should be
programs) · `MOSTLY_EXTRACTABLE` (largely a deterministic procedure in prose).
Flag each rule that **reduces to a deterministic check (regex / numeric
threshold / table lookup / structural parse) AND is not already delegated** to a
program. Per the `benchmark-enhancement-capture` 4-way ladder, classify each as
ALREADY-PROGRAM (trim to "enforced by programs/<x>.py") / EXTRACT-NEW (new
program + test, no fabrication) / AUGMENT-EXISTING (report) / KEEP-JUDGMENT.
Be adversarial but do NOT invent extractability where the skill is genuinely
judgment (RTL authoring, dialogue, go/no-go narrative, triage routing).

## Synthesis — report all four

Give one verdict per dimension:
- **Full test**: N passed / M failed (+ guard).
- **D1**: zero gap, or the list of untested non-synth programs.
- **D2**: zero gap, or each finding (self-assertion hole / dangling / undocumented
  presence-only).
- **D3**: K/57 skills clean; list every skill with an extractable rule still in
  prose + its 4-way classification.

"All four green" is the bar. D1/D2 are auto-checkable every run via
`plugin_full_audit.py` (and pinned by `test_plugin_full_audit.py` +
`test_gate_self_assertion_check.py` + `test_single_testpath_guard.py`); D3 is the
judgment pass that catches new prose rules as the plugin grows.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/full-test-audit/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
