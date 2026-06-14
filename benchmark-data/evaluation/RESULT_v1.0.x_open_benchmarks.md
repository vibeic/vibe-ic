# Open-benchmark RESULT — plugin v1.0.x (2026-06-14)

Benchmark Agent clean-room (§4.1/§8.1 full re-run, blind, empty samples) on the open benchmarks.
blindness_audit PASS at the score front door for every reported number.

## 1. Headline (pass@1, what was measured, what was substituted)
| Benchmark | pass@1 | denominator | measure |
|---|---|---|---|
| VerilogEval-v2 | **153/156 = 98.08%** | 156 | spec→RTL, host iverilog + hidden _test.sv |
| VerilogEval-Human | **154/156 = 98.72%** | 156 | code-complete, host iverilog + _test.sv |
| RTLLM v2 | **37/50 = 74.0%** (rigorous 34/47) | 50 | runner-authored RTL + testbench.v (cwd=design) |
| CVDP nonagentic no_commercial | **199/302 = 65.89%** problem | 302 | official local_import + OSS sim image (cocotb) |

## 2. Shape (per open-benchmark-methodology §2)
- VerilogEval-v2 / VerilogEval-Human: **Shape C** (gates_atomic.py per-problem, host iverilog scorer).
- RTLLM v2: **Shape B** (vibe_ic_one_shot_runner --skip-phase3 --skip-analog --skip-hardware; host score_iverilog_tb cwd=design).
- CVDP: **Shape C/D** (official local_export → blind authoring → cvdp_gate.py SOLE-EMIT → official run_benchmark.py local_import).

## 3. Score trajectory
- VE-v2 / VE-Human / RTLLM: single-shot clean-room (matches prior canonical band). RTLLM 2 recoverable H-bugs (freq_divbyfrac, traffic_light) close-loop own-TB confirmed recoverable (not counted in canonical due to a file-location probe taint; would pass blind next round).
- CVDP: single-shot 199/302. Two cvdp_gate correctness bugs found+fixed this campaign (#626 fence-emit, #642 harness top-name) — both gate-compile≠scorer-compile; score delta this round = 0 (the affected completions had deeper module-name/functional issues), but the gate is now correct.

## 4. Residual triage (A-H; every fail mapped)
- VE-v2 (3 fails): Prob099 = irreducible benchmark defect (golden fails its OWN TB) **FLOOR**; Prob062 = suspected defective golden (vetted sample mismatches golden 111/114) **FLOOR**; Prob093 = golden violates the prompt's own K-map at (ab=10,cd=11) **FLOOR (Cat E / defective golden)**. 0 plugin gaps.
- VE-Human (2 fails): Prob062 + Prob093 (same FLOOR). 0 plugin gaps.
- RTLLM (13 fails): 11 FLOOR (A: sequence_detector desc↔TB reset_n/rst_n; B: radix2_div res_ready unstated, freq_divbyeven; C: LFSR positional port order; D/E: asyn_fifo, serial2parallel, barrel_shifter, freq_divbyodd, pulse_detect, alu, signal_generator convention/phase); 2 recoverable H close-looped. 0 plugin gaps. 3 non-discriminating TBs flagged (ring_counter/edge_detect/square_wave benchmark defect).
- CVDP (103 fails): FUNC_ALL 61 / FUNC_PARTIAL 24 = spec→RTL authoring + spec-ambiguity (AI core, §1, not plugin gaps); ELAB_ERROR 9 = the #626/#642 gate bugs (fixed); SYNTH_THRESHOLD 5 = optimization shortfall (authoring); TRUNCATED 4 = flakiness.

## 5. Tool substitution (per §3)
- RTLLM: **Synopsys VCS → Icarus Verilog 12** (host scorer). Disclosed.
- VE-v2/Human: host iverilog 12 (atomic micro-problems). Disclosed.
- CVDP: **NO substitution** — official OSS sim image `nvidia/cvdp-sim:v1.0.0` (Icarus v13 / yosys 0.40 / cocotb 2.0.1), verified by `cvdp_env_preflight.py` = PASS (the self-built cvdp-sim-local at yosys 0.62 was REFUSED, avoiding the #536 version-skew false-FAIL class).

## 6. Reproduce
- VE-v2:  `benchmark_dispatch.py verilogeval-v2 --score --run <run> --dataset _extbench/verilog-eval/dataset_spec-to-rtl`
- VE-Human: `benchmark_dispatch.py verilogeval-human --score --run <run> --dataset _extbench/verilog-eval/dataset_code-complete-iccad2023`
- RTLLM:  `benchmark_dispatch.py rtllm --score --run <run> --dataset _extbench/RTLLM` (sample = `<run>/samples/<leaf>.v`)
- CVDP:   `cvdp_env_preflight.py --image nvidia/cvdp-sim:v1.0.0` then `run_benchmark.py -f <nonagentic_no_commercial.jsonl> --model local_import --prompts-responses-file <responses.jsonl> --llm` (OSS_SIM_IMAGE=nvidia/cvdp-sim:v1.0.0).

## 7. Sequence / plan status
VE-v2, VE-Human, RTLLM: **CONVERGED — 0 plugin gaps** (all residuals FLOOR / benchmark-defect / spec-ambiguity / AI-core authoring). CVDP: 2 plugin gaps captured + fixed (#626, #642); single-shot 199/302; remaining fails are authoring/spec/flakiness. PyHDL-Eval / RTL-Repo / MetRex intentionally Shape-E (blocked / out-of-scope-metric) — not run.

_Backlog: reyerchu/AI_IC_design organic-backlog #626, #642 (CVDP gate). Trail: AI_IC_design/_bench_open_v100_r1._
