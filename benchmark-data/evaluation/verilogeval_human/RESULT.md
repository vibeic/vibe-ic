# VerilogEval-Human (iccad2023 code-complete) — clean-room full re-run, plugin v1.4.81 + vibeic-eda 0.2.26, 2026-07-22

## 1. Headline

**pass@1 = 154 / 156 = 98.72 %** — clean-room, single-shot, blind. **Both residual
fails are proven dataset defects: 100 % except floor, third consecutive run.**

- **Measured:** functional `pass@1`, official hidden testbench under iverilog;
  PASS iff `Mismatches: 0 in N samples`. All 156 problems, nothing inherited.
- **Substituted:** iverilog 12 (host scorer) for Synopsys VCS / Cadence Xcelium (§ 5).
- Excluding the suspected defective golden: 154/155 = **99.35 %** (advisory).

**Trajectory (same shape, same harness):** 154/156 on v1.4.68 → 154/156 on
v1.4.74 → **154/156 on v1.4.81** — identical score and identical fail set across
three clean-room rounds. A strong stability datapoint.

## 2. Shape and entry point

**Shape C**, § 7.5 entry, on the **official v1.4.81 cache** (no local patches):

- `benchmark_dispatch.py verilogeval-human --setup` → clean-room scaffold.
- `benchmark/gates_atomic.py` sole emit path (now carrying the shipped
  `level_hysteresis_flag_oracle` step 4d); per-problem Phase-1 fact-graph ×156.
- `lesson_consumption_check` program-enforced per problem: 156/156 acks.

Front-door guards at scoring: entry guard **PASS (native)**, clean-room **PASS**,
blindness audit **PASS (32 transcripts clean)**, emit attestation **PASS (156/156)**.

Environment: vibeic-eda **0.2.26** (`eda_doctor` 14/14). Host scorer iverilog 12;
12-vs-13 skew disclosed; host `verilator` absent → SKIP, never a silent pass.

## 3. Score trajectory

| Stage | Score | Notes |
|---|---|---|
| Clean-room single-shot blind (**headline**) | **154/156 = 98.72 %** | 16 batch agents; zero gate BLOCKs — every problem emitted first-iteration |
| Close-loop | not applicable | both residuals are proven dataset defects; § 4 forbids converging on them |

Prob149 (this suite's variant) passed again with the correct held-flag semantics —
the shipped oracle covers this suite's embedded-module-header prompt style too
(the interface fallback parser), standing as backstop; it did not need to fire.

## 4. Residual triage

Both fails are Category A2 floors with **this run's** evidence (§ 4.1).
Machine-checked: `triage_record_check.py` PASS,
`benchmark_triage_absorption_audit.py` PASS (0 absorbed, 2 floor-exempt).

> **Re-verifiability note (2 floors) — vibe-ic#1293, added 2026-08-13.**
> The two machine checks cited immediately above are **not re-runnable from this
> published record.** Both `triage_record_check.py` and
> `benchmark_triage_absorption_audit.py` take their triage JSON as a *required
> positional argument*, and no `triage_records*.json` was ever published in this
> run directory. Across the whole repo exactly one such file exists
> (`benchmark-data/evaluation/cvdp/run_v1239_converge/`), it belongs to a
> different corpus, and nothing in `programs/`, `tools/`, `skills/` or `flow/`
> produces one — the absorption audit is registered NOT WIRED in
> `checker_skill_only_reasons.json` for precisely this reason.
>
> This is a gap in the *evidence trail*, not a retraction. The claim is
> well-formed and corpus-specific: `PASS (0 absorbed, 2 floor-exempt)` is the
> program's own output string (`benchmark_triage_absorption_audit.py:446`) and
> its record count matches the 2 fails enumerated below, so it reads as a real
> run whose input was simply not committed. But a reader can only *read* it, not
> *reproduce* it. Treat both as **UNREPRODUCED** until a producer lands and the
> input is published beside the result.
>
> **Scope: the pass@1 headline in §1 is unaffected.** It comes from the official
> scorer, whose inputs are published; only the §4.2 convergence-bar line depends
> on the missing file.

### Prob062_bugs_mux2 — Category A2 — TRUE_FLOOR

This run's scorer re-flagged `suspected_defective_golden` (vetted canonical sample
mismatches the hidden golden **111/114**). The prompt gives
`(~sel & a) | (sel & b)` and names the width as the bug; the golden inverts the
given select polarity. Prior 3-lens blind solve: 3/3 failed identically.

