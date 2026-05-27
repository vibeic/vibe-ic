# Four-benchmark MCP-EDA re-run — Vibe-IC **v0.1.23** (fresh agents, blind, agentic)

User request: *"Have fresh agents use the newest vibe-ic plugin with MCP-EDA to run full
VerilogEval-v2, VerilogEval-Human, VerilogEval-Machine and CVDP."* → 25 **fresh** sub-agents (no
shared context, no prior-run memory) authored every sample **blind** (read only
`<Prob>_prompt.txt` / `docs/specification.md`; never `_ref.sv` / `_test.sv` / hidden harness), each
self-verifying through the **MCP-EDA toolchain** (`eda_lint` + `eda_synth`, gf180) before the host
scored deterministically.

Plugin **v0.1.23**; MCP-EDA server **v0.113.0** (`iic-eda` container). Run dirs:
`*/run_v0123_mcp/` (VerilogEval) and `cvdp/run_v0123/`.

## Headline

| Benchmark | prompt style | pass@1 (this v0.1.23 MCP run) | prior v0.1.22 MCP | defect floor | gap = blind variance |
|---|---|---|---|---|---|
| VerilogEval-v2 spec-to-rtl | structured interface bullets | **144 / 156 = 92.31%** | 147 | 152 (4 defects) | 8 |
| VerilogEval-Human (iccad2023) | concise human prose + header | **150 / 156 = 96.15%** | 150 | 153 (3 defects) | 3 |
| VerilogEval-Machine (legacy v1.0.0) | verbose LLM-generated prose | **132 / 143 = 92.31%** | 133 | 136 (7 defects) | 4 |
| CVDP agentic (gated, N=1) | spec.md + cocotb harness | **FAIL** (1/9 hidden cases) | FAIL | — | — |

**Every emitted sample** (156 + 156 + 143 = **455**) is **`eda_lint` clean (Verilator 5.044, 0 err
/ 0 warn)** and **`eda_synth` synthesizable (Yosys gf180)**. The structural contribution of MCP-EDA
**held on 100% of samples** — and on this fresh run it forced the same real fixes during authoring:
LATCH → `always_latch` (Prob028, 145), CASEINCOMPLETE → explicit `default` (Prob106), Verilator
BLKSEQ → carry-via-wires + clocked `<=` (Prob141), CASEOVERLAP → priority if-chain (Prob071).

This is **within blind-sampling noise** of the v0.1.22 cherry-best (v2 −3, Human ±0, Machine −1).
The dominant new contributor to the v2 dip is a single, *newly-isolated, recoverable* class — the
**power-up-init phase** (below) — not a regression and not a dataset defect.

## The one genuinely actionable finding: reset-less registered-output power-up

Three fails this run have **RTL byte-identical to the hidden reference** — the *only* difference is
a missing `initial <reg> = 0;`, and the official testbench samples the output at **t = 0**:

| Prob | ref logic | sample logic | only difference |
|---|---|---|---|
| Prob034_dff8 (v2) | `q<=d` + `initial q=8'h0` | `q<=d` | sample has no `initial` → q=x at t=0 |
| Prob053_m2014_q4d (v2) | `out<=in^out` + `initial out=0` | `q<=in^q` (no init) | same |
| Prob104_mt2015_muxdff (v2+Human+Machine) | `Q<=L?r_in:q_in` + `initial Q=0` | `Q<=L?r_in:q_in` | same |

The fresh agents uniformly left these **reset-less** because the per-problem instruction said the
`rtl_hygiene_lint` *uninit-registered-output* WARN was "acceptable — do not over-fit to silence
WARNs." That guidance is **too weak for this convention**: VerilogEval references with no reset port
consistently use `initial <reg>=0` and the bench checks t=0, so leaving it `x` is a deterministic
loss. The cherry-best v0.1.22 runs happened to add `initial=0` on these; this fresh sample did not.

**Recommended general fix (not overfit):** when a registered output has no reset and the prompt
states no power-up value, default to `initial <reg> = 0;` for a deterministic, sim-matching
power-up — this *resolves* the uninit WARN semantically rather than merely tolerating it. This is a
community-backlog **candidate** (general, IC-agnostic; applies to any reset-less VerilogEval-class
DUT) — not yet filed.

## Fail classification (defect vs blind-variance vs power-up-init)

