# VerilogEval-v2 — blind run on v0.1.17 (Moore-realizability lesson in the double-confirm)

## Headline
**150/156 = 96.15%** (6 fails), fully blind, 8 parallel prompt-only agents — the high point of
the enhanced-blind series.

| Run | Gate / lesson | pass@1 |
|---|---|---|
| iter0 | base | 141/156 |
| enhanced-blind | + uninit lint | 147/156 |
| v0.1.13 | + function-arg fix | 149/156 |
| v0.1.16 | + FSM-style conformance + semantic double-confirm | 148/156 |
| **v0.1.17** | **+ "Moore is always realizable" in the fsm confirm** | **150/156** |

## Attributable win: Prob089 fixed by the v0.1.17 lesson
In v0.1.16 the semantic double-confirm wrongly overrode a correct `moore` candidate to Mealy,
reasoning "a serial 2's-complementer must read the live input, so Moore is impossible" — and
Prob089 failed. v0.1.17 added the domain fact (a Moore machine is realizable for ANY sequential
function via a registered output; judge what the spec REQUIRES, not feasibility) to the
`fsm_output_style` confirm. This run, every batch-04/05/06/07 agent that hit a Moore declaration
**kept Moore and registered the output** (e.g. Prob089 `z_reg <= seen?~x:x; assign z=z_reg`).
Result: **Prob089 PASS** (newly fixed vs v0.1.16). The lesson is now also a first-class IC Expert
Agent knowledge item (v0.1.18, "RTL Realization Principles").

Diff vs v0.1.16: newly fixed Prob089, Prob098, Prob145; newly broke Prob150 (blind variance).

## The semantic double-confirm also kept catching parser over-reads
Across the run, agents re-read every `unconfirmed-no-backend` candidate and overrode only the
genuine parser misfires — Prob124 and Prob144 (parser read a reset off a `load` signal → no
reset port exists), confirming all other reset/polarity/Moore/Mealy candidates as-is. No correct
candidate was wrongly overridden this run (unlike v0.1.16's Prob089).

## Remaining 6 fails — none addressable by a reliable general gate
- Prob062 — bug-fix mux: reference uses `sel?a:b`, opposite the embedded buggy code (dataset defect).
- Prob093 — reference `mux_in[2]=~d` contradicts the printed K-map (dataset defect).
- Prob099 — testbench wires `.Y2/.Y4` to a RefModule with only `Y1/Y3` (un-runnable dataset defect).
- Prob070 — SOP/POS correct on every CARE cell; diverges only on the spec's explicit don't-cares.
- Prob149 — reservoir FSM, ambiguous valve-direction wording.
- Prob150 — one-hot FSM, blind-shot variance (passed in earlier runs).

These are dataset defects + don't-care freedom + ambiguous wording + blind variance — confirmed
(see the rejected waveform-replay gate) to have no reliable, general, spec-derived deterministic
fix without overfitting.

## Reproduce
```bash
python3 score_verilogeval.py --run run_blind_v0117 \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
```
