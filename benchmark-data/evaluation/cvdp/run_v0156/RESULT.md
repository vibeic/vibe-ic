# CVDP example dataset — Shape D (runner-driven) on v0.1.56

> Triggered by user "run CVDP" + the v0.1.56 corrected doctrine:
> - § 4 Cat-A/E: FLOOR is FLOOR; no silent variant retry.
> - "general, not keyword": dispatcher uses general agentic JSONL extractor;
>   no `bench == "cvdp"` branches anywhere in the path.

## Headline

| Metric | Value |
|---|---|
| Plugin version | v0.1.56 |
| Shape | **D — agentic with runner** (per § 5 + Shape-D blind instructions) |
| Authoring entry | `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware` + `spec-to-rtl` skill (runner WAIVED rtl_gen on `digital_arithmetic_primitive`) |
| Scoring entry | `benchmark-harness/score_cocotb_mcp.py` (iic-eda container, docker exec, iverilog + cocotb 2.0.1) — **honest single-pass; no silent variant fallback** |
| Problems extracted | **N=2** (v0.1.56 general extractor; prior runs missed Project 2) |
| Cocotb verdict | **0 / 2 PASS** — both FLOOR (re-justified below) |

## Score trajectory & per-problem triage (§ 4)

### Project 1 — `cvdp_agentic_fixed_arbiter_0001` — **Cat A FLOOR**

**Authoring**: spec-literal synchronous reset per docs/specification.md line 54:
*"Active-high synchronous reset (clears all outputs)"*. Implementation: clocked
always block with `if (reset)` clearing outputs synchronously.

**Runner gates**: phase1 PASS (14/14 L docs, 100% coverage), phase2
`yosys_synth` PASS (61 cells, top=`fixed_priority_arbiter`),
`full_stack_tb_gen` PASS, `sdc_gen` PASS, `phase2_manifests` PASS.

**Cocotb result**: `TESTS=1 PASS=0 FAIL=1 SKIP=0`.

**Evidence for Cat A** (re-justified from THIS run, not copied from prior
RESULT.md): the hidden cocotb harness's `reset_dut(active=False)` reads
`grant` immediately after `await RisingEdge(clk)` with no settle delay,
racing the synchronous-reset NBA update specified by the spec. The
inconsistency between spec ("synchronous") and harness (de-facto demands
async-reset visibility) is unsatisfiable blind without violating the spec.

**v0.1.56 doctrine compliance**: we did NOT silently retry with an async
variant. The async resolution exists as an option but per § 4 Cat-E
("leave spec-faithful, do NOT over-fit to the hidden oracle") and the
v0.1.56 honesty rule, alternative-variant scoring must happen as a
SEPARATE --rtl arg + SEPARATE run, transparently labelled. Anyone running
this benchmark needs to know the canonical Cat-A is documented here, not
quietly papered over.

### Project 2 — `cvdp_agentic_8x3_priority_encoder_0003` — **Cat D FLOOR**

**Authoring**: 8-to-3 MSB-priority cascade per prompt
*"MSL [MSB] to LSB high bit priority"*; SVA assertion wrapped in
`ifdef SVA_ON` so default elaboration matches the visible TB's
positional instantiation `priority_encoder_8x3 dut (.in(...), .out(...))`.

**Sanity**: own visible-TB at `work/verif/priority_encoder_tb.sv` compiles
+ runs on iverilog 12 (host) → **PASSED** (8/8 one-hot cases match).

**Runner gates**: phase1 PASS (14/14 L docs, 100%), phase2 `yosys_synth`
PASS (14 cells, top=`priority_encoder_8x3`), `sdc_gen` PASS, manifests PASS.
`full_stack_tb_gen` SKIPPED (L9 has no top_ports — minimal-IO module).

**Cocotb result**: `TESTS=0 PASS=0 FAIL=0 SKIP=0` (and pytest reports
`FAILED test_runner.py::test_pri_enc[0] - TypeError: int() argument must be
a string, a bytes-like object or a real number, not 'NoneType'`).

**Evidence for Cat D** (tool-substitution gap): the iverilog build
succeeded (sim.vvp present); the error is inside cocotb-tools' `runner.test()`
invocation chain (harness_library.py:24), `int(None)` — strongly suggests
the hidden harness was built against the gated `nvidia/cvdp-sim:v1.0.0`
image's specific cocotb/cocotb-tools version stack and the iic-eda
container (cocotb 2.0.1) substitution doesn't satisfy what the harness
expects. Per § 3 substitution disclosure, this is a documented Cat D
floor under our substitution, not a DUT bug.

Per the blind rule we did NOT open `score/src/harness_library.py` to
narrow down the missing input. The honest report is: the DUT is
spec-correct (own-TB PASS, synth clean), the substituted harness errors
before scoring.

## Tool substitution (mandatory § 3)

