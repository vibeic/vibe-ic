# Four-benchmark MCP-EDA re-run — Vibe-IC v0.1.22 (blind, agentic)

User request: *"use newest plugin with MCP-EDA to re-try VerilogEval-v2, VerilogEval-Human,
VerilogEval-Machine and CVDP"* → all four re-run through the **MCP-EDA toolchain**, fully blind
(agents read ONLY `<Prob>_prompt.txt` / `docs/specification.md`; never `_ref.sv` / `_test.sv`).

## Headline (this fresh MCP-EDA run)

| Benchmark | prompt style | pass@1 (this MCP run) | defect floor | gap = blind variance |
|---|---|---|---|---|
| VerilogEval-v2 spec-to-rtl | structured interface bullets | **147 / 156 = 94.23%** | 152 (4 defects) | 5 |
| VerilogEval-Human (iccad2023) | concise human prose + header | **150 / 156 = 96.15%** | 153 (3 defects) | 3 |
| VerilogEval-Machine (legacy v1.0.0) | verbose LLM-generated prose | **133 / 143 = 93.01%** | 136 (7 defects) | 3 |
| CVDP agentic (gated, N=1) | spec.md + cocotb harness | FAIL (1/1, spec-ambiguity) | — | — |

**Every emitted sample** (156 + 156 + 143 = 455) is **`eda_lint` clean (Verilator, 0 err / 0 warn)
+ `eda_synth` synthesizable (Yosys gf180)**. That is the structural contribution of MCP-EDA and it
held on 100% of samples.

## What MCP-EDA changed — and what it did not

**It raised structural quality, not functional pass@1.** The MCP gate added two real checks the
deterministic `gates.py` + iverilog pipeline does not perform — Verilator lint and Yosys gf180
synthesis — and these forced concrete, semantics-preserving fixes during authoring:

- **LATCH** → intended transparent latches coded as `always_latch` (Prob028, 145).
- **PROCASSINIT** → reset-less power-up via a separate `initial q=0;` block, not decl-init
  `output reg q=0` (Prob031/034/058/061/080/084/105/108/115/117/124/147, …).
- **CASEOVERLAP** → `casez` priority-encoders rewritten as behaviorally-identical priority
  if-chains (Prob071).
- **CASEINCOMPLETE** → explicit `default` added (Prob088, 106).

**It did not move functional pass@1**, which is governed by two factors MCP-EDA cannot touch:
1. an **irreducible dataset-defect floor** (prompts that contradict their own hidden reference or
   omit essential information — see `RESIDUAL_DEFECTS.md`), and
2. **blind-sampling variance** on genuinely-solvable-but-ambiguous problems (K-map don't-care
   fills, FSM output assignment, shift-vs-rotate, sign-extend-vs-replicate).

Because each benchmark was a *fresh independent blind sample*, this run lands within a few points of
the per-benchmark cherry-best — the gap is purely from (2), not from any MCP-induced regression.
(Verified: v2 and Human are genuinely distinct runs — 153/156 samples differ; the 3 identical are
trivial const tie-offs with a single canonical answer.)

## Fail classification (defect vs blind variance)

### spec-to-rtl 147/156 — fails: 053 062 070 089 093 099 133 146 149
- **Dataset defects (4):** 062 (mux polarity ref-vs-buggy-code), 093 (ref `mux_in[2]=~d` wrong vs
  prompt's own K-map), 099 (TB wires `.Y2/.Y4` to a `Y1/Y3` RefModule → uncompilable for any DUT),
  149 (reference inverts the prompt's stated `dfr` polarity).
- **Blind variance (5):** 053 (toggle-FF init), 070 (dual-POS don't-care fill), 089 (3-state Moore),
  133 (FSM z-assignment), 146 (serial-data FSM) — all solvable; this sample missed them.

### Human 150/156 — fails: 062 089 093 104 113 149
- **Dataset defects (3):** 062, 093, 149 (same as above; on Human, 099 *is* solvable — and this run
  passed it, the nice spec-to-rtl↔Human swap noted in `RESULT_human.md`).
- **Blind variance (3):** 089 (3-state Moore), 104 (mux-DFF power-up: this sample left it reset-less,
  overriding the uninit WARN), 113 (prose "5-bit x" vs 4-bit `x[4:1]` header — header authoritative,
  this interpretation missed the ref). All solvable; this sample missed them.

### Machine 133/143 — fails: 042 063 072 085 094 099 105 122 131 133
- **Description defects (7):** 072/085/105 (prose direction contradicts ref), 122/131/133 (prose
  omits the truth-table / gate-types / `z`-equation), 099 (garbled one-hot prose).
- **Blind variance (3):** 042 (machine prose "24 times" = sign-bit replication for sign-extension;
  the agent dismissed it as contradictory and used `{4{in}}`), 063 (shift/down-count priority),
  094 (gatesv neighbor-op). Defect floor 136 − 3 variance = 133. Consistent.

### CVDP — N=1 (honest scope)
CVDP's full set is gated; the only runnable agentic example with a cocotb harness is
`cvdp_agentic_fixed_arbiter_0001`. The MCP-EDA toolchain ran clean end-to-end (`eda_lint` PASS,
`eda_simulate` 7/7 in-context, `eda_synth` 64 cells / 0 latches), but the **hidden** harness FAILed
at the `priority_override` case on an **ambiguous spec phrase** ("highest-priority bit" — the agent
read it as lowest-index, consistent with the spec's own `req` rule; the harness expects the
opposite). Per discipline the agent was not iterated against the hidden harness (= no overfit).
Details in `cvdp/RESULT_v0122_mcp.md`.

## Honest conclusion

MCP-EDA is a genuine **structural** strengthening of the emit path: every blind sample is now
Verilator-clean and Yosys-synthesizable, and the toolchain surfaced/forced real fixes (latch,
PROCASSINIT, case-overlap/incomplete) that the iverilog-only gate misses. It is **not** a functional
pass@1 lever — that number stays in the `defect-floor + blind-variance` band (here 147 & 150 / 156
and 133 / 143), and a fresh run sampling the ambiguous problems independently is expected to land a
few points off the cherry-best. The irreducible residual remains benchmark-data defects
(`RESIDUAL_DEFECTS.md`); moving them would require reading hidden references (cheating) or
per-problem canonical hard-coding (overfit) — both out of bounds.

## Reproduce
```bash
# spec-to-rtl
cd benchmark_external/verilogeval_v2 && python3 score_verilogeval.py --run run_v0122_mcp \
  --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
# Human
cd benchmark_external/verilogeval_human && python3 score_verilogeval.py --run run_v0122_mcp \
  --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_code-complete-iccad2023
# Machine
cd benchmark_external/verilogeval_machine && python3 score_verilogeval.py --run run_v0122_mcp \
  --dataset dataset_machine
```
(MCP-EDA tools run inside the `iic-eda` Docker container, which mounts only
`/home/reyerchu/AI_IC_design → /foss/designs`; RTL must be staged there with the Bash sandbox
disabled for the container to see it.)
