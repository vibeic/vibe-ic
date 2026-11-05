---
name: full-test-audit
description: >-
  Run when the user says "have full test", "full test", "run the full audit", or
  asks to check D3. "Full test" is NOT just pytest — it is the two-part
  plugin health check: (full test) the whole test suite the CI way + chip-AGNOSTIC
  source guard, (D3) every skill has no deterministic rule still hiding in
  prose (program-first residual).
---

# full-test-audit — "have full test" = full test + D3

When the user says **"have full test"** (or "full test" / "run the full audit" /
"check D3"), they do NOT mean "just run pytest". They mean this **two-part**
plugin-health audit. Run both parts and report each verdict; never report only the
pytest number.

## Part 1 — Full test (the CI way, not a subset)

**`./run_tests.sh` IS the full suite. A bare `pytest` is NOT.** `pytest.ini`
declares ONE testpath on purpose, so a bare
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

## Synthesis — report both parts

Give one verdict per dimension:
- **Full test**: N passed / M failed (+ guard).
- **D3**: K/57 skills clean; list every skill with an extractable rule still in
  prose + its 4-way classification.

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
