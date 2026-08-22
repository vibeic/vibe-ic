---
name: phase1-completeness-deep-review
description: After phase1_one_shot_runner emits L*.json, AI does a STRONG double-check that every fact present in input documents (input_doc/ + input/docs/) lands somewhere in generated_docs/L*.json. If anything is missing, AI patches the L doc directly AND evaluates whether the gap is systematic — if so, submits a community-backlog entry so a future plugin/program iteration absorbs it. Mandatory after every phase1 / phase2 / phase23 run before claiming PASS.
tier: verification
paired_program: phase1_doc_input_completeness_check.py
mandatory_after: [vibe-ic-phase1, vibe-ic-phase2, vibe-ic-phase23, vibe-ic-all]
---

# Phase 1 Completeness Deep Review (AI strong check)

**Purpose**: deterministic regex-based gates can only catch tokens
they know how to recognise. A vendor PPT with timing values laid
out across multiple lines, a Chinese-named doc the fname filter
missed, a register table inside a scanned PDF — these slip through
every regex gate but are exactly the facts the user is paying us
to capture.

This skill closes that loop with a **two-tier strong check**:

1. **Tier 1 — deterministic gate** (`phase1_doc_input_completeness_check.py`):
   per-input-doc token-level audit. Flags any single doc with
   <50% capture in `generated_docs/L*.json`.
2. **Tier 2 — AI semantic review** (this skill):
   for every doc the deterministic gate flagged FAIL/WARN, AND for
   every doc with `extraction_strategy == bare_value_harvest`
   evidence (signal of weak extraction), AI reads the source +
   reads every L*.json and confirms semantically that no fact is
   missing.

The skill is **mandatory** after every `/vibe-ic-phase1` /
`/vibe-ic-phase2` / `/vibe-ic-phase23` / `/vibe-ic-all` run before
the agent may claim Overall PASS.

## Workflow

### Step 1 — run the deterministic gate

```bash
python3 \
  /home/<your-user>/AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic/programs/phase1_doc_input_completeness_check.py \
  <project_dir>
```

Reads:
* `<project>/input_doc/*.txt` (preferred) and
  `<project>/input/docs/*.txt` (fallback)
* `<project>/generated_docs/L*.json`

Writes `<project>/reports/phase1_input_vs_generated_completeness.json`
with per-doc `{distinct, captured, captured_pct, missing_sample}`.

### Step 2 — AI semantic review per flagged doc

For every doc with `verdict ∈ {FAIL, WARN}`, OR every doc whose
`captured_pct < 0.95`:

1. **Read the source doc** end-to-end. Identify every:
   - numeric+unit value (timing, voltage, current, frequency)
   - hex constant (opcode, register address, OTP byte)
   - pin/signal/register identifier
   - state-machine state name
   - command name / response code
   - test scenario / mode
   - structured table row
