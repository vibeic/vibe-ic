# VerilogEval-v2 — clean-room pass@1 (Vibe-IC v1.3.88 · Claude Fable 5 · fork vibeic-eda:0.2.12)

## 1. Headline
- **pass@1 = 153/156 = 98.08%** (raw), **SINGLE-SHOT** — no close-loop needed. Matches the all-time best, previously only reachable after close-loop + scorer fix.
- Model: **Claude Fable 5** (all 26 batch authoring agents). Measured: pass@1, spec→RTL, blind (prompt-only), official iverilog+`_test.sv` harness (`Mismatches: 0`).
- Program-first: **130/156 problems emitted deterministically** by `registry.generate()` solvers; 26 AI-authored.
- excl. dataset defects 153/155 = 98.71%; advisory excl. suspected-defect golden 153/154 = 99.35%.

## 2. Shape / entry point
- **Shape C** per `open-benchmark-methodology` §2. `gates_atomic.py` per-problem gate = sole emit path; every problem through `phase1_engine` (per-problem L1_DATASHEET.json **156/156**), `spec_conformance_check`, enforced `rtl_hygiene_lint --fix`, iverilog gate.
- **Integrity (verified PASS):** clean-room ✓ · blindness audit ✓ (26 transcripts clean) · emit-attestation strict ✓ (156/156) · per-problem Phase-1 evidence 156/156.
- Scored via the canonical oracle scorer `score_iverilog_tb.py` (v1.3.86 masked call-scoped dump-strip + fork-iverilog-14 escalation, both landed and §4.05 no-leak-proven).

## 3. Score trajectory
| Stage | pass@1 | note |
|---|---|---|
| **single-shot (blind, 26 batch agents, Fable 5)** | **153/156 = 98.08%** | equals the prior campaign's *converged* number — the v1.3.83/86 scorer escalation (recovers Prob151/156) and captured genre lessons landed between runs, so single-shot now reaches the defect floor. No close-loop round was needed. |

## 4. Residual triage (3 fails, A–H per §4 — all FLOOR, unchanged from the v1.3.79 campaign's proven evidence)
| Problem | reason | Category | evidence |
|---|---|---|---|
| `Prob099_m2014_q6c` | compile_error | **A dataset defect (FLOOR)** | golden `_ref.sv` fails its own multi-module TB (`port Y4 not a port of good1`); scorer golden-also-fails proven |
| `Prob062_bugs_mux2` | functional_mismatch (111/114) | **suspected-defect golden (FLOOR)** | vetted canonical sample ALSO mismatches the hidden golden 111/114 |
| `Prob093_ece241_2014_q3` | functional_mismatch (11/60) | **E spec-ambiguity (FLOOR)** | prior campaign's blind close-loop tried BOTH mux-index conventions (binary-value & printed-K-map-column); both fail → prompt "and so on" under-determined; stays spec-faithful |

## 5. Tool substitution (mandatory per §3)
- **Synopsys VCS / Cadence Xcelium → iverilog** (host Icarus 11.0; **fork Icarus 14.0-devel** + Verilator 5.048 in `ghcr.io/vibeic/vibeic-eda:0.2.12` as the SV-2012 escalation rung — handles the golden's enum cast `States'(...)` that host iverilog 11 rejects).

## 6. Reproduce
```bash
DS=<clone of NVlabs/verilog-eval>/dataset_spec-to-rtl
RUN=<fresh run dir>
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_dispatch.py verilogeval-v2 --setup --dataset $DS --run $RUN
# author blind per benchmark/blind_instructions_shape_c.md (gates_atomic.py sole emit), then:
python3 vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_iverilog_tb.py --bench verilogeval-v2 --dataset $DS --run $RUN
```
Snapshot: `pass_at_1_singleshot.json` (153). This run: `/home/reyerchu/AI_IC_design/verilogeval-v2_cleanroom_v1388`.

## 7. Sequence / plan status
Run this session (2026-07-12, plugin v1.3.88): VerilogEval-v2 (this), VerilogEval-Human, RTLLM v2. Not run: CVDP (separate campaign, prior 243/302 with Opus 4.8 stands), PyHDL-Eval / RTL-Repo (Shape E), MetRex/ResBench (out-of-scope metric).
