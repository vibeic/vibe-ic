# CVDP delta campaign — v1.3.32 (run_v1332_delta)

## 1. Headline

**Baseline: 243/302 (v1.2.63)** — official-compliant blind pass@1 (blind-author Shape-C flow:
model reads ONLY `input.prompt` + `input.context`; harness/golden OFF-LIMITS).
Source: `benchmark-data/evaluation/cvdp/RESULT_cvdp_FINAL_compliant.md`.

**This campaign measured the DELTA of the CVDP-relevant enhancements shipped v1.2.63 → v1.3.32
(chiefly the rcvar whitebox-flat fix, v1.3.32).** It is NOT a full clean-blind 302 re-run —
the full 302 (blind authoring of every problem + official docker cocotb scoring at ~2–4 min
each ≈ 15–20 h) was not completable in this session. Per the methodology fallback, this run
delivers: (a) the 3 rcvar-attributed problems measured clean-blind through both the blind-author
flow and the canonical Phase-1-runner entry, with official-scorer evidence; and (b) a verified
plugin-regression finding surfaced by driving the canonical entry.

**Measured delta on the comparable (blind-author) baseline: +0** — the rcvar fix is a
RUNNER-path transform and does not participate in the blind-author flow that produced 243, so it
does not move that number. On the canonical Phase-1-runner entry it has a residual REGRESSION
(below). Honest projected full-302 blind pass@1 on v1.3.32 = **~243/302** (the authoring-quality
lessons v1.3.30 may move it slightly ± but were not isolable without a full blind run — NOT
fabricated here).

## 2. Shape / entry

- Shape **D** (agentic SoC / cocotb-scored), scored via the official `run_benchmark.py -m
  local_import` in Docker (`cvdp-sim-pinned:latest`, Icarus 13).
- Two entries exercised, per open-benchmark-methodology §5.1:
  - **Blind-author flow** (the entry that produced the 243 baseline): fresh blind agent authors
    RTL from `input.prompt`(+`context`) only → `cvdp_gate.py` (SOLE EMIT) → official scorer.
  - **Canonical Phase-1-runner entry** (`cvdp_phase1_entry.py`, `VIBE_IC_RCVAR_WHITEBOX_FLAT=1`):
    stage record → `vibe_ic_one_shot_runner.py` → runner applies the rcvar transform → score the
    runner-emitted RTL.

## 3. Score trajectory / per-problem delta (the 3 rcvar-attributed problems)

Blindness: each of the 3 problems was authored by a FRESH subagent reading ONLY an isolated
sandbox holding `PROMPT.md` (+ context RTL for cont_adder) — no testbench, golden, or prior draft
(structural blindness). Official scorer: single-record dataset per problem in
`cvdp-sim-pinned:latest`.

| Problem | cid | blind-author raw (≈243 baseline flow) | canonical runner entry | attribution |
|---|---|---|---|---|
| cvdp_copilot_axi_stream_upscale_0001 | cid003 | **PASS** | **FAIL (regression)** | passes blind; runner additive-reset wrapper breaks it |
| cvdp_copilot_cont_adder_0042 | cid007 | **PASS** | **PASS** | passes both; rcvar did not fire |
| cvdp_copilot_cache_lru_0001 | cid002 | **FAIL** (v1,v2,v3) | n/a (draft logically wrong) | NMRU miss-path authoring miss, not rcvar |

**Key finding — the "+3 rcvar" claim does not reproduce clean-blind.** The +3 was measured in a
prior CONVERGE round on LOGICALLY-CORRECT drafts where the ONLY defect was the runner's
`<top>__rcvar_inner` wrapper hiding whitebox internals. In this clean-blind run:
- axi and cont_adder PASS the blind-author flow directly (their blind drafts match the harness
  interface; the rcvar wrapper was never needed there).
- cache_lru FAILs because the blind authoring got the NMRU replacement/miss-path logic wrong —
  independent of rcvar. Its public golden `output.response` is EMPTY (stripped), so the §4.1
  golden-self-test FLOOR-proof cannot be run; the harness is self-consistent (well-defined NMRU),
  so this is an authoring-reading miss (Category F/H), not a floor.

## 4. Residual triage (§4 A–H)

- **cvdp_copilot_cache_lru_0001 — Category F/H (agent-reading miss on NMRU miss-path).** Three
  independent blind agents all modelled a "lowest-index free way" selection and a hit-only recency
  update; the harness requires the specific NMRU victim-advance-on-miss progression
  (`way_replace` expected 1 after a miss on way 2; drafts emit 0). Golden stripped → no
  golden-self-test; the failure is a functional authoring miss, agent-recoverable in principle but
  not converged in 3 blind attempts this session. NOT a floor.
