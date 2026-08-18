---
name: analog-flow-orchestrate
description: Canonical reference doc for the Analog A1-A9 track — spec extraction → topology → netlist → corner sweep → layout → per-block PV (DRC/LVS) → post-layout resim → hardmacro → HIL. Used when an agent wants to walk the A1-A9 plan step-by-step. For unified one-command execution (deterministic runner + AI fall-through + final audit aggregated), prefer the slash command `/vibe-ic-analog` (v1.6.13+) which merges this skill's workflow with `analog_one_shot_runner.py`.
---

# Analog Flow Orchestrate — **9-STEP ANALOG TRACK**

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first (runner + 9 A-step check gates); AI is the backstop.

## Mandatory Deterministic Preflight

```bash
# 1. Drive the deterministic runner first:
python3 plugins/vibe-ic/programs/analog_one_shot_runner.py <project>

# 2. After each A-step, the corresponding check gate runs deterministically:
python3 plugins/vibe-ic/programs/analog_a1_spec_extract_check.py
python3 plugins/vibe-ic/programs/analog_a2_topology_select_check.py
python3 plugins/vibe-ic/programs/analog_a3_netlist_gen_check.py
python3 plugins/vibe-ic/programs/analog_a4_corner_sweep_check.py
python3 plugins/vibe-ic/programs/analog_a5_layout_check.py
python3 plugins/vibe-ic/programs/analog_a6_block_pv_check.py
python3 plugins/vibe-ic/programs/analog_a7_post_layout_resim_check.py
python3 plugins/vibe-ic/programs/analog_a8_hardmacro_gen_check.py
python3 plugins/vibe-ic/programs/analog_a9_hw_verify_check.py

# 3. Ordering gate — A8 must finish before digital Step 15 floorplan
#    (Hard rules #1 + #2), enforced deterministically:
python3 plugins/vibe-ic/programs/analog_a8_before_floorplan_check.py <project>
```

The skill is the CANONICAL REFERENCE for A1-A9 semantics. **The runner
+ 9 step-check programs are the source of truth for PASS / FAIL.**
Refuse to override their verdicts.

> **Merged into `/vibe-ic-analog` slash command (v1.6.13+).** This skill
> remains as the canonical reference for the A1-A9 step semantics, the
> per-step skill mapping, and the gate-predicate definitions. The slash
> command implements the orchestration workflow described here so the
> agent does not have to invoke skill + runner separately. Use this
> skill directly when you want the A1-A9 plan without first running
> the deterministic runner; otherwise prefer `/vibe-ic-analog`.

The analog counterpart to `flow-orchestrate`. Manages the complete analog design pipeline from spec extraction through hardware-verified convergence to hardmacro packaging. Runs in parallel with the digital track (Steps 1-13), converging before digital Step 15 (Floorplan; was Step 14 pre-Wave-91).

## Scope

- Input: `generated_docs/L1_DATASHEET.json` + `generated_docs/L5_ADI_SPEC.json` + PDK
- Output: `hardmacro/<block>/` deliverables (GDS + LEF + Liberty + behavioral Verilog) per analog block
- Decision: PASS iff `analog_flow_compliance_check` exits 0

## The 9 steps

| # | Step | Skill | Gate |
|---|------|-------|------|
| A1 | Analog Spec Extraction | `analog-spec-extract` | `analog/<block>/spec.json` per detected block |
| A2 | Topology + Initial Sizing | `analog-topology-select` + `analog-sizing` | `topology.md` + `sizing.md` per block |
| A3 | Netlist Generation | `analog-netlist-gen` | `analog_netlist_pdk_check` exits 0 |
| A4 | Corner Sweep + Optimization | `analog-sizing-loop` | `analog_corner_sweep_check` exits 0 |
| A5 | Analog Layout | `analog-layout` + `eda_analog_layout` | `layout.mag` per block |
| A6 | Per-Block Physical Verification (DRC + LVS) | `drc-fix` + `lvs-triage` | `analog_a6_block_pv_check` exits 0 |
| A7 | Post-Layout Extraction + Resim | `analog-extraction-resim` | `analog_pre_vs_post_layout_check` exits 0 |
| A8 | Hardmacro Generation | `analog-hardmacro-gen` | `analog_hardmacro_check` exits 0 |
| A9 | HW Verification + Mixed-Signal | `analog-hw-tuning-loop` + `mixed-signal-cosim` | `analog_hw_spice_correlation_check` + `mixed_signal_cosim_check` exit 0 |

> **v1.6.14 Wave 90 — step renumber.** Pre-release decimal/sub-step
> ids were integerised; the analog track is now A1-A9 (A1-A5 unchanged,
> per-block PV is A6, Resim/Hardmacro/Cosim are A7/A8/A9).

## Hard rules

1. **A8 must complete BEFORE digital Step 15 (Floorplan).** Digital PnR
   needs the LEF/Liberty/GDS to place analog blocks. *Enforced by
   `programs/analog_a8_before_floorplan_check.py`* — FAILs when a floorplan
   DEF exists but any analog block is still missing its A8 hardmacro LEF.
