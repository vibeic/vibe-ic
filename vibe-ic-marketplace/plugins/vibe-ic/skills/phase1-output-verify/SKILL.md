---
name: phase1-output-verify
description: After phase1_one_shot_runner emits 13 L*.json, AI spot-checks completeness and authenticity. Triggers on phrases like "verify L docs", "check phase 1 output", "confirm extraction is correct", or automatically when /vibe-ic-phase1 / /vibe-ic-phase2 returns PASS.
tier: verification
paired_program: phase1_one_shot_runner.py
---

# Phase 1 Output Verification

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on residual narrative.

## Mandatory Deterministic Preflight

```bash
python3 plugins/vibe-ic/programs/phase1_verify_aggregate.py \
    <project_dir> \
    --out-md /tmp/phase1_verify.md \
    --out-json /tmp/phase1_verify.json --strict
```

The aggregator runs 7 backing programs (`phase1_all_l_docs_present_check`
through `phase1_gate_contract_check`) AND checks 13 L-doc file presence.
**Refuse to claim verification PASS without the aggregator's `verdict: PASS`.**

**Purpose**: deterministic phase1 runner emits typed L docs from input/docs, but its mechanical regex extraction can:
- miss vendor docs that use unusual formatting
- emit `__TODO__` stubs for fields it couldn't parse
- fabricate plausible-looking but incorrect values
- skip whole sections silently

After runner reports PASS, AI invokes this skill to spot-check.

## Verification checklist

For each L*.json produced:

1. **Completeness** — enforced by `programs/l_doc_todo_stub_count_check.py`
   (counts `__TODO__` across all L docs; FAILs on count>0; VACUOUS_PASS when
   generated_docs absent). Do NOT re-count by eye. On FAIL, re-run phase1
   with patched extractor or fall back to the corresponding NL doc-gen skill.

2. **Schema**: confirm L1 has `pin_table[]`, L3 has `opcodes[]`, L4 has `registers[]` or `otp_layout`, L8 has `rx_classifier_ticks` + `timing_constants`, L9 has `top_module` + `ports` + `submodules`, etc. Fields cited by `phase1_doc_content_implementation_completeness_check`.

3. **Cross-doc consistency** — the structural set-membership relations are
   enforced by `programs/l_doc_cross_consistency_check.py` (honors the
   `no_<field>_in_input` escape valves; FAILs on a real subset violation):
   - L1.pin_table names ⊂ L9.ports names (or aliased) — program-enforced
   - L11.otp_bytes addresses ⊂ L4.otp_layout fields — program-enforced
   The remaining two relations stay AI-judgment (the typed corpus carries
   no `fsm_states.transitions` sub-structure nor any
   `rig_topology.fingerprint_byte_index`, so encoding them would require
   inventing a field the spec never gives):
   - L3.opcodes hex set ⊂ L9 FSM transitions — judgment
   - L3.verdict_byte_offset matches the rig-topology fingerprint byte — judgment
   - L8.rx_classifier_ticks values match RTL parameters when phase2 is run — judgment

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
- `programs/l_doc_todo_stub_count_check.py` — checklist item 1 (`__TODO__` count == 0)
- `programs/l_doc_cross_consistency_check.py` — checklist item 3 (pin_table⊂ports, otp_bytes⊂otp_layout)

Run the two delegated gates directly (both accept a project dir, a phase1
dir, or a generated_docs dir; add `--json` for a machine report):

```bash
python3 plugins/vibe-ic/programs/l_doc_todo_stub_count_check.py <project_dir>
python3 plugins/vibe-ic/programs/l_doc_cross_consistency_check.py <project_dir>
```


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

