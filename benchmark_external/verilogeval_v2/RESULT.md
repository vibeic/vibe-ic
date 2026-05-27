# VerilogEval-v2 (spec-to-RTL) — Vibe-IC / Claude result

## Headline
**pass@1 = 146 / 156 = 93.59%** — blind single-shot generation, scored by the official
VerilogEval iverilog testbench. This sits at the published frontier (~90%) for the
spec-to-RTL task.

> **Note (v0.1.3 re-run).** This headline is scored over the **frozen** samples in
> `samples/`; re-running `score_verilogeval.py` is deterministic and always returns
> 146/156 — the plugin update lives in the flow's gate path, not in this blind-generation
> or scoring path. A genuinely **fresh blind re-run** on v0.1.3 (regenerated from scratch)
> scored **142/156 = 91.03%** — within blind single-shot variance — and its failures were
> then used to demonstrate that the v0.1.3 port-fidelity lint catches 5/14 of them. See
> [`run_rerun_v013/RESULT_rerun.md`](run_rerun_v013/RESULT_rerun.md).
>
> **Note (v0.1.4 re-run).** A second fresh blind re-run, regenerated from scratch on v0.1.4
> by 8 parallel prompt-only Claude agents, scored **145/156 = 92.95%** (145/155 = 93.55% on
> the scoreable set). Its single non-functional failure, **Prob099**, is a *defective dataset
> problem*: the testbench wires ports `Y2/Y4` that the golden `RefModule` does not have, so
> **even the official reference fails its own testbench** — and our blind output was byte-for-byte
> the reference. The v0.1.4 `spec_rtl_port_fidelity_check` flagged exactly that garbled-spec
> signature (and nothing else among the 11 fails). See
> [`run_rerun_v014/RESULT_rerun.md`](run_rerun_v014/RESULT_rerun.md).
>
> **Note (v0.1.5 re-run).** A third fresh blind re-run, regenerated from scratch on v0.1.5 by
> 8 parallel prompt-only Claude agents, scored **143/156 = 91.67%** (143/155 = 92.26% on the
> scoreable set) — ordinary blind single-shot variance (the 12 functional misses are the K-map
> don't-care / reset-timing tail). The defective **Prob099** was again the only non-functional
> failure, and the v0.1.5 `spec_self_consistency_check` (MCP `eda_spec_lint`) flagged it from the
> prompt ALONE, before any RTL — `body-port-gap` — and nothing else among the 13 fails. See
> [`run_rerun_v015/RESULT_rerun.md`](run_rerun_v015/RESULT_rerun.md).

## What was measured
- **Benchmark:** NVlabs `verilog-eval`, `dataset_spec-to-rtl` (the 2024 v2 spec-to-RTL task,
  156 Human-Eval problems). Dataset @ commit `c498220` (not vendored here — clone
  `https://github.com/NVlabs/verilog-eval` to reproduce).
- **Generator:** a Claude agent (the model behind Vibe-IC) — there is no ANTHROPIC_API_KEY /
  anthropic SDK on this host, so the official `sv-generate` API loop could not be used;
  instead a Claude agent authored one deterministic `module TopModule` per problem.
- **Setting:** pass@1, n=1, single deterministic shot per problem (the official "low
  temperature" setting). No pass@k inflation.
- **Scorer:** `score_verilogeval.py` — for each problem,
  `iverilog -g2012 -s tb -o bin <our_sample> <Prob>_test.sv <Prob>_ref.sv` (host iverilog 12.0,
  the version VerilogEval specifies) then `vvp`; PASS iff it compiles AND the official
  testbench prints `Mismatches: 0 in N samples`. Every one of the 156 problems is scored;
  a missing sample = FAIL. No cherry-picking.

## ⛔ Honesty discipline (this is the whole point)
- The 6 generation agents read **ONLY** each `<Prob>_prompt.txt`. They were forbidden to open
  `<Prob>_ref.sv` (reference solution) or `<Prob>_test.sv` (testbench), and each confirmed it
  never did. Generation was **blind**; the reference/test are touched **only** by the scorer.
- No iterate-against-the-hidden-test loop. The 93.59% is a true single-shot blind number.
- The 10 failures below were analysed **post-hoc** (after the score was locked) purely to
  characterise them — that analysis did **not** feed back into the score.

## The 10 failures (honest)
| Problem | Mode | Root cause (post-hoc) |
|---|---|---|
| Prob099_m2014_q6c | compile | garbled prompt interface → generated ports Y1/Y3, the design needs Y2/Y4 (prompt-fidelity miss) |
| Prob062_bugs_mux2 | functional | a deliberate "find-and-fix the bug" problem |
| Prob034_dff8 | functional | DFF reset/edge timing nuance |
| Prob053_m2014_q4d | functional | XOR-fed DFF, edge/reset timing |
| Prob074_ece241_2014_q4 | functional | DFF-chain init/timing |
| Prob089_ece241_2014_q5a | functional | Moore FSM async-reset / output timing |
| Prob092_gatesv100 | functional | 100-bit gate-vector edge case |
| Prob093_ece241_2014_q3 | functional | K-map / don't-care minimisation choice |
| Prob104_mt2015_muxdff | functional | mux+DFF sampling-cycle interpretation |
| Prob149_ece241_2013_q4 | functional | reservoir/thermometer FSM state decode |

These are the classic subtle HDLBits-derived cases (sync-vs-async reset, output-by-one-cycle,
don't-care choices, the intentional bug-fixing problems) where a single blind shot diverges
from the exact reference — the expected ~6% tail.

## Scope / positioning
VerilogEval measures the **single-module RTL-generation sliver** only. Vibe-IC's differentiator
is the full **design-documents → RTL → synth → PnR → GDS → sign-off** flow (56 steps, 6-pillar
verification), evidenced by `benchmark_clean/` (spm, sha256, u_hawaii_adc, subservient). This
93.59% is the "can the underlying model write a correct module from a spec" baseline that the
full flow builds on.

## Reproduce
```bash
git clone https://github.com/NVlabs/verilog-eval   # @ c498220
python3 score_verilogeval.py --run . --dataset <verilog-eval>/dataset_spec-to-rtl
# (samples/ here are our blind single-shot generations)
```
