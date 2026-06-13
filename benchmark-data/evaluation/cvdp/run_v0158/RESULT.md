# CVDP example dataset — Shape D on v0.1.58 (blind re-run)

> Triggered by user "run CVDP" after v0.1.58 (R8 capture landed).
> § 8.1 default: re-run blind. § 4.1: re-justify FLOOR from THIS run.

## Headline

| Metric | Value |
|---|---|
| Plugin version | v0.1.58 |
| Shape | **D — agentic with runner** |
| Problems | **N=2** (general agentic_jsonl_to_shape_d extractor) |
| Runner aggregate verdict | **PASS_WITH_WAIVERS / 2** ⬆ (was FAIL/2 on v0.1.57) |
| Cocotb verdict | **0 / 2 PASS** (unchanged) — both FLOOR re-justified |

## What v0.1.58 changed vs v0.1.57

R8 fixed the phantom `agent_report_sha256_attestation_check` FAIL by
emitting `reports/final_summary.md` BEFORE `step_final_audit` (the FPGA-
burn path already did this; the `--skip-hardware` path was missing it).
The cocotb harness itself is untouched, so Project 1's Cat-A spec↔harness
inconsistency and Project 2's Cat-D substitution gap both surface
identically to v0.1.57 — they're documented as honest FLOOR, not
"recovered".

| Aspect | v0.1.57 | v0.1.58 |
|---|---|---|
| Project 1 runner verdict | **FAIL** (phantom attestation) | **PASS_WITH_WAIVERS** |
| Project 2 runner verdict | **FAIL** (phantom attestation) | **PASS_WITH_WAIVERS** |
| Project 1 cocotb verdict | FAIL (Cat A) | FAIL (Cat A) — unchanged |
| Project 2 cocotb verdict | FAIL (Cat D) | FAIL (Cat D) — unchanged |
| Project 2 harness_error label | `cocotb-tools-typeerror` | `cocotb-tools-typeerror` — preserved |

## Per-problem § 4 triage (re-justified from THIS run)

### Project 1 — `fixed_priority_arbiter` — Cat A FLOOR (re-justified)

- Authoring: spec-literal synchronous reset per spec line 54
  ("Active-high synchronous reset").
- Runner phase1: 14/14 L docs, 100% coverage.
- Runner phase2: `yosys_synth` PASS (61 cells); `sdc_gen`, manifests PASS.
- Runner audit: `Overall: PASS_WITH_WAIVERS (strict=True)` — 3 thin-input
  structural gates correctly WAIVED-DEFERRED.
- Cocotb: `TESTS=1 PASS=0 FAIL=1 SKIP=0`.
- Cat A evidence (from THIS run): hidden harness `reset_dut(active=False)`
  reads `grant` immediately after `RisingEdge(clk)` racing the synchronous
  NBA update — unsatisfiable blind without violating spec line 54.
- `harness_error: null` — v0.1.57 R6 correctly distinguishes Cat A
  (DUT-FAIL) from Cat D (harness-substitution); this is the former.

### Project 2 — `priority_encoder_8x3` — Cat D FLOOR (re-justified)

- Authoring: 8-to-3 MSB-priority cascade per prompt.
- Runner phase1: 14/14 L docs, 100% coverage.
- Runner phase2: `yosys_synth` PASS (14 cells); `sdc_gen`, manifests PASS.
- Runner audit: `Overall: PASS_WITH_WAIVERS (strict=True)`.
- Cocotb: `TESTS=0 PASS=0 FAIL=0 SKIP=0`.
- `harness_error: {kind: 'cocotb-tools-typeerror', signal: 'TypeError:
  int() argument must be a string'}` — Cat D auto-labelled by v0.1.57 R6.
- Cat D evidence: iverilog build succeeded; cocotb-tools' `runner.test()`
  raised TypeError in `harness_library.py:24` BEFORE any test could run.
  iic-eda container's cocotb 2.0.1 substitution vs the gated
  `nvidia/cvdp-sim:v1.0.0` (per § 3 substitution disclosure).