### VerilogEval-v2 144/156 — fails: 034 053 062 070 092 093 099 104 122 149 150 155
- **Power-up-init (3, recoverable):** 034, 053, 104 — logic == ref, only `initial=0` missing.
- **Dataset defects (4, irreducible):** 062 (buggy-mux polarity), 093 (ref `mux_in[2]=~d` wrong vs
  prompt's own K-map), 099 (TB wires `.Y2/.Y4` to a `Y1/Y3` RefModule → uncompilable for any DUT),
  149 (reference inverts the prompt's stated `dfr` polarity).
- **Blind variance (5, solvable, this sample missed):** 070 (dual-POS don't-care fill), 092
  (`out_any[0]` must be 0 — sample's `in | {in[98:0],1'b0}` leaks `in[0]`, a real boundary-bit miss),
  122 (checkerboard K-map = `a^b^c^d`, mis-derived), 150 (one-hot FSM — dropped the `Count`/`Wait`
  self-loop next-state terms), 155 (lemmings4 fall-FSM).

### VerilogEval-Human 150/156 — fails: 062 093 104 113 149 150
- **Power-up-init (1):** 104.
- **Dataset defects (3):** 062, 093, 149 (same as v2; here 099 is solvable and **passed**).
- **Blind variance (2):** 113 (prose "5-bit x" vs 4-bit `x[4:1]` header — header authoritative),
  150 (one-hot FSM self-loops).

### VerilogEval-Machine 132/143 — fails: 061 067 072 085 104 105 122 131 133 139 154
- **Power-up-init (1):** 104.
- **Description defects (6):** 072 (fan-condition contradicts ref), 085 (shift direction), 105
  (rotate direction), 122 (kmap4 prose self-contradictory: "all-ones→1" contradicts ref `4'hf→0`),
  131 (gate functions absent from prose), 133 (output `z` never defined in prose).
- **Blind variance (4):** 061 (R-reset vs L-mux semantics), 067 (prose says "asynchronous reset" but
  ref is **synchronous** — agent followed the prose adjective; the v0.1.22 "reset-structure-beats-
  adjective" lesson would recover it), 139 (q2b FSM), 154 (PS2-data FSM).
- Note: **Prob099_machine passed this run** (the garbled one-hot prose happened to land correctly),
  so only 6 of the 7 catalogued machine defects were hit.

### CVDP agentic — N=1 (honest scope)
CVDP's full set is gated (NVIDIA/Turing). The only runnable agentic example with a cocotb harness is
`cvdp_agentic_fixed_arbiter_0001`. The fresh agent authored `fixed_priority_arbiter` blind and
self-verified: **`eda_lint` PASS**, **in-context TB 7/7 PASS**, **`eda_synth` PASS** (71 cells,
12 DFFs, **0 latches**). The **hidden** cocotb harness (`test_fixed_priority_arbiter.py`, run via MCP
`eda_cocotb`/Icarus) returned **1 pass / 8 fail of 9** — dominated by *Test Case 8 "grant should be
zero after reset"*. Root cause is the documented **spec ambiguity**: the spec's Port table literally
says *"Active-high **synchronous** reset"*, which the agent implemented faithfully, but the harness's
reset timing requires the reset to clear `grant` the way an **async** reset would; the
`priority_override` direction is also under-specified. Per discipline the agent was **not** iterated
against the hidden harness (no overfit). This fresh sample picked the sync-reset reading (8/9 fail);
the v0.1.22 sample picked async (only the override case failed) — both are honest blind readings of
the same ambiguous spec. Details: `cvdp/run_v0123/` + the eda_cocotb log.

## Honest conclusion

MCP-EDA remains a genuine **structural** strengthening: all 455 blind samples are Verilator-clean
and Yosys-gf180-synthesizable, and the toolchain forced the same concrete fixes (latch,
case-incomplete, BLKSEQ, case-overlap) an iverilog-only gate misses. It is **not** a functional
pass@1 lever. The pass@1 band (144 / 150 / 132 and the CVDP N=1 FAIL) sits within
`defect-floor + blind-variance`, a few points off the v0.1.22 cherry-best as expected for an
independent fresh blind sample.

What this fresh run **added** over prior runs: it cleanly isolated the **power-up-init** class
(Prob034/053/104) — the only systematic, *recoverable* (non-defect, non-overfit) gap — which points
to one general plugin improvement (default reset-less registered outputs to `initial 0`). Everything
else is either an irreducible benchmark-data defect (`RESIDUAL_DEFECTS.md`) or solvable-but-missed
ambiguity (K-map fills, one-hot FSM self-loops, boundary bits, sign-extend, reset adjective) that a
different blind draw would catch.

## Reproduce
```bash
cd benchmark_external/verilogeval_v2 && python3 score_verilogeval.py --run run_v0123_mcp \
  --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl       # 144/156
cd benchmark_external/verilogeval_human && python3 score_verilogeval.py --run run_v0123_mcp \
  --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_code-complete-iccad2023  # 150/156
cd benchmark_external/verilogeval_machine && python3 score_verilogeval.py --run run_v0123_mcp \
  --dataset dataset_machine                                                              # 132/143
# CVDP hidden harness via MCP eda_cocotb (stage RTL+test+harness_library under the iic-eda mount):
#   /foss/designs/_bench_stage/v0123/cvdp/{fixed_priority_arbiter.sv,test_fixed_priority_arbiter.py,harness_library.py}
```
(MCP-EDA tools run inside `iic-eda`, which mounts only `/home/reyerchu/AI_IC_design → /foss/designs`;
RTL/TB must be staged there and passed as `/foss/designs/...` container paths.)
