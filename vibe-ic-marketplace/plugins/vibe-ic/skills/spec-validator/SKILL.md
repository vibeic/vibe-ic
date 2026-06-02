---
name: spec-validator
description: "Cross-check Datasheet, Application Note, and Spec for consistency. Detects pin name mismatches, register address conflicts, and unresolved TBD values. Also runs auto-quality scoring on DS (0-100) and AN (0-80). Triggers when: 'check consistency', 'validate docs', 'cross-check DS and AN', 'are the docs consistent', 'run spec validator', or before Checkpoint 1 gate. This is an automated pre-gate check — run before every Phase 1 to Phase 2 transition."
---

# Spec Validator — Cross-Consistency + Quality Scoring

Ensures that Datasheet, Application Note, and Specification are internally consistent and meet minimum quality thresholds before advancing to Phase 2 (Design).

## When to use

- Before running checkpoint-gate for Phase 1 -> Phase 2
- After generating or editing a datasheet or application note
- When user says "check docs", "validate", "cross-check", "consistency"
- Proactively before any Phase 2 tool invocation

## Tools

> All four checks below are **enforced by deterministic programs**, not prose to
> grade by hand. The exact criteria, weights and thresholds live in
> `programs/ds_quality_check.py`, `programs/an_validator.py`,
> `programs/spec_validator.py` and `programs/spec_conformance_check.py` so every
> agent gets the identical verdict. **Run the program — do not re-grade the table
> mentally.** All four are chip-AGNOSTIC, pure-stdlib, follow the
> `main(argv)->int` 0/1/2 contract, and degrade to `MISSING`/`SKIP` (never a
> false FAIL) on absent or unexpected input.

### 1. ds_quality_check.py — Datasheet (L1) Scoring (0-100)

Scores a Markdown datasheet on 10 criteria (0-10 each: Features, Description,
Pin Configuration, Absolute Maximum Ratings, Recommended Operating Conditions,
Electrical Characteristics, Timing Diagrams, Block Diagram, Detailed
Description + Register Map, Application Information). **Run it:**

```bash
# single file or a project dir (auto-locates the datasheet)
python3 programs/ds_quality_check.py phase1_spec/04_datasheet.md --json
python3 programs/ds_quality_check.py <project_dir> --json
```

Output: `{score, max:100, threshold:70, verdict, breakdown:[...]}`.
**Checkpoint 1 threshold: score >= 70/100** (exit 0 = PASS, 1 = FAIL,
2 = MISSING/empty — treat MISSING as "datasheet not produced yet", not a fail).

### 2. an_validator.py — Application Note (AN) Scoring (0-80)

Scores a Markdown application note on 8 criteria (0-10 each: Overview, Typical
Application Circuit, External Component Selection, PCB Layout, Firmware Example,
Design Calculations, FAQ, Competitive Comparison). **Run it:**

```bash
python3 programs/an_validator.py phase1_spec/05_appnote.md --json
python3 programs/an_validator.py <project_dir> --json
```

Output: `{score, max:80, threshold:56, verdict, breakdown:[...]}`.
**Checkpoint 1 threshold: score >= 56/80.**

### 3. spec_validator.py — DS↔AN Cross-Consistency Check

Cross-checks identifiers between documents (DS Pin Configuration ↔ AN Typical
Application Circuit; DS Register Map ↔ AN Firmware Example; and TBD/TODO/
placeholder tokens that must be zero across all docs). Identifiers are parsed
structurally from the docs — never compared against a hard-coded pin/register
list — and a check is **SKIPPED** (not flagged) when either side lacks the
section or parsable identifiers, so a sparse doc never produces a false
mismatch. **Run it:**

```bash
python3 programs/spec_validator.py \
    --ds phase1_spec/04_datasheet.md \
    --an phase1_spec/05_appnote.md \
    --spec phase1_spec/03_spec_confirmed.md --json
# or auto-locate DS + AN inside a project dir:
python3 programs/spec_validator.py <project_dir> --json
```

Output: `{verdict, error_count, findings:[...]}` with rules `pin-mismatch`,
`register-mismatch`, `unresolved-tbd` (all ERROR) and `section-missing` (INFO/
SKIP). **Checkpoint 1 threshold: 0 ERROR-level mismatches.**

**AI judgment (keep):** a passing score is necessary, not sufficient. Still
eyeball the `breakdown` for criteria that scored full marks on thin content
(e.g. a register table with placeholder rows), and confirm any
`section-missing` SKIP is genuinely "section not applicable for this IC class"
rather than "section forgotten". Use `/datasheet-gen` to raise a low DS score.

### 4. spec_conformance_check.py — Spec↔RTL contract gate (once RTL exists)

The checks above keep the *documents* consistent. Once RTL is drafted, this gate
proves the *implementation* matches the declared contract — the failure that
slips past pure structural lints (e.g. a spec that says "synchronous reset"
while the RTL is asynchronous, or an interface whose ports drifted from the
spec). It extracts the expected interface + reset semantics + output latency
straight from the spec (natural-language bullets `- input d (8 bits)`, a
markdown ```verilog module(...)``` header, or a JSON contract) — no hand-built
port list — and diffs it against the RTL.

```bash
# CLI
python3 programs/spec_conformance_check.py --spec phase1_spec/04_datasheet.md \
    --rtl-dir phase2/stage1/rtl --top <module>
# MCP (preferred in-flow)
#   eda_spec_conformance { spec, rtl_dir|verilog_files, top }
```

Findings: `port-missing/extra/direction/width`, `reset-mode-spec-mismatch`,
`reset-polarity-spec-mismatch` (all ERROR); `reset-not-found` (WARN);
`latency-mismatch` (INFO). **Threshold: 0 ERROR.** If a `reset-*-spec-mismatch`
fires, reconcile the spec wording against the reference/testbench before Phase 2 —
a blind spec-faithful RTL will otherwise mismatch the bench.

## Workflow

1. Run `ds_quality_check.py` on the datasheet
2. Run `an_validator.py` on the application note
3. Run `spec_validator.py` to cross-check both (+ spec if available)
4. Once RTL exists, run `spec_conformance_check.py` (or `eda_spec_conformance`)
   to prove the RTL conforms to the spec's ports + reset + latency contract
5. If any check fails threshold, report findings and block Phase 2 entry
6. Log results via `vibe_ic_log.py`

## Output format

Each tool outputs both human-readable text and `--json` machine-readable format.

JSON outputs can be piped to `vibe_ic_log.py` for unified pipeline logging.

## Handoff

- All checks pass -> `/checkpoint-gate` (Phase 1 -> Phase 2)
- DS score low -> improve datasheet with `/datasheet-gen`
- AN score low -> improve application note
- Mismatches found -> fix inconsistencies before proceeding

## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit. This guarantees that different agents executing this same SKILL.md
produce reports containing the same required elements, even when the prose
inside each element differs. Missing elements are the single largest
source of skill-execution non-determinism.
