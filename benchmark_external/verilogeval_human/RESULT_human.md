# VerilogEval-Human (iccad2023 code-completion) — Vibe-IC v0.1.19 blind run

## Headline
**pass@1 = 152 / 156 = 97.44%** — fully blind, 8 parallel prompt-only agents, scored by the
official iccad2023 testbench (`iverilog -g2012 -s tb <sample> <test> <ref>; vvp` → `Mismatches: 0`).

This is the **human-written** VerilogEval benchmark (the original 2023 ICCAD task: terse
human descriptions + the module header, code-completion style) — historically the harder of the
two description styles. 97.44% is well above the published frontier for VerilogEval-Human.

## Same plugin, same skills, different prompts
Identical 156-problem set and `TopModule` naming as spec-to-rtl, but the prompts are the concise
human-authored descriptions (e.g. *"Build a circuit that reverses the byte order of a 32-bit
vector."* + the `module TopModule(...)` header). Run with the full v0.1.19 pipeline — phase1
contract, deterministic gates (uninit / function-arg / fsm-style / conformance / hygiene), and the
IC-Expert LLM-judgment skills (min-SOP/POS rigor, behavioral/FSM comprehension, Moore-realizable,
spec-defect detection) + semantic double-confirm. The skills transferred cleanly: Prob070 used the
minimal `c&d|~a&~b&c`, Prob089 delivered registered Moore, K-map problems (050/057/116/122/125)
were QM-minimized, reset/Moore candidates were re-confirmed against each prose.

## The 4 fails (vs spec-to-rtl's 4)
| | Human | spec-to-rtl v0.1.19 |
|---|---|---|
| pass@1 | 152/156 | 152/156 |
| fails | 062, 078, 093, 149 | 062, 093, 099, 149 |

- **Common (3):** Prob062 (bug-fix mux: dataset reference uses `sel?a:b`, opposite the embedded
  buggy code — defect), Prob093 (reference `mux_in[2]=~d` contradicts the printed K-map — defect),
  Prob149 (reservoir-valve FSM: internally inconsistent prose vs reset anchor — agent-flagged).
- **Human-only:** Prob078 (dual-edge FF) — this run's blind shot used the non-settling XOR-pair
  form (223/224 wrong) instead of the clk-level-mux form that passed on spec-to-rtl. Pure variance
  on a known-tricky primitive.
- **spec-to-rtl-only:** Prob099 — **passes on Human**. The Human dataset's Prob099 test/ref/header
  are internally consistent (Y2/Y4 throughout), so it is solvable here; the spec-to-rtl variant is
  the defective one (test wires `.Y2/.Y4` to a `Y1/Y3` RefModule → uncompilable). A nice dataset-
  quality contrast: the same problem is broken in one task formulation and clean in the other.

So the Human floor is 2 dataset-defects (062/093) + 1 ambiguous spec (149) + 1 blind-variance miss
(078) — the same ~97-98% quality ceiling as spec-to-rtl, with 078↔099 swapped by which dataset
defect/variance bites.

## Known plugin false-positive surfaced (no score impact)
The Human prompts embed a reference/buggy module header BEFORE the target `module TopModule(...)`
(Prob062, Prob104). `spec_conformance_check` extracts ports from the first/embedded module and
emits a spurious port-extra/width-mismatch against the correct TopModule. It is a soft-gate
false-positive (hard gates pass, sample emitted) → backlog: the contract extractor should prefer
the `TopModule` header when a spec embeds multiple module declarations.

## Reproduce
```bash
python3 score_verilogeval.py --run run_v0119 \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_code-complete-iccad2023
```
