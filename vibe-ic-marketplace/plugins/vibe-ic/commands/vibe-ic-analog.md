---
name: vibe-ic-analog
description: Run the standalone Analog A1-A9 track via analog_one_shot_runner, then apply expert fallbacks, output review, and the final analog compliance gates.
argument-hint: <project-dir> [--container <image>] [--blocks <comma-list>] [--allow-deterministic-stubs]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-analog <project-dir>`.
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-analog — Analog A1-A9

This is the standalone front door for the analog track. Phase 1 remains the
canonical design entry point: the project must already contain its Phase-1
design intent, including `L1_DATASHEET.json`, `L5_ADI_SPEC.json`, and an
explicit analog block declaration. If that intent is absent, stop and route
the project through `/vibe-ic-phase1`; do not infer it from downstream
artefacts.

Before running, invoke
`Skill(skill="vibe-ic:analog-flow-orchestrate")`, resolve the PDK, block list,
hardware availability, and target specifications from the user or Phase-1
inputs, and ask about any item that remains undetermined. Read design inputs
only; never inspect an oracle, harness, golden output, or reference solution.

Emit this nine-row plan for every declared block before executing A1:

| Step | Work | Deterministic gate | Expert fallback |
|---|---|---|---|
| A1 | Spec extraction | `analog_a1_spec_extract_check.py` | `analog-spec-extract` |
| A2 | Topology and initial sizing | `analog_a2_topology_select_check.py` | `analog-topology-select`, `analog-sizing` |
| A3 | Netlist generation | `analog_a3_netlist_gen_check.py`, `analog_netlist_pdk_check.py` | `analog-netlist-gen` |
| A4 | Corner sweep and optimization | `analog_a4_corner_sweep_check.py` | `ams-sim`, `analog-sizing-loop` |
| A5 | Analog layout | `analog_a5_layout_check.py` | `analog-layout` |
| A6 | Per-block DRC and LVS | `analog_a6_block_pv_check.py` | `drc-fix`, `lvs-triage` |
| A7 | Extraction and post-layout resimulation | `analog_a7_post_layout_resim_check.py` | `analog-extraction-resim` |
| A8 | Hardmacro generation | `analog_a8_hardmacro_gen_check.py` | `analog-hardmacro-gen` |
| A9 | Hardware and mixed-signal verification | `analog_a9_hw_verify_check.py` | `analog-hw-tuning-loop`, `mixed-signal-cosim` |

Main execution (**program-driven first**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/analog_one_shot_runner.py $ARGUMENTS
```

After the runner finishes:

1. Read `<project-dir>/reports/analog_one_shot.json`; do not infer the verdict
   from the process exit code alone.
2. For each `FAIL`, `WAIVED`, `BLOCKED`, or `PASS_STRUCTURE_ONLY` step, invoke
   the matching expert fallback from the plan, repair only the reported
   defect, and rerun the same runner and deterministic gate. Retry at most
   three times, then stop and report the unresolved evidence.
3. An AI rejection of a deterministic result must first be demonstrated by a
   prompt-derived executable test that fails on that exact result. The repair
   must pass the same test and the normal gate before review resumes.
4. When the runner has no unresolved step, invoke
   `Skill(skill="vibe-ic:analog-output-verify")` for the independent residual
   engineering review. If it rejects an output, preserve its executable
   challenge and rerun the affected deterministic gate after repair.

Run both final gates after the review:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/analog_flow_compliance_check.py \
    <project-dir> --json <project-dir>/reports/analog_compliance.json
python3 ${CLAUDE_PLUGIN_ROOT}/programs/analog_a8_before_floorplan_check.py \
    <project-dir> --json <project-dir>/reports/analog_a8_before_floorplan.json
```

`analog_flow_compliance_check.py` must exit 0 before declaring the analog
track PASS or PASS_WITH_WAIVERS. The ordering gate must not FAIL. Its exit 2
means the A8-before-floorplan relation was NOT CHECKED (for example, floorplan
has not run yet), not PASS; report that state verbatim and re-run the gate once
floorplan exists. A9 is the only analog step allowed to continue in parallel
with digital Step 15 and later.

Never promote `SKIP`, `VACUOUS_PASS`, `PASS_STRUCTURE_ONLY`, a missing report,
or a killed run to PASS. Apply the shared anti-fabrication rules in
`commands/_anti_fabrication_rules.md` to every emitted artefact and verdict.
