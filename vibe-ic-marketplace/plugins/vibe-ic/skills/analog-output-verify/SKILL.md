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

For each analog block in `<project>/analog/<block>/`:

**Run the deterministic gates first**, then apply the AI judgment
below. Every fixed threshold / file-existence / structural rule on this
track is enforced by a program — do not re-assert them by eye:

| Step | Gate | Enforces |
|------|------|----------|
| A3 | `programs/analog_a3_netlist_gen_check.py` + `programs/analog_netlist_pdk_check.py` | `.sp` substance (`.subckt`, size), PDK model/body/device-name compliance |
| A4 | `programs/analog_corner_margin_check.py` | ≥27-corner PVT cube + ≥10% margin/corner (stricter than the 9-corner `analog_corner_sweep_check.py`); accepts `A4_corners.json` or `corner_results.json`, self-skips on stub |
| A5 | `programs/analog_a5_layout_check.py` | `layout.mag`/`<block>.gds` exists with real placed geometry, for **EVERY** declared block (partial coverage → `INCOMPLETE`, never PASS) + zero-violation DRC and match LVS evidence read with **A6's precedence** (`drc.report`/`*.lyrdb` then `drc_clean.flag`; `comp.json`/`lvs.report` then `lvs_match.flag`) — a bare or 0-byte flag with no report beside it is not sign-off |
| A6 | `programs/analog_per_block_pv_completeness_check.py` + `programs/analog_a6_block_pv_check.py` | full per-block deliverable set + DRC=0 / LVS=match evidence |
| A7 | `programs/analog_pre_vs_post_layout_check.py` (+ `analog_a7_post_layout_resim_check.py`) | post-vs-pre degradation bands (≤20% INFO / >20% WARN / >30% FAIL) |
| A8 | `programs/analog_a8_hardmacro_gen_check.py` + `programs/analog_hardmacro_check.py` | LEF+lib+GDS+Verilog present & non-stub |
| A8 outline | `programs/analog_lef_gds_outline_check.py` | **LEF `SIZE w BY h ;` matches the GDS bounding box** (the "LEF matches GDS outline" + "cross-check LEF outline vs A5 extents" spot-check, now a numeric gate; honest FAIL on mismatch / missing-half / garbage GDS) |
| A9 | `programs/analog_hw_spice_correlation_check.py` | HW-vs-SPICE error bands (<5% PASS / 5-15% WARN / >15% FAIL) |

```bash
python3 ../../programs/analog_corner_margin_check.py <project> \
    --json <project>/reports/gates/analog_corner_margin.json
python3 ../../programs/analog_lef_gds_outline_check.py <project> \
    --json <project>/reports/gates/analog_lef_gds_outline.json
# (the A1-A9 gates above run inside analog_one_shot_runner; re-run any
#  individually if a verdict is in doubt)
```

Exit 0 = PASS (or self-skip / VACUOUS_PASS), 1 = FAIL. After every gate
is green, apply the AI judgment below — these are the residual checks
the programs **cannot** make.

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

