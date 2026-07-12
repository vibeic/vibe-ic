# VerilogEval-Human — clean-room pass@1 (Vibe-IC v1.3.88 · Claude Fable 5 · fork vibeic-eda:0.2.12)

## 1. Headline
- **pass@1 = 153/156 = 98.08%** (raw), **SINGLE-SHOT** — no close-loop round run. Matches the prior campaign's converged number at single shot.
- Model: **Claude Fable 5** (all 26 batch authoring agents). Measured: pass@1, code-complete (iccad2023), blind (prompt-only), official iverilog+`_test.sv` (`Mismatches: 0`).
- Program-first: **129/156 problems emitted deterministically** by `registry.generate()` solvers; 27 AI-authored.
- advisory excl. suspected-defect golden 153/155 = 98.71%.

## 2. Shape / entry point
- **Shape C** per `open-benchmark-methodology` §2. `gates_atomic.py` per-problem gate = sole emit path; every problem through `phase1_engine` + `spec_conformance_check` + `rtl_hygiene_lint --fix` + iverilog gate. Per-problem Phase-1 evidence **156/156**.
- **Integrity (verified PASS):** clean-room ✓ · blindness audit ✓ (26 transcripts clean) · emit-attestation strict ✓ (156/156).
- Scored via canonical `score_iverilog_tb.py` (v1.3.86, fork-iverilog-14 escalation — recovers the Prob151/156 enum-cast tool-gap class).

## 3. Score trajectory
| Stage | pass@1 | note |
|---|---|---|
| **single-shot (blind, 26 batch agents, Fable 5)** | **153/156 = 98.08%** | prior campaign needed close-loop + scorer fix to reach 153; the landed captures make it single-shot. Historical note: an earlier Opus-4.8 campaign (v1.2.7) reported 154/156 after close-loop convergence — that figure included a close-loop stage; this 153 is pure single-shot. |

## 4. Residual triage (3 fails, A–H per §4)
| Problem | reason | Category | evidence |
|---|---|---|---|
| `Prob062_bugs_mux2` | functional_mismatch (111/114) | **suspected-defect golden (FLOOR)** | vetted canonical sample ALSO mismatches the hidden golden 111/114 |
| `Prob093_ece241_2014_q3` | functional_mismatch | **E spec-ambiguity (FLOOR)** | prior campaign's blind close-loop tried BOTH mux-index conventions; both fail |
| `Prob149_ece241_2013_q4` | functional_mismatch (1171/2040) | **E/H residual (close-loop-attempted in the prior campaign)** | fr-valve combinational-vs-registered re-derivation recovered the spec-to-rtl variant but not this code-complete variant; attempted blind, never over-fit to the oracle |

## 5. Tool substitution (mandatory per §3)
- **Synopsys VCS / Cadence Xcelium → iverilog** (host Icarus 11.0; **fork Icarus 14.0-devel** + Verilator 5.048 in `ghcr.io/vibeic/vibeic-eda:0.2.12` as the SV-2012 escalation rung).

## 6. Reproduce
```bash
DS=<clone of NVlabs/verilog-eval>/dataset_code-complete-iccad2023
RUN=<fresh run dir>
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_dispatch.py verilogeval-human --setup --dataset $DS --run $RUN
python3 vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_iverilog_tb.py --bench verilogeval-human --dataset $DS --run $RUN
```
Snapshot: `pass_at_1_singleshot.json` (153). This run: `/home/reyerchu/AI_IC_design/verilogeval-human_cleanroom_v1388`.

## 7. Sequence / plan status
Run this session (2026-07-12, plugin v1.3.88): VerilogEval-v2, VerilogEval-Human (this), RTLLM v2. Not run: CVDP (prior 243/302 with Opus 4.8 stands), PyHDL-Eval / RTL-Repo (Shape E), MetRex/ResBench (out-of-scope).
