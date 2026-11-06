---
name: analog-flow-orchestrate
description: Canonical reference doc for the Analog A1-A9 track — spec extraction → topology → netlist → corner sweep → layout → per-block PV (DRC/LVS) → post-layout resim → hardmacro → HIL. Used when an agent wants to walk the A1-A9 plan step-by-step. For unified one-command execution (deterministic runner + AI fall-through + final audit aggregated), prefer the slash command `/vibe-ic-analog` (v1.6.13+) which merges this skill's workflow with `analog_one_shot_runner.py`.
---

# Analog Flow Orchestrate — **9-STEP ANALOG TRACK**

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Native tools supply the measurements; AI reviews every result.

## Read the native analog results

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Use the analog steps selected by the current table. Open their actual SPICE,
layout, DRC, LVS and extracted-model results for every declared block.

## Scope

- Input: `generated_docs/L1_DATASHEET.json` + `generated_docs/L5_ADI_SPEC.json` + PDK
- Output: `hardmacro/<block>/` deliverables (GDS + LEF + Liberty + behavioral Verilog) per analog block
- Decision: each selected native measurement meets its original limit and its engineering review is complete.

## Analog work and native evidence

| Work | Skill | Native evidence to review |
|------|-------|---------------------------|
| Specification | `analog-spec-extract` | Required blocks, electrical limits and conditions |
| Topology and sizing | `analog-topology-select`, `analog-sizing` | Circuit choice and sized netlist |
| Netlist | `analog-netlist-gen` | Native simulator elaboration and operating point |
| PVT optimization | `analog-sizing-loop` | Per-corner SPICE values against original bounds |
| Layout | `analog-layout` | Actual placed geometry |
| Physical verification | `drc-fix`, `lvs-triage` | Native DRC and LVS results |
| Extraction and re-simulation | `analog-extraction-resim` | Extracted parasitics and post-layout SPICE |
| Hardmacro | `analog-hardmacro-gen` | LEF, Liberty, GDS and behavioral views for their consumers |
| Hardware and mixed signal | `analog-hw-tuning-loop`, `mixed-signal-cosim` | Actual waveform/ADC and mixed-signal results |

The current step table selects execution and user-facing numbering. This
reference does not create an additional nine-row acceptance layer.

## Track dependencies and scope

Analog hardmacro LEF, Liberty, GDS and behavioral models must exist before a
digital tool consumes them. Follow the current table's dependencies rather
than adding a separate ordering gate. Hardware verification may proceed in
parallel when it does not supply an input to the physical tool.

Show the selected plan and every block's measured, failed or unmeasured work.
Unavailable hardware leaves its measurement open. A waiver records scope; it
does not make an unexecuted measurement pass.

## Orchestration workflow

1. Read the source documents and enumerate the required analog blocks.
2. Show the selected native steps, dependencies and original requirements.
3. Execute each owning tool through the normal public runner.
4. Read its native measurements and review their engineering meaning.
5. Fix the design, tool or plugin when a result exposes a problem, then rerun
   the affected native work without changing limits.
6. Report every measured, failed or unavailable result for each block.

Choose a different sizing, topology or layout only when the circuit and native
results support it. Keep source limits and PDK constraints unchanged.

## Timing integration with digital work

Follow the dependencies in the current step table. A physical tool needs the
actual hardmacro views before it can place or analyze those blocks. Hardware
work can run independently when it does not provide an input to the selected
physical step. Report the current table position and step name to the user.

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
- Do not declare PASS without the applicable native measurement meeting its original limit and its engineering review being complete.
- Do not block the digital track — A9 is the only step that can run past Step 15

## Review completion

Read each selected native result against its original limit and review every
block. Report failed and unmeasured items with their actual scope. Native
measurements determine completion; a separate compliance or ordering receipt
does not.
