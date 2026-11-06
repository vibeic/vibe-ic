---
name: analog-output-verify
description: After analog_one_shot_runner emits A1..A9 outputs, AI spot-checks corner-sim coverage, hardmacro completeness, HIL data fidelity. Triggers on /vibe-ic-analog PASS or phrases like "review analog", "verify A8 hardmacro", "check analog corners".
tier: verification
paired_program: analog_one_shot_runner.py
---

# Analog Output Verification

**Purpose**: analog runner is a thin chain marking each A1..A9 as PASS / WAIVED. WAIVED means human / domain skill needed. Even PASS steps need verification — analog correctness is rarely binary.

> **v1.6.14 Wave 90 — step renumber.** Pre-release decimal/sub-step
> ids were integerised; the analog track is now A1-A9 (A1-A5 unchanged,
> per-block PV is A6, Resim/Hardmacro/Cosim are A7/A8/A9).

## Verification checklist

For each block declared by the input documents, read the selected native
producer's report and the original min/max specification. Inspect the actual
netlist and simulator output, PVT corner results, placed geometry, DRC/LVS,
extracted re-simulation, hardmacro views and hardware measurements when those
steps were requested.

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Check that each declared block and corner has its own measurement. Compare
pre-layout, post-layout and hardware values under matching conditions.
Disclose missing coverage and modelling limits. Review the LEF outline against
the actual GDS geometry. Use the original degradation/correlation limits; do
not replace them with a universal software pass band.

### A1 spec_extract — AI judgment
- A1_spec.json should match L5_ADI_SPEC.json's block entry
- **Confirm specs are silicon-realistic** (e.g. V > 5V on a 1.8V device,
  a bandwidth implausible for the chosen process). Needs device-class
  limits + physical reading of the spec — KEEP-JUDGMENT.

### A2 topology_select — AI judgment
- A2_topology.json names a real topology (cascode / two-stage / Miller / etc.)
- **Topology choice consistent with A1 spec** (high-gain → two-stage,
  low-power → folded cascode). A soft heuristic mapping, not a strict
  table — KEEP-JUDGMENT.

## Spot-check actions (AI judgment over green-gate data)

- **Eyeball A4_corners.json / A7 / A9 data for outliers and systematic
  offsets** that the numeric gates pass (e.g. one corner consistently
  off in the same direction). Pattern-recognition over data already
  within threshold — KEEP-JUDGMENT.
- The LEF-vs-GDS outline numeric cross-check is now `analog_lef_gds_outline_check.py`.

## When to escalate

- A4 corner FAIL → invoke `analog-sizing-loop` to retune
- A7 vs A4 delta > 30% → invoke `analog-extraction-resim` debug
- A9 vs A7 delta > 15% → invoke `analog-hw-tuning-loop`

## Output

Append findings to `<project>/reports/analog_verify.md`.