## Tool substitution (§ 3)

`iic-eda` container (hpretl/iic-osic-tools): iverilog 13 + cocotb 2.0.1
substitutes `nvidia/cvdp-sim:v1.0.0`. Project 2's `cocotb-tools-typeerror`
is direct evidence of the version-stack mismatch.

## Reproduce

```bash
PLUGIN=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.58
DATASET=/home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark/example_dataset
RUN=benchmark_external/cvdp/run_v0158
STAGE=/home/reyerchu/AI_IC_design/_vibeic_cvdp_v0158

python3 $PLUGIN/programs/benchmark_dispatch.py cvdp \
    --setup --dataset $DATASET --run $RUN

for P in $(cat $RUN/problems.list); do
    TOP=...
    rsync -a $RUN/$P $STAGE/
    mkdir -p $STAGE/$P/input/docs
    cp $STAGE/$P/work/PROMPT.txt $STAGE/$P/input/phase1_prompt.md
    cp $STAGE/$P/work/PROMPT.txt $STAGE/$P/input/docs/design_description.md
    python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $STAGE/$P \
        --skip-phase3 --skip-analog --skip-hardware --top-name $TOP --ic-name $TOP
    # [author RTL into $STAGE/$P/phase2/stage1/rtl/$TOP.sv per spec-to-rtl]
    python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $STAGE/$P \
        --skip-phase3 --skip-analog --skip-hardware --skip-phase1 \
        --top-name $TOP --ic-name $TOP
    mkdir -p $STAGE/$P/work/rtl
    cp $STAGE/$P/phase2/stage1/rtl/$TOP.sv $STAGE/$P/work/rtl/
    python3 $PLUGIN/benchmark-harness/score_cocotb_mcp.py \
        --project $STAGE/$P --top $TOP --rtl work/rtl/$TOP.sv \
        --mount-root /home/reyerchu/AI_IC_design
done
```

## Comparison across plugin versions

| Run | Runner verdict | Cocotb verdict | What was honest about it |
|---|---|---|---|
| run_fresh_v0125 | (n/a direct-agent) | PASS 9/9 | Wrong shape; async manual switch |
| run_v0153_runner | (analog FAIL noise) | PASS 1/1 | Sync→async manual switch |
| run_v0156 | FAIL/2 (analog noise) | 0/2 | First honest baseline; R3+R4 cheating reverted |
| run_v0157 | FAIL/2 (phantom attestation) | 0/2 | R6+R7 visible: Cat-D auto-label + structural waivers |
| **run_v0158** | **PASS_WITH_WAIVERS / 2** | **0/2** | R8: runner verdict now honest; cocotb unchanged |

The runner-verdict trajectory v0.1.56 FAIL → v0.1.58 PASS_WITH_WAIVERS
reflects three honesty fixes (R6 + R7 + R8), not a "real" pass@1
improvement — the cocotb-side number is still 0/2 because the spec↔harness
inconsistency and substitution gap are real benchmark-side floors.

## § 4.1 doctrine validation

Re-attempted blind on v0.1.58. Both FLOORs survived re-justification from
this run's evidence (cocotb_score.json log_tail for Project 1; auto-emitted
harness_error for Project 2). Both labels are independently verifiable
from JSON — that's the cumulative R6 honesty layer at work.

## v0.1.58 doctrine compliance

- ✅ Scorer single-pass; no variant retry (R3 removed v0.1.56).
- ✅ Dispatcher uses general agentic extractor; zero bench-name branches.
- ✅ Runner audit honest: phantom attestation FAIL closed (R8).
- ✅ Cat-A and Cat-D both re-justified from THIS run's evidence.
- ✅ Cocotb 0/2 stands honestly — no over-fit to hidden oracle.
