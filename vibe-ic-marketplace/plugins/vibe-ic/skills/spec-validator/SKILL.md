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

### 1. ds_quality_check.py — Datasheet Scoring (0-100)

Scores a Markdown datasheet on 10 criteria (0-10 each):

| # | Criterion | Full marks when... |
|---|-----------|-------------------|
| 1 | Features | Section exists, >=5 bullet items |
| 2 | Description | >=2 paragraphs |
| 3 | Pin Configuration | Table with >=3 columns |
| 4 | Absolute Maximum Ratings | Table exists with >=5 params |
| 5 | Recommended Operating Conditions | Table with min/typ/max |
| 6 | Electrical Characteristics | DC + AC sections with tables |
| 7 | Timing Diagrams | ASCII art or description present |
| 8 | Block Diagram | Visual diagram present |
| 9 | Detailed Description + Register Map | Long description + register table |
| 10 | Application Information | Circuit diagram + component values |

```bash
python3 tools/vibe_ic_tools/ds_quality_check.py phase1_spec/04_datasheet.md
python3 tools/vibe_ic_tools/ds_quality_check.py phase1_spec/04_datasheet.md --json
```

**Checkpoint 1 threshold: score >= 70/100**

### 2. an_validator.py — Application Note Scoring (0-80)

Scores on 8 criteria (0-10 each):

| # | Criterion | Full marks when... |
|---|-----------|-------------------|
| 1 | Overview | >=2 paragraphs, >300 chars |
| 2 | Typical Application Circuit | ASCII schematic + components |
| 3 | External Component Selection | Table + values |
| 4 | PCB Layout | Guidelines + diagram |
| 5 | Firmware Example | Code block + register ops |
| 6 | Design Calculations | >=3 formulas + values |
| 7 | FAQ | >=5 Q&A items |
| 8 | Competitive Comparison | Table with >=3 products |

```bash
python3 tools/vibe_ic_tools/an_validator.py phase1_spec/05_appnote.md
python3 tools/vibe_ic_tools/an_validator.py phase1_spec/05_appnote.md --json
```

**Checkpoint 1 threshold: score >= 56/80**

### 3. spec_validator.py — Cross-Consistency Check

Compares identifiers across documents:
- Pin names: DS Pin Configuration vs AN Typical Application Circuit
- Register addresses: DS Register Map vs AN Firmware Example
- TBD/TODO values: must be zero across all documents

```bash
python3 tools/vibe_ic_tools/spec_validator.py \
    --ds phase1_spec/04_datasheet.md \
    --an phase1_spec/05_appnote.md \
    --spec phase1_spec/03_spec_confirmed.md

python3 tools/vibe_ic_tools/spec_validator.py \
    --ds phase1_spec/04_datasheet.md \
    --an phase1_spec/05_appnote.md \
    --json
```

**Checkpoint 1 threshold: 0 ERROR-level mismatches**

## Workflow

1. Run `ds_quality_check.py` on the datasheet
2. Run `an_validator.py` on the application note
3. Run `spec_validator.py` to cross-check both (+ spec if available)
4. If any check fails threshold, report findings and block Phase 2 entry
5. Log results via `vibe_ic_log.py`

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
