# VerilogEval-v2 — blind run with the cumulative general-enhanced gate (v0.1.13 → reverted to v0.1.14)

## Headline
**149/156 = 95.51%** (7 fails), fully blind, 8 parallel prompt-only agents.

Trajectory across the enhance loop:
| Run | Gate adds | pass@1 |
|---|---|---|
| iter0 | base | 141/156 = 90.38% |
| enhanced-blind (uninit only) | + rtl_hygiene rule 5 | 147/156 = 94.23% |
| this run | + function/task-arg fix (and a Moore check that NEVER fired) | 149/156 = 95.51% |

## Honest attribution
- **Durable, general plugin gains:** `uninit-registered-output` (rule 5) deterministically
  fixes the reset-less power-up-X class (Prob034/053/104, the same +3 every run); the
  function/task-arg parser fix removes a false `port-extra` block (correctness, no score cost).
- **Everything else is blind single-shot variance.** This run's 7 fails are Prob062 (mux-polarity
  dataset defect), Prob092/Prob093 (defective/don't-care), Prob099 (un-runnable dataset defect),
  and Prob091/Prob150/Prob155 (fresh blind misses this run). Prior runs missed a different subset;
  the spread is noise.
- The Moore "discipline" check that was briefly in the v0.1.13 gate **never fired** (agents wrote
  state-pure outputs unprompted) and was **reverted in v0.1.14 as non-generalizable** — it keyed on
  the literal word "Moore" and Mealy-vs-Moore is a valid design choice, so it is not a legitimate
  general gate. Prob089 passing this run is the model's blind shot, not a plugin gate.

## Loop convergence
The general, chip-agnostic deterministic gaps that VerilogEval surfaced are now exhausted:
shipped `uninit-registered-output` (v0.1.11) and the function/task-arg port-parse fix (v0.1.12);
rejected the Moore check (v0.1.13→v0.1.14) for failing the generality bar. The remaining misses
are dataset defects and blind functional variance — neither is addressable by a *general*
deterministic gate without overfitting to specific problems. Further iteration would only chase
variance or add specific (forbidden) checks, so the general-enhancement loop has converged.

## Reproduce
```bash
python3 score_verilogeval.py --run run_blind_v0113 \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
```
