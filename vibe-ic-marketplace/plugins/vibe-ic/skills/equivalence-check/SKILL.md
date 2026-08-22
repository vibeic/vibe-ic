---
name: equivalence-check
description: Run Logic Equivalence Checking (LEC) between two representations of a design — RTL vs gate-level netlist, pre-ECO vs post-ECO, or golden vs revised RTL — to prove functional identity. Use when the user says "LEC", "equivalence check", "formal equivalence", "is this netlist equivalent", "post-ECO check".
---

# Equivalence Check (LEC)

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop. Never claim PASS without the tool's verdict.

After every transformation that touches the netlist — synthesis, DFT
insertion, clock gating, ECO — someone has to prove the result is
functionally identical to the golden RTL. This skill drives that check
through MCP-EDA's `eda_lvs` `yosys_equiv` mode.

## Mandatory Deterministic Preflight

```bash
# MCP tool call (handles SAT-engine corner cases since v0.1.12):
eda_lvs({
  mode: "yosys_equiv",
  layout_netlist: "<post-transformation-netlist>.v",
  schematic_netlist: "<golden-netlist>.v",
  top_module: "<top>",
  pdk: "sky130",  // or "gf180" or "custom" with custom_lib
})
```

The tool returns `equiv_cells_total / proven / unproven` plus
`sat_model_unsupported_cells[]` (for custom-PDK Liberty primitives
without built-in SAT models), and writes the result to `reports/lec.json`
(+ optional `reports/lec.rpt`).

**The PASS verdict is NOT decided in this prose — it is enforced by
`programs/lec_equivalence_check.py`.** That deterministic substance gate
independently re-parses the artefacts (alias-resilient across Yosys
`equiv_*` / Cadence Conformal / Synopsys Formality field spellings) and
returns rc=0 (PASS) iff `equivalent==true` AND compared-points > 0 (non-vacuous)
AND non-equivalent points == 0 AND unproven/aborted points == 0 — with an
anti-vacuous-claim guard so a bare `{"equivalent": true}` over 0 compared
points is an HONEST FAIL, never a vacuous PASS. Missing/unparseable
`reports/lec.json` is also an honest FAIL (`LEC_REPORT_MISSING` /
`LEC_REPORT_UNPARSEABLE`), so absence of evidence can never be claimed PASS.

```bash
# Verdict gate (run AFTER eda_lvs / eda_equiv has written reports/lec.json):
python3 programs/lec_equivalence_check.py <project_dir> --json reports/lec_gate.json
# rc 0 = PASS, 1 = FAIL (NOT_EQUIVALENT / NONEQUIV / UNPROVEN / VACUOUS /
#                        NO_POINT_EVIDENCE), 2 = bad-arg / not-a-dir.
```

Refuse to claim PASS based on log inspection alone — the rc of the program
above is the verdict.

## When to use

- Post-synthesis (RTL ↔ synth netlist)
- Post-DFT (pre-DFT ↔ post-DFT netlist, with test pins held at functional values)
- Post-ECO (pre-ECO netlist ↔ post-ECO netlist)
- Post-hand-edit (sanity check RTL refactor)

## Inputs

1. Golden (reference) design
2. Revised design
3. Key-point mapping hints (register name correspondence) if names changed
4. Constraints: which pins are test-mode, which are scan-enable, etc.
5. Tool: Yosys `equiv_*` commands (open), Synopsys Formality, Cadence Conformal

## Workflow

1. **Compile both sides** into a common internal representation
2. **Map key points**: registers, primary I/O, black-box boundaries
3. **Report unmapped points** — usually where the bug is
4. **Run verification** — prove cone-of-logic equivalence per key point
5. **Triage mismatches**:
   - Real functional change → flag to user
   - Reset-state difference → may be benign if documented
   - Uninitialized X-propagation → investigate

## Output format

- `lec/<design>_lec.tcl` (Yosys / Formality script)
- `lec/<design>_report.md`:
  - Mapped / unmapped point count
  - Status per key point
  - Debug pointers for every mismatch

## Tool prerequisites

Open flow: Yosys with `equiv_make` / `equiv_simple` / `equiv_induct`. Commercial: Formality, Conformal. The skill produces the script; execution requires the tool.

## Technical basis

Cone-of-logic equivalence checking with SAT / BDD back-ends is the industry standard for post-synthesis sign-off. Yosys implements this via the `equiv_*` pass family (https://yosyshq.readthedocs.io/).

## Handoff

- Mismatch → `/rtl-repair` or `/eco-plan`
- Re-run after fix → re-invoke this skill

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/equivalence-check/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
