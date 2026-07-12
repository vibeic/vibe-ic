# RTLLM v2.0 — clean-room pass@1 (Vibe-IC v1.3.88 · Claude Fable 5 · fork vibeic-eda:0.2.12)

## 1. Headline
- **pass@1 = 49/50 = 98.0%** (raw, converged after ONE blind close-loop round; single-shot 47/50 = 94.0%). **New best** (prior campaign: 42 single → 46 converged).
- **Excluding the 1 proven upstream dataset defect: 49/49 = 100%** — every solvable design passes.
- Model: **Claude Fable 5** (13 batch authoring agents + 2 close-loop agents). Measured: pass@1, spec→RTL standalone designs, blind, official `testbench.v` (`Your Design Passed`, cwd=design).
- Rigorous (discriminating TBs only): 47/48 = 97.92% (2 upstream TBs are non-discriminating — a constant-0 stub also passes — flagged, counted per the upstream marker metric).

## 2. Shape / entry point
- **Shape B** per `open-benchmark-methodology` §2: every design driven through the deterministic **`vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware`**; AI plays the spec-to-rtl role INSIDE the pipeline on `rtl_gen=null` WAIVE; `shape_b_sample_export.py` = sole emit path.
- **Integrity (verified PASS):** clean-room ✓ · blindness audit ✓ (15 transcripts incl. close-loop, clean) · emit-attestation strict ✓ (50/50) · per-design Phase-1 evidence 50/50.

## 3. Score trajectory
| Stage | pass@1 | Δ | note |
|---|---|---|---|
| single-shot (blind, 13 batch agents, Fable 5) | 47/50 = 94.0% | — | **beats the prior campaign's converged 46/50 at single shot** — the captured fixes landed in the plugin: v1.3.84 reset-alias wrapper fix auto-recovers `up_down_counter`/`sequence_detector`/`synchronizer`; v1.3.87 mount-aware yosys fallback + correct container mounts recover `radix2_div`/`freq_divbyeven` (previously mis-degraded by an unmounted container) |
| **close-loop round 1 (blind)** | **49/50 = 98.0%** | +2 | `float_multi` (held-result → clean constant-5-cycle pipeline; bit-exact vs 500-vector IEEE-754 self-check) + `freq_divbyfrac` (dual-edge-OR phase decode corrected per the captured 3.5× genre lesson) |

## 4. Residual triage (1 fail, A–H per §4)
| Design | reason | Category | evidence |
|---|---|---|---|
| `ring_counter` | compile_error | **A dataset defect (FLOOR)** | official `testbench.v` defect (`Cannot assign to array data` + unresolved `reset` wire); the golden `verified_*.v` ALSO fails its own TB — scorer golden-also-fails proven (§4.1 floor-proof) |

Flagged (PASS but disclosed): `edge_detect`, `square_wave` — non-discriminating upstream TBs (constant-0 stub also passes).

## 5. Tool substitution (mandatory per §3)
- **Synopsys VCS / Cadence Xcelium → iverilog** (host Icarus 11.0; **fork Icarus 14.0-devel** in `ghcr.io/vibeic/vibeic-eda:0.2.12` for VCS-only TB constructs — `break;`/`continue;` fork-closed per `tools/vibeic-eda/FIX_STATUS.md` Tool 5) + **yosys (vibeic fork) / OpenROAD** for the runner's synth gates. cwd=design honored for relative `$readmemh`.

## 6. Reproduce
```bash
DS=<clone of hkust-zhiyao/RTLLM>
RUN=<fresh run dir>
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_dispatch.py rtllm --setup --dataset $DS --run $RUN
# drive each design per benchmark/blind_instructions_shape_b.md (runner + shape_b_sample_export sole emit), then:
python3 vibe-ic-marketplace/plugins/vibe-ic/benchmark/score_iverilog_tb.py --bench rtllm --dataset $DS --run $RUN
```
Snapshots: `pass_at_1_singleshot.json` (47) / `pass_at_1_converged.json` (49). This run: `/home/reyerchu/AI_IC_design/rtllm_cleanroom_v1388`.

## 7. Sequence / plan status
Run this session (2026-07-12, plugin v1.3.88): VerilogEval-v2, VerilogEval-Human, RTLLM v2 (this). Not run: CVDP (prior 243/302 with Opus 4.8 stands), PyHDL-Eval / RTL-Repo (Shape E), MetRex/ResBench (out-of-scope).