2. **A9 (and only A9) can run in parallel with digital Steps 15+.** Hardware
   verification doesn't block physical design. *Corollary enforced by the
   same `analog_a8_before_floorplan_check.py` ordering gate* (every step ≤ A8
   must precede floorplan; A9 is the sole exception).
3. **No step is optional.** If hardware is unavailable for A9, write a waiver.
   *Enforced by `programs/analog_flow_compliance_check.py`* (every step is
   PASS or carries a waiver in `analog/waivers.json`).
4. **Emit the 9-row plan table BEFORE any step runs.** User must see all 9
   steps up front. This is an interaction/presentation rule (LLM-driven) —
   the deliverable-presence half is covered by `analog_flow_compliance_check.py`.

## Orchestration workflow

```
plan → execute_step_AN → gate_AN → observe → (retry ≤3 or abort) → next step
                                                ↓
                                       final: analog_flow_compliance_check
```

1. **Detect**: Read `generated_docs/L5_ADI_SPEC.json` or scan RTL for analog
   modules. *Enforced by `programs/analog_block_coverage_check.py` +
   `programs/analog_content_detected_must_emit_l5_check.py`* (deterministic
   JSON-read / module-scan; FAILs if docs document analog content but L5 omits it).
2. **Plan**: Emit 9-row table with all blocks × 9 steps (LLM presentation step).
3. **Execute**: Walk A1→A9 in order. For each block, run the named skill.
   The A1→A9 dispatch table + state machine is the deterministic
   `programs/analog_one_shot_runner.py` (source of truth, not this prose).
4. **Gate**: After each step, run its A-step gate program. **Retry decision
   on failure — what to change before retry, and abort-vs-continue — is the
   LLM backstop (see "Per-step retry / abort" below).**
5. **Report**: Write `analog/status.json` (program-emittable) +
   `analog/flow_summary.md` (LLM narrative).
6. **Final gate**: `programs/analog_flow_compliance_check.py` must exit 0,
   and the ordering gate `programs/analog_a8_before_floorplan_check.py`
   must not FAIL.

### Per-step retry / abort (LLM backstop — KEEP)

When an A-step gate FAILs, the deterministic runner reports *which* gate
failed; deciding *what to change* before the retry (resize a device, pick a
different topology, relax a corner, loosen a layout constraint) and *whether
to abort vs continue* after ≤3 retries is genuine engineering judgment that
cannot be reduced to a fixed program. The same applies to the **STOP-and-ask**
branch under "Inputs to gather" — clarifying ambiguous / missing PDK, block
list, HW availability or target specs from a human is interaction, not a check.

## Timing integration with digital track

```
Digital Track            Analog Track
Step 1: spec-to-rtl      A1: spec extraction    ← both start from L1-L27
Step 2: lint              A2: topology + sizing
Step 3: CDC/RDC           A3: netlist gen
Step 4: simulation        A4: corner sweep
Step 5: formal            A5: analog layout
Step 6: FPGA proto        A6: per-block DRC/LVS
Step 7-13: synth+DFT      A7: extraction + resim
                          A8: hardmacro gen
                                ↓ A8 DONE
Step 14: pre-PnR Yosys gate (Wave 91 sentinel)
Step 15: Floorplan  ◄─── hardmacro LEF/GDS placed
Step 16-28: PnR+STA       A9: HW verification (parallel)
Step 29-36: signoff       A9: mixed-signal cosim
```

## Inputs to gather (must be explicit before starting)

1. PDK (gf180 or sky130)
2. Which analog blocks to design (from L5 or user specification)
3. Hardware availability (FPGA board + scope for A9)
4. Target specs per block (from L1 or user specification)

If any input is missing, STOP and ask.

## Output format

### `analog/status.json`
```json
{
  "blocks": ["ldo_1v8", "por", "rc_osc"],
  "steps": {
    "ldo_1v8": {
      "A1": {"status": "PASS", "started": "...", "ended": "..."},
      "A2": {"status": "PASS"},
      "A3": {"status": "PASS"},
      "A4": {"status": "PASS", "iterations": 3},
      "A5": {"status": "PASS"},
      "A6": {"status": "PASS", "drc_clean": true, "lvs_match": true},
      "A7": {"status": "PASS", "degradation_pct": 8.2},
      "A8": {"status": "PASS"},
      "A9": {"status": "PASS", "hw_verified": true, "cosim_pass": true}
    }
  },
  "all_pass": true
}
```

### `analog/flow_summary.md` — human-readable summary

## Do not

- Do not skip A1-A4 (SPICE convergence) and jump to hardware (A9)
- Do not generate hardmacros (A8) before post-layout verification (A7)
- Do not declare PASS without `analog_flow_compliance_check` exit 0
- Do not block the digital track — A9 is the only step that can run past Step 15

## Compliance gate (MANDATORY)

At end of analog flow, run:

```bash
python3 plugins/vibe-ic/programs/analog_flow_compliance_check.py \
    <project_dir> --json <project_dir>/reports/analog_compliance.json
```

Exit 0 → declare PASS. Exit 1 → list failures and recommend next action.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/analog-flow-orchestrate/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.

**Your task is not complete until the audit returns PASS.**
