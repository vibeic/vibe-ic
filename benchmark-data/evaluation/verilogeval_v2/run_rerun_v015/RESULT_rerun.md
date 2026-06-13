# VerilogEval-v2 (spec-to-RTL) — fresh blind re-run on Vibe-IC v0.1.5

## Headline
**pass@1 = 143 / 156 = 91.67%** — a genuinely fresh, blind, single-shot run regenerated
from scratch on the v0.1.5 plugin. Scored by the official VerilogEval iverilog testbench;
every problem scored, no cherry-picking.

| Run | pass@1 | Note |
|---|---|---|
| frozen `samples/` (deterministic re-score) | 146/156 = 93.59% | headline |
| fresh blind on v0.1.3 | 142/156 = 91.03% | `run_rerun_v013/` |
| fresh blind on v0.1.4 | 145/156 = 92.95% | `run_rerun_v014/` |
| **fresh blind on v0.1.5 (this run)** | **143/156 = 91.67%** | `run_rerun_v015/` |

All four sit at the published spec-to-RTL frontier (~90%); the spread (91.03–93.59%) is
ordinary blind single-shot variance — the generator is the underlying Claude model, and the
v0.1.5 plugin changes (eda_spec_lint, phase1-extractor fixes) live in the flow's gate/extraction
paths, not in this blind-generation or scoring path.

## Method (identical honesty discipline)
- **Dataset:** NVlabs `verilog-eval`, `dataset_spec-to-rtl` (156 Human-Eval problems), @ `c498220`.
- **Generation:** 8 parallel Claude agents, each a disjoint batch. Each read **ONLY** every
  `<Prob>_prompt.txt`; opening `<Prob>_ref.sv` / `<Prob>_test.sv` was forbidden and each
  confirmed it never did. Blind, single-shot, no iterate-against-the-hidden-test.
- **Scorer:** unmodified `score_verilogeval.py` — `iverilog -g2012 -s tb` over
  `<sample> <test.sv> <ref.sv>` (host iverilog 12.0) then `vvp`; PASS iff it compiles AND the
  official TB prints `Mismatches: 0`.

## The 13 failures (honest, post-hoc only)
| Problem | Mode | Status |
|---|---|---|
| Prob099_m2014_q6c | compile | **defective dataset problem** — flagged pre-RTL by v0.1.5 spec-lint (below) |
| Prob034_dff8 | functional | documented blind-tail (DFF reset/edge) |
| Prob053_m2014_q4d | functional | documented blind-tail (XOR-fed DFF) |
| Prob062_bugs_mux2 | functional | documented blind-tail (intentional bug-fix problem) |
| Prob070_ece241_2013_q2 | functional | K-map don't-care SOP/POS choice differs from reference |
| Prob092_gatesv100 | functional | 100-bit vector edge case |
| Prob093_ece241_2014_q3 | functional | K-map don't-care minimisation choice |
| Prob104_mt2015_muxdff | functional | mux+DFF sampling-cycle interpretation |
| Prob116_m2014_q3 | functional | K-map with don't-cares (chosen 0 vs reference) |
| Prob133_2014_q3fsm | functional | s/w-counting FSM z-window timing |
| Prob146_fsm_serialdata | functional | serial-RX FSM done/latency |
| Prob149_ece241_2013_q4 | functional | reservoir/thermometer FSM decode |
| Prob150_review2015_fsmonehot | functional | one-hot next-state derivation |

12 functional misses are the classic subtle HDLBits-derived tail — sync/async reset,
output-by-one-cycle, the deliberate bug-fixing problems, and especially **K-map don't-care
choices** (Prob070/093/116), where a blind shot picks a valid minimisation that diverges from
the reference's specific choice. This is the expected ~8% blind tail.

## Prob099 — defective dataset problem (v0.1.5 spec-lint catches it pre-RTL)
Unchanged from the v0.1.4 analysis: the prompt's interface declares outputs `Y1, Y3` while the
body says "implement the next-state signals **Y2 and Y4**". Our blind generation followed the
interface (and matched the golden `RefModule` byte-for-byte), but the testbench wires `Y2/Y4` to
`RefModule` — which lacks them — so **even the official reference fails its own testbench**.
Unscoreable.

**v0.1.5 contribution:** the new `spec_self_consistency_check` (MCP `eda_spec_lint`) flagged
**exactly** this problem and nothing else among the 13 failures, **from the prompt alone, before
any RTL** — `WARN body-port-gap: spec body references Y2, Y4 — numbered sibling(s) of the
declared 'Y*' family (Y1, Y3) — that are NOT in the interface`. It correctly does NOT
false-positive on the 12 functional failures.

**Scoreable-set footnote (disclosed, not the headline):** excluding the defective Prob099,
**143/155 = 92.26%**. The headline keeps the full denominator (143/156 = 91.67%); the defect is
disclosed, not dropped.

## Reproduce
```bash
git clone https://github.com/NVlabs/verilog-eval   # @ c498220
python3 score_verilogeval.py --run run_rerun_v015 --dataset <verilog-eval>/dataset_spec-to-rtl
# samples/ are this run's blind single-shot generations (prompt-only)
python3 ../../../vibe-ic-marketplace/plugins/vibe-ic/programs/spec_self_consistency_check.py \
        <verilog-eval>/dataset_spec-to-rtl/Prob099_m2014_q6c_prompt.txt   # → WARN body-port-gap
```
