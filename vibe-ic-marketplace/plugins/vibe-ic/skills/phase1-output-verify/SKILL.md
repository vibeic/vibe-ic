---
name: phase1-output-verify
description: After phase1_one_shot_runner emits 13 L*.json, AI spot-checks completeness and authenticity. Triggers on phrases like "verify L docs", "check phase 2a output", "confirm extraction is correct", or automatically when /vibe-ic-phase1 / /vibe-ic-phase2 returns PASS.
tier: verification
paired_program: phase1_one_shot_runner.py
---

# Phase 2a Output Verification

**Purpose**: deterministic phase1 runner emits typed L docs from input/docs, but its mechanical regex extraction can:
- miss vendor docs that use unusual formatting
- emit `__TODO__` stubs for fields it couldn't parse
- fabricate plausible-looking but incorrect values
- skip whole sections silently

After runner reports PASS, AI invokes this skill to spot-check.

## Verification checklist

For each L*.json produced:

1. **Completeness**: open every L doc, count `__TODO__` strings. >0 means incomplete extraction. Action: re-run phase1 runner with patched extractor, or fall back to corresponding NL doc-gen skill.

2. **Schema**: confirm L1 has `pin_table[]`, L3 has `opcodes[]`, L4 has `registers[]` or `otp_layout`, L8 has `rx_classifier_ticks` + `timing_constants`, L9 has `top_module` + `ports` + `submodules`, etc. Fields cited by `phase1_doc_content_implementation_completeness_check`.

3. **Cross-doc consistency**:
   - L3.opcodes hex set ⊂ L9.fsm_states transitions
   - L3.verdict_byte_offset matches rig_topology fingerprint_byte_index
   - L1.pin_table names ⊂ L9.ports names (or aliased)
   - L11.otp_bytes addresses ⊂ L4.otp_layout fields
   - L8.rx_classifier_ticks values match RTL parameters when phase2 is run

4. **Anti-fabrication**: scan input_doc/*.txt for every L doc value. Confirm every numeric / hex / opcode / pin name has a citation. Use `extraction_evidence` blocks.

5. **Coverage report**: read `<project>/reports/extraction_coverage_report.json`. `overall.pct` should be 100. If <100%, identify which input doc has uncovered sections.

## Spot-check actions

- Read 3 random sections from input_doc/*.txt → grep through generated_docs/*.json → if NOT found, flag the section as "extracted but not cited" and report.
- Compare L docs from this project vs a reference well-extracted project (same chip class). Note structural deltas.
- If user expressed specific intent ("this chip has feature X"), confirm L docs encode feature X.

## When to escalate

- Spot-check finds >5 issues → suggest re-running phase1 with patched gen_l*_* OR invoke specific doc-gen skill (datasheet-gen, frs-gen, etc.) for the failing layer.
- Spot-check finds 1-3 issues → patch directly via Edit on the L doc and add waiver entry citing the manual fix.

## Output

Append findings to `<project>/reports/phase1_verify.md`. If all checks pass, write a single-line PASS summary.

## Reference programs

- `programs/phase1_one_shot_runner.py` — what it produces
- `programs/phase1_doc_content_implementation_completeness_check.py` — citation gate
- `programs/extraction_coverage_check.py` — typed-field coverage
- `programs/l_doc_structured_field_count_check.py` — typed-depth gate


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