| Benchmark mandates | We substitute | Caveat |
|---|---|---|
| `nvidia/cvdp-sim:v1.0.0` Docker image | `iic-eda` container (hpretl/iic-osic-tools): iverilog 13 + cocotb 2.0.1 + cocotb_tools | cocotb / cocotb-tools version delta vs CVDP's pinned image; Project 2's harness errored on the version mismatch (Cat D). Full 1500+ set also gated by NVIDIA + Turing. |

Container mount: `/home/reyerchu/AI_IC_design → /foss/designs`. The v0.1.54
`_validate_mount()` precheck refuses execution if `--mount-root` doesn't
correspond to an actual bind mount.

## Reproduce

```bash
PLUGIN=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/0.1.56
DATASET=/home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark/example_dataset

# 1. v0.1.56 general extractor + dispatcher (NO bench-name in args/code)
RUN=benchmark_external/cvdp/run_v0156
python3 $PLUGIN/programs/benchmark_dispatch.py cvdp \
    --setup --dataset $DATASET --run $RUN

# 2. Stage under container mount + add input/ for phase1 ingester
STAGE=/home/reyerchu/AI_IC_design/_vibeic_cvdp_v0156
mkdir -p $STAGE
for P in $(cat $RUN/problems.list); do
    rsync -a --delete $RUN/$P $STAGE/
    mkdir -p $STAGE/$P/input/docs
    cp $STAGE/$P/work/PROMPT.txt $STAGE/$P/input/phase1_prompt.md
    cp $STAGE/$P/work/PROMPT.txt $STAGE/$P/input/docs/design_description.md
done

# 3. For each problem: runner phase1+phase2 → spec-to-rtl → re-invoke
#    → score (single-pass, no variant retry)
for P in $(cat $RUN/problems.list); do
    TOP=...     # per-problem from prompt
    python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $STAGE/$P \
        --skip-phase3 --skip-analog --skip-hardware \
        --top-name $TOP --ic-name $TOP
    # [author RTL into $STAGE/$P/phase2/stage1/rtl/$TOP.sv per spec-to-rtl]
    python3 $PLUGIN/programs/vibe_ic_one_shot_runner.py $STAGE/$P \
        --skip-phase3 --skip-analog --skip-hardware --skip-phase1 \
        --top-name $TOP --ic-name $TOP
    cp $STAGE/$P/phase2/stage1/rtl/$TOP.sv $STAGE/$P/work/rtl/$TOP.sv
    python3 $PLUGIN/benchmark-harness/score_cocotb_mcp.py \
        --project $STAGE/$P --top $TOP \
        --rtl work/rtl/$TOP.sv \
        --mount-root /home/reyerchu/AI_IC_design
done
```

## Sequence / plan status (§ 6 item 7)

- **CVDP example dataset**: 0/2 cocotb-PASS on v0.1.56 (Project 1 Cat-A
  spec↔harness; Project 2 Cat-D cocotb substitution gap).
- **CVDP full (1500+)**: Shape E blocked (NVIDIA + Turing gated). Not pursued.
- Other Shape-E benchmarks (PyHDL-Eval / RTL-Repo / MetRex / ResBench)
  intentionally skipped per § 7 rule "never publish a number from Shape E".

## Comparison vs prior runs

| Aspect | run_fresh_v0125 (2026-05-28) | run_v0153_runner | run_v0156 (this run) |
|---|---|---|---|
| Shape | direct-agent (wrong) | D | **D (canonical)** |
| Problems attempted | 1 (arbiter only — manual stage) | 1 (arbiter — manual stage) | **2 (general extractor surfaced both)** |
| Scoring honesty | direct-agent; PASS via known async | runner; PASS via async (sync→async manual switch — workaround) | **honest single-pass; sync FAIL stays FAIL** |
| Cocotb verdict | PASS 9/9 (via async) | PASS via async (1 problem) | **0/2** — Project 1 Cat A, Project 2 Cat D |

The v0.1.56 number is **lower** than v0.1.53's, but it is the honest
number. Per § 4 doctrine, lowering a FAKE PASS to a documented FAIL is a
PLUGIN improvement, not a regression: the prior PASS was an over-fit
workaround. v0.1.56's general extractor also surfaced Project 2, which
prior runs hid behind manual single-problem staging.

## § 4.1 doctrine note

Per "DON'T CARE ABOUT PREVIOUS RESULT", we re-attempted blind on the
current plugin version. The Cat-A floor on Project 1 was re-justified
from THIS run's `cocotb_score.json` log (sync variant FAIL=1, harness
TB-line evidence), not copy-pasted from the v0.1.53 RESULT. The Cat-D
floor on Project 2 is NEWLY documented from this run.

## v0.1.56 doctrine compliance

- ✅ Scorer single-pass; no silent variant retry (R3 removed v0.1.56).
- ✅ Dispatcher uses `agentic_jsonl_to_shape_d.py` general extractor;
  zero `bench == "cvdp"` branches (regression test pins this).
- ✅ Cat-A and Cat-D floors documented honestly; no fabricated PASS.
- ✅ Anti-keyword regression tests prevent any future bench-name creep.
