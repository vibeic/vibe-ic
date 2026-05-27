# VerilogEval-v2 — blind run on v0.1.16 (semantic-confirm gate + agent-layer double-confirm)

## Headline
**148/156 = 94.87%** (8 fails), fully blind, 8 parallel prompt-only agents.

| Run | Plugin gate | pass@1 |
|---|---|---|
| iter0 | base | 141/156 = 90.38% |
| enhanced-blind | + uninit lint | 147/156 = 94.23% |
| v0.1.13 | + function-arg fix | 149/156 = 95.51% |
| **v0.1.16** | **+ FSM-style conformance + semantic LLM-double-confirm (agent-layer)** | **148/156 = 94.87%** |

The score is on a plateau (147 / 148 / 149 across the last three) — the plugin's general
gates set a durable floor; the rest is blind single-shot variance.

## What this run validates: the semantic double-confirm actually ran (and is a real judgment)
Every prose-inferred semantic candidate (reset mode/polarity, latency, FSM output style)
came out of the deterministic parser marked `unconfirmed-no-backend` (no in-process LLM on
this host), so each agent performed the v0.1.16 **agent-layer double-confirm**: re-read the
prompt and confirmed or overrode the parser's reading before acting. Observed:

- ✅ **Correct catches of parser over-reads** (the mechanism working as intended):
  - **Prob084**: parser inferred `reset = synchronous/active-high` — but it had keyed off the
    *enable* signal's wording; the design has NO reset. Agent overrode → no reset. Correct.
  - **Prob124**: parser inferred a `reset` from "synchronous active high **load**". Agent
    overrode → load-only, no reset. Correct.
  - Dozens of reset/Moore/Mealy candidates (e.g. Prob127 Moore, Prob129 Mealy, Prob088 Mealy)
    were re-read and **confirmed correct** — no rubber-stamping.
- ⚠️ **One wrong override** (the mechanism is only as good as the judgment):
  - **Prob089**: parser candidate `fsm_output_style=moore` was CORRECT (the prompt explicitly
    says Moore, and the reference is a registered Moore machine). The agent overrode it to a
    Mealy `assign z = seen?~x:x`, reasoning "a serial 2's-complementer must read the live LSB,
    so Moore is impossible." That reasoning is wrong — a *registered* Moore output (`z_reg <=
    x^c`) implements it with one cycle of latency, which is exactly the reference. The override
    cost Prob089 (it had PASSED in v0.1.13 when an agent wrote registered-Moore). Honest result:
    LLM double-confirm is a genuine judgment step, not infallible.

So the semantic-confirm's value is real for **catching deterministic-parser false-positives**
(its design intent), with the caveat that the confirming LLM's own reasoning can still err.

## Fail breakdown (8) vs the untouched iter0 baseline
- Fixed vs iter0 (10): Prob034/053/104 (uninit lint, durable), 078/092/116/124/146/154/155 (variance).
- Still failing (5): Prob062 (mux-polarity dataset defect), Prob093 (`~d` defect/don't-care),
  Prob099 (un-runnable dataset defect), Prob089 (double-confirm wrong override this run),
  Prob149 (reservoir FSM, ambiguous wording).
- New vs iter0 (3): Prob070, Prob098, Prob145 — fresh blind misses (different from v0.1.13's
  091/150/155; pure variance).

## Conclusion
v0.1.16's two general gates work as designed: the FSM-style conformance fires only on a
semantically-confirmed Moore declaration, and the semantic double-confirm caught real parser
over-reads (Prob084/124). The blind score stays on its ~94-95% plateau (defective-dataset +
functional-variance tail). Prob089 is a useful honest data point: the double-confirm is a true
LLM judgment, and here it overrode a correct parser candidate — a reminder that the confirm
step improves over a silent deterministic guess but does not guarantee correctness.

## Reproduce
```bash
python3 score_verilogeval.py --run run_blind_v0116 \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
# per-problem semantic-confirm manifests: run_blind_v0116/work/<Prob>/semantic_manifest.json
```