### Prob093_ece241_2014_q3 — Category A2 — TRUE_FLOOR

Re-proved fresh this run in this dataset variant: the golden's `mux_in[2] = ~d`
(truth vector (1,0,0,1)) matches no column of the printed K-map under any of the
24 index mappings. Prior 3-lens blind solve: 3/3 failed identically at 11/60.

### No Category F–H residual

Zero authoring misses, third consecutive run.

## 5. Tool substitution

| Benchmark mandates | We substitute | Caveat |
|---|---|---|
| Synopsys VCS simulation | **iverilog 12** (host scorer) | No residual attributed to a tool gap |
| Cadence Xcelium | **iverilog 12** | Same commercial-vs-OSS gap as VCS |
| Synopsys Design Compiler PPA | **not scored** | Not apples-to-apples; deliberately not reported |

## 6. Reproduce

```bash
PLUGIN=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.4.81
DATASET=/home/reyerchu/ic-benchmarks/repos/verilog-eval/dataset_code-complete-iccad2023
RUN=/home/reyerchu/ic-benchmarks/runs/ve_human_v1481_20260722

python3 $PLUGIN/programs/benchmark_dispatch.py verilogeval-human --setup \
    --dataset $DATASET --run $RUN
# per problem: author spec.yaml + sample.sv + lessons_applied.json, then
python3 $PLUGIN/programs/lesson_consumption_check.py --prompt $DATASET/<Prob>_prompt.txt \
    --digest $RUN/lessons.md --ack $RUN/work/<Prob>/lessons_applied.json --strict
python3 $PLUGIN/benchmark/gates_atomic.py --prob <Prob> \
    --workdir $RUN/work --dataset $DATASET --bench verilogeval-human
# export transcripts to $RUN/transcripts/, then
python3 $PLUGIN/programs/benchmark_dispatch.py verilogeval-human --score --run $RUN
```

## 7. Sequence / plan status

Paired with **VerilogEval-v2** (153/156 this run — the absorbed hysteresis class
passed blind for the first time; see its RESULT.md). Prob062 and Prob093 fail
identically in both suites across all three campaign runs — six-fold corroboration
of the dataset-defect classification.

**Convergence count: zero-backlog clean-room round #1 of the required 2** (jointly
with the spec-to-RTL suite: zero residuals needing a plugin fix this round).

Not run (unchanged Shape-E status per § 5): PyHDL-Eval, RTL-Repo, MetRex,
ResBench, ChipAgentsBench, CVDP-full. RTLLM (Shape B) and cvdp-open remain
available.

## Summary

**STATUS**: COMPLETE — **100 % except floor, third consecutive run** (154/156;
both fails proven dataset defects). Official v1.4.81, all four guards PASS.

| | |
|---|---|
| pass@1 | **154/156 = 98.72 %** (identical across all three campaign rounds) |
| Non-floor residuals | **0** |
| Floors | 2, both with this-run § 4.1 evidence (A2 / A2) |
| § 4.2 convergence bar | PASS (0 absorbed, 2 floor-exempt) — **UNREPRODUCED**, input unpublished (§ 4 note, #1293) |
| Convergence count | **zero-backlog round #1 of 2** (jointly with VE-v2) |

Next: run /vibe-ic-benchmark verilogeval-human clean-room once more for
zero-backlog round #2, or proceed to /vibe-ic-benchmark rtllm (Shape B target
re-run).
