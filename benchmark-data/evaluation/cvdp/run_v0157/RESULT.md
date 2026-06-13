# CVDP example dataset — Shape D on v0.1.57 (blind re-run)

> Triggered by user "run CVDP" after v0.1.57 (R6 + R7 captures landed).
> Per § 8.1 default policy: re-run blind on current plugin even though
> prior result (v0.1.56) was 0/2 FLOOR. Per § 4.1: re-justify every
> FLOOR label from THIS run's evidence.

## Headline

| Metric | Value |
|---|---|
| Plugin version | v0.1.57 |
| Shape | **D — agentic with runner** |
| Problems | **N=2** (v0.1.56 general extractor) |
| Cocotb verdict | **0 / 2 PASS** (unchanged vs v0.1.56) — both FLOOR re-justified |
| New v0.1.57 signal | Project 2 now carries explicit `harness_error: {kind: cocotb-tools-typeerror}` (R6); runner audit now PASS_WITH_WAIVERS-class structural gates (R7); one residual: `agent_report_sha256_attestation_check` newly surfaces |

## Why cocotb verdicts didn't change

v0.1.57 captures are CLASSIFICATION / WAIVER infrastructure — they don't
touch RTL authoring, the cocotb harness substitution, or the spec↔harness
inconsistency in Project 1. Same DUT, same hidden harness, same iic-eda
container → same verdicts (0/2). What changed is the HONESTY of the run:
- R6: Project 2 FAIL is now explicitly labelled Cat-D in the JSON, not
      buried in `log_tail`.
- R7: Project 1 runner final_audit now treats the 3 SoC-grade structural
      gates as WAIVED-DEFERRED (thin-input ticket=thin-input-v1.6.97)
      instead of FAILing them — atomic-input projects can no longer be
      falsely red-flagged on richness assumptions.

## Per-problem § 4 triage (re-justified from THIS run)

### Project 1 — `fixed_priority_arbiter` — Cat A FLOOR (re-justified)

- Authoring: spec-literal synchronous reset per `docs/specification.md`
  line 54. Same canonical form as v0.1.56 (§ 4 Cat-E: leave spec-faithful).
- Runner gates: phase1 PASS 14/14, phase2 `yosys_synth` PASS (61 cells),
  `sdc_gen` PASS, `phase2_manifests` PASS.
- v0.1.57 R7 effect: 3 thin-input structural gates correctly WAIVED-
  DEFERRED in `reports/audit/flow_compliance_check.log` (vs v0.1.56 where
  they were hard-FAIL).
- Cocotb: `TESTS=1 PASS=0 FAIL=1 SKIP=0`.
- Evidence for Cat A (from this run's cocotb_score.json log_tail): hidden
  harness `reset_dut(active=False)` reads `grant` immediately after
  `RisingEdge(clk)` racing the synchronous NBA — unsatisfiable blind
  without violating the spec.
- `harness_error: null` (v0.1.57 R6 correctly DIDN'T mis-label a DUT-level
  FAIL as Cat-D).

### Project 2 — `priority_encoder_8x3` — Cat D FLOOR (re-justified)

- Authoring: 8-to-3 MSB-priority cascade. Same canonical form as v0.1.56.
- Runner gates: phase1 PASS 14/14, phase2 `yosys_synth` PASS (14 cells),
  `sdc_gen` PASS, manifests PASS.
- Cocotb: `TESTS=0 PASS=0 FAIL=0 SKIP=0`.
- v0.1.57 R6 effect: `harness_error: {kind: 'cocotb-tools-typeerror',
  signal: 'TypeError: int() argument must be a string'}` automatically
  emitted to cocotb_score.json. Stdout shows
  `← cocotb-tools-typeerror in cocotb runner (Cat-D candidate)`.
  No more spelunking required.
- Evidence for Cat D: iverilog build succeeded; cocotb-tools' `runner.test()`
  raised TypeError inside the harness library layer before any test could
  run. This is the iic-eda cocotb 2.0.1 substitution gap vs the gated
  `nvidia/cvdp-sim:v1.0.0` image (per § 3 substitution disclosure).
- Per the blind rule, we did NOT open `score/src/harness_library.py` to
  root-cause the missing input.

## NEW residual surfaced by v0.1.57 R7

When R7 unblocked the 3 thin-input structural gates, a fourth gate
`agent_report_sha256_attestation_check` surfaced as FAIL on both projects:
"1 attestation gap(s)". The runner expects provenance SHA256 records for
every emitted RTL file; the AI's spec-to-rtl authoring step doesn't write
them. This is a real plugin gap (not a DUT bug, not a benchmark defect)
and is flagged for v0.1.58 capture.

## Tool substitution (§ 3)

`iic-eda` container (hpretl/iic-osic-tools): iverilog 13 + cocotb 2.0.1
substitutes the gated `nvidia/cvdp-sim:v1.0.0`. Project 2's Cat-D
harness_error is direct evidence of the cocotb-version-stack mismatch.

## Reproduce

```bash
PLUGIN=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.57
DATASET=/home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark/example_dataset
RUN=benchmark_external/cvdp/run_v0157
STAGE=/home/reyerchu/AI_IC_design/_vibeic_cvdp_v0157

python3 $PLUGIN/programs/benchmark_dispatch.py cvdp \
    --setup --dataset $DATASET --run $RUN

for P in $(cat $RUN/problems.list); do
    TOP=...   # per-problem from prompt
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

| Run | Cocotb verdict | What was honest about it |
|---|---|---|
| run_fresh_v0125 | PASS 9/9 (direct-agent) | Wrong shape; manual async workaround |
| run_v0153_runner | PASS 1/1 (manual N=1) | Sync→async manual switch (over-fit) |
| run_v0156 | 0/2 (general extractor; honest) | First honest baseline; R6+R7 captured here |
| **run_v0157** | **0/2** (same as v0.1.56) | Same DUT, same verdict. Now Project 2 auto-classified Cat-D; Project 1 audit correctly PASS_WITH_WAIVERS structural; one residual `agent_report_sha256_attestation_check` for v0.1.58 |

## § 4.1 doctrine validation

Per "DON'T CARE ABOUT PREVIOUS RESULT", re-attempted blind on v0.1.57.
Both FLOORs survived re-justification from THIS run's fresh evidence:
- Project 1 Cat-A re-justified from this run's cocotb_score.json `log_tail`
  (sync NBA race line) + spec line 54.
- Project 2 Cat-D re-justified from this run's `harness_error` field
  (cocotb-tools-typeerror auto-detected).

Both labels are now also independently verifiable from the JSON without
human log_tail parsing — that's the v0.1.57 honesty improvement.

## Sequence / plan status (§ 6 item 7)

- CVDP example: 0/2 cocotb PASS, both FLOOR re-justified.
- CVDP full (1500+): Shape E blocked (NVIDIA + Turing gated).
- Other Shape-E benchmarks intentionally skipped per § 7.

## v0.1.57 doctrine compliance

- ✅ Scorer single-pass; no variant retry.
- ✅ Dispatcher uses general agentic_jsonl_to_shape_d.py (no bench-name).
- ✅ Cat-A re-justified from THIS run's evidence, not copy-pasted.
- ✅ Cat-D auto-classified by R6 (no log_tail spelunking).
- ✅ Runner audit thin-input waiver active (R7).
- ⚠ New residual: agent_report_sha256_attestation_check — captured for
  v0.1.58 enhancement loop.
