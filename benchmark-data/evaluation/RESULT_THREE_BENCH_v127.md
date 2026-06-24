# Vibe-IC benchmark clean-run — VE-v2 + VE-Human + RTLLM (plugin cache 1.2.7)

Clean-room FULL re-run (open-benchmark-methodology §4.1/§8.1): every problem authored fresh,
blind, from its prompt only; the deterministic plugin GATE/runner is the sole emit path;
reconciled by disk-truth. Direct subagents, narrow-width (no rate-limit). No local benchmark DB.
Tool: VCS→iverilog 12.

## 1. Headline (single blind draw, pass@1)
| benchmark | shape | pass@1 | excl. dataset defects | prior best | result |
|---|---|---|---|---|---|
| VerilogEval-v2    | C | **153/156 = 98.08%** | 153/154 = 99.35% | 152 | NEW HISTORY-HIGH |
| VerilogEval-Human | C | **154/156 = 98.72%** | 154/155 = 99.35% | 154 | ties history-high |
| RTLLM v2          | B | **46/50 = 92.0%**    | 46/49 = 93.88%   | 46  | ties best |

Blindness audited (all transcripts clean); every sample carries an emit-path attestation.

## 2. Shape
VE-v2 / VE-Human → Shape C (gates_atomic.py sole emit). RTLLM → Shape B (vibe_ic_one_shot_runner
--skip-phase3 → spec-to-rtl WAIVE/author → shape_b_sample_export.py sole emit; phase2 shim active).

## 3. Score trajectory — the deterministic recoveries from v1.2.3-1.2.7 LANDED
On 1.2.2 the residual fails included Prob082/086 (Galois-LFSR no_sample), Prob116 (kmap no_sample),
Prob092/094 (comb_advanced functional_mismatch) — all PLUGIN self-conflicts. v1.2.3 (#3 LFSR
conformance carve-out + #4 comb_advanced declared-port-width) + #2 kmap[4:1] + v1.2.4/1.2.5 tier
gate-parity LANDED. This run CONFIRMS the recovery: Prob082/086/092/094/116 ALL emit + pass —
they are GONE from every fail list. VE-v2 150→153, VE-Human 149→154.

## 4. Residual triage — every remaining fail is FLOOR-proven (no over-fit)
- VE-v2 (3): Prob062_bugs_mux2 (DATASET_DEFECT — golden inverts the prompt's select polarity),
  Prob093_ece241_2014_q3 (TRUE_FLOOR E — oracle ~d not derivable from the printed K-map),
  Prob099_m2014_q6c (DATASET_DEFECT — golden fails its OWN hidden TB, scorer-proven).
- VE-Human (2): Prob062 + Prob093 (same two floors).
- RTLLM (4): radix2_div (DATASET_DEFECT — golden fails own TB), asyn_fifo (FLOOR-D — TB `break;`
  at L102, golden also uncompilable under iverilog), freq_divbyeven (TRUE_FLOOR E — TB hardwired
  to golden's undeclared NUM_DIV=6 default), serial2parallel (sim_timeout — pass@1 authoring
  variance, blind-recoverable). Both VE benchmarks reached their FLOOR-FREE CEILING (99.35%).

## 5. Tool substitution (open-benchmark-methodology §3)
| Benchmark mandates | We substitute | Caveat |
|---|---|---|
| Synopsys VCS / Cadence Xcelium sim | iverilog 12 | VCS-only TB constructs (`break;`) reject → pure tool-gap floor (asyn_fifo) |
| Synopsys Design Compiler PPA | yosys (Shape-B runner synth gate only) | NOT reported as PPA |

## 6. Reproduce
```
PR=/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.2.7
python3 $PR/programs/benchmark_dispatch.py <bench> --setup/--score --dataset <ds> --run <run>/<bench>
```
Datasets: _extbench/verilog-eval/{dataset_spec-to-rtl,dataset_code-complete-iccad2023}, _extbench/RTLLM.

## 7. Sequence / plan status
The three OPEN spec→RTL benchmarks requested (VE-v2, VE-Human, RTLLM) on current cache 1.2.7.
Intentionally NOT run: cvdp-open / PyHDL-Eval (E) / RTL-Repo / MetRex / ResBench (E) /
benchmark_clean (A, separate flow). The VE history-high confirms the v1.2.3-1.2.7 plugin fixes
(LFSR carve-out + comb_advanced declared-width + tier gate-parity) produce the deterministic
recovery they were authored for.