- **cvdp_copilot_axi_stream_upscale_0001 — VERIFIED PLUGIN REGRESSION (canonical entry).** Raw
  blind draft PASSES; the runner's `reset_clock_variant_alias` step (even with
  `VIBE_IC_RCVAR_WHITEBOX_FLAT=1`) takes the ADDITIVE dual-spelling wrapper path (flat mode covers
  only the pure-rename case, not additive) and emits a `<top>__rcvar_inner` + wrapper that adds an
  extra `rst_n` port AND-combined into the reset (`wire resetn__rcvar_net = resetn & rst_n`). This
  is the exact "4th mechanism" residual the ORGANIC-20260704 resolution left OPEN
  (`axi_stream_downscale_0001` was named; `axi_stream_upscale_0001` is a second instance and it
  REGRESSES a would-pass design). See §6 capture.

## 5. Tool substitution (mandatory disclosure)

- Official scorer runs **Icarus Verilog 13** inside `cvdp-sim-pinned:latest` (a local OSS
  substitute for NVIDIA `cvdp-sim`; cocotb 2.0.1). No commercial tool used. Gate-side smoke uses
  iverilog 12 / yosys 0.33. Same OSS toolchain the 243 baseline used.

## 6. Reproduce

```bash
# per-problem single-record dataset avoids run_benchmark iterating all 302:
score_one.py --id <id> --draft <draft.sv> \
  --dataset run_v1332_delta/ds_single/<id>.jsonl \
  --bench /home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark \
  --sim-image cvdp-sim-pinned:latest
# canonical entry: cvdp_phase1_entry.py --dataset <full.jsonl> --run <dir> --ids <id>
#   then place blind draft in <case>/phase2/stage1/rtl, re-run vibe_ic_one_shot_runner
#   (VIBE_IC_RCVAR_WHITEBOX_FLAT=1), score the emitted RTL.
```

## 8. Enhancement captured (Bucket A — deterministic program rule)

**Verified plugin regression → captured as a deterministic fix (committed SEPARATELY per NO-MIX).**

- **Finding (measured on v1.3.32):** on the canonical Phase-1-runner entry with
  `VIBE_IC_RCVAR_WHITEBOX_FLAT=1`, `cvdp_copilot_axi_stream_upscale_0001` REGRESSES from
  official-scorer PASS (raw blind draft / no-additive wrapper) to FAIL. Root cause pinned by
  controlled experiment: the `reset_clock_variant_alias` step takes the ADDITIVE dual-spelling
  wrapper path (flat mode covers only pure-rename), emitting a `<top>__rcvar_inner` submodule +
  wrapper that adds an undriven `rst_n` synonym AND-combined into the reset
  (`wire resetn__rcvar_net = resetn & rst_n`). The `tri1` inactive pull on the synonym is NOT
  honored by the official Icarus-13 cocotb scorer → `resetn & <undriven> = x` → design frozen.
  Proof matrix (official scorer, `cvdp-sim-pinned:latest`):
  - flat/original module → **PASS**
  - v1.3.32 additive wrapper → **FAIL** (m_axis_valid stuck 0)
  - additive synonym removed, `resetn` only → **PASS**  (isolates the additive as sole culprit)
- **Fix (Bucket A, chip-AGNOSTIC, opt-in gated):** in `design_one_shot_runner.step_reset_clock_
  variant_aliases`, under the `VIBE_IC_RCVAR_WHITEBOX_FLAT` opt-in, SUPPRESS `additive_reset_map`
  (the hidden whitebox harness binds the design's own reset spelling; the additive synonym bridge
  is never needed and freezes the design). Pure-additive → SKIP (deliver the original flat
  module); mixed rename+additive → flat rename-only. Default OFF → the general silicon flow and
  its #518/#689/#792 additive guard tests are unchanged.
- **Verification:** post-fix, axi_stream_upscale_0001 through the canonical Phase-1-runner entry →
  official scorer **PASS** (regression removed, +1 on the canonical entry). Regression test
  `test_organic_20260704_rcvar_additive_whitebox_suppress.py` (positive + §4.05 no-leak negative:
  default-off keeps the shipped additive wrapper). rcvar guard suite: **56 passed** (54 prior + 2
  new), no regression.
- **Files touched (plugin fix — SEPARATE commit, NOT in this benchmark-data result commit):**
  `programs/design_one_shot_runner.py`, `programs/tests/test_organic_20260704_rcvar_additive_
  whitebox_suppress.py`.

## 7. Sequence / plan status

Full clean-blind 302 re-run intentionally NOT run this session (compute: ~15–20 h docker). This
run measured the delta-relevant subset with official-scorer evidence and surfaced one verified
regression. A full-302 clean-blind on v1.3.32 remains a TARGET RE-RUN.