2. **Grep generated_docs/** for each fact (substring match across
   all L*.json). Mark each as **present** or **missing**.
3. **Classify each missing fact**:
   - **Real factual content** (a value the chip needs) → must
     land in an L doc. Pick the right L layer:
     * timing → L8_TIMING_WAVEFORM
     * register/OTP → L4_REGMAP
     * opcode/command → L3_CMD_PROTOCOL
     * pin → L1_DATASHEET
     * FSM state → L6_CONTROL_LOGIC
     * test scenario → L7_TEST_DEBUG / L10_TEST_CASES
     * behavioural sequence → L12_BEHAVIORAL_SEQUENCES
     * etc.
   - **Regex noise** (header artefact, page number, repeated
     boilerplate) → ignore.

### Step 3 — write AI patches to the durable sidecar

**Do NOT edit `generated_docs/L*.json` directly** — those files are
overwritten on every `phase1_one_shot_runner.py` re-run, so any
inline patches are lost. Instead append to the durable sidecar:

```
<project>/phase1/ai_deep_review_patches.json
```

**Path matters**: the sidecar MUST live under `phase1/`. This is the
canonical location the `_path_layout` resolver returns and the location
every consuming gate (`phase1_doc_input_completeness_check`,
`l_doc_structured_field_count_check`) reads. A sidecar written to the
project ROOT (`<project>/ai_deep_review_patches.json`) is the wrong path;
the gates emit a backward-compat WARNING and still read it, but you should
write it under `phase1/` directly.

Sidecar schema:

```json
{
  "_schema_version": "1",
  "patches": {
    "L1_DATASHEET":      [ {entry}, {entry}, ... ],
    "L3_CMD_PROTOCOL":   [ ... ],
    "L4_REGMAP":         [ ... ],
    "L8_TIMING_WAVEFORM":[ ... ],
    "L11_OTP_CONTENT":   [ ... ],
    ...
  }
}
```

Each entry is a dict carrying:

```json
{
  "literal": "<exact substring from source>",
  "kind": "<bom_component_part_number | indexed_pin_signal | "
          "indexed_register_address | protocol_constant | "
          "test_threshold | electrical_value | etc>",
  "source": "<source filename, e.g. AS3616_Datasheet.pdf>",
  "extraction_strategy": "ai_deep_review_patch",
  "rationale": "<one short sentence on why this fact belongs in "
                "this L layer>"
}
```

The completeness gate reads the sidecar, merges its tokens into
the per-layer haystack, and counts each entry as `ai_captured`
in the per-Layer / per-Doc tables. The marker
`extraction_strategy: "ai_deep_review_patch"` distinguishes AI
patches from deterministic-runner output for audit / regression
/ replay.

The sidecar is intended to be reviewed (not auto-deleted) — if
phase1's deterministic extractor later absorbs a pattern, the
corresponding sidecar entries become redundant and may be
removed by hand.

### Step 4 — submit systematic-gap backlog

After patching, ask: **could a future regex / extractor have
caught this without AI?** If YES (the source has a recognisable
pattern the deterministic extractor just doesn't know about
yet), submit a `community-backlog-submit` entry:

* **Symptom**: which doc, which fact pattern was missed
* **Root cause**: which extractor (e.g.
  `gen_l8_timing_waveform_doc`, `gen_l4_regmap`,
  `_TIMING_FNAME_RE`) is the gap in
* **Proposed fix**: the regex / heuristic / fname keyword that
  would have caught it
* **Evidence**: 2-3 lines from the source doc that exhibit the
  pattern
* **Severity**:
  - HIGH if the gap is in a structural-RTL-affecting layer (L3,
    L4, L8, L9)
  - MEDIUM otherwise

Use the existing `vibe-ic:community-backlog-submit` skill (or
write directly to
`<plugin_root>/docs/reports/community_backlog.json`).

The point: every project's AI patches feed the plugin's next
wave of deterministic improvements. Fresh-agent → AI fill →
backlog → next plugin release. The plugin gets monotonically
stronger; no project waits for the plugin.

### Step 5 — re-run deterministic gate to confirm

```bash
python3 \
  /home/<your-user>/AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic/programs/phase1_doc_input_completeness_check.py \
  <project_dir>
```

Now must report `verdict: PASS`. If it still WARNs, the AI
patches missed something — repeat Step 2.

## Output

Write `<project>/reports/phase1_completeness_deep_review.md` with:

```
# Phase 1 Completeness Deep Review

**Verdict**: PASS / WARN / FAIL
**Deterministic gate verdict (before AI patch)**: <verdict>
**Deterministic gate verdict (after AI patch)**:  <verdict>

## Docs reviewed
- <doc_name>: <captured_pct_before> → <captured_pct_after>
- ...

## AI patches applied
| L doc | Fact | Source doc | Strategy |
| --- | --- | --- | --- |
| L8_TIMING_WAVEFORM | tA0=3.5us | AS3616_TxRx_signal_format.txt | ai_deep_review_patch |
| ...

## Backlog submissions
- <BACKLOG-id>: <one-line summary>
- ...

## Residual concerns (if any)
- <doc>: <pct>; AI could not unambiguously extract because <reason>
```

## When to STOP and ask the user

* A "missing fact" in the source is genuinely ambiguous (e.g. a
  PPT slide with a number but no clear label). Do NOT fabricate
  semantic meaning. Either:
  - record as `name: "tA<idx>", rationale: "value harvested
    without semantic label, verbatim from source p.<n>"`, OR
  - flag in residual concerns and ask the user to clarify.
* The source is in a language / script the agent cannot read
  reliably.
* The source contradicts another input doc (consistency conflict
  belongs to `spec-validator`, not this skill).

## What this skill does NOT do

* It does not invent values. Every fact patched into L*.json
  must be traceable to a substring of a real input doc.
* It does not waive the deterministic gate. If after AI patches
  the deterministic gate is still FAIL, the project is FAIL —
  AI cannot waive its way to PASS.
* It does not modify input docs.
* It does not touch `extraction_patterns.json` (that belongs to
  `phase1_coverage_report_gen`); it only edits `generated_docs/`.

## Reference

- Tier-1 program: `programs/phase1_doc_input_completeness_check.py`
- Forbidden waiver prefix: `phase1_input_vs_generated_*`
  (enforced by `phase1_no_waivers_used_check`)
- Sibling skill (lighter spot-check): `phase1-output-verify`
- Backlog skill: `community-backlog-submit`

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
audit.
