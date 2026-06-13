# SPM Cross-Check — Phase-1 + Phase-2 (Stage 1+2) Summary

OURS: `benchmark_clean/spm` (100% GENERATED carry-save bit-serial RTL).
REF:  `AI_IC_design/4th_benchmark/spm_e2e` (upstream open-source reference run).
All EDA run in container `iic-eda`; OUR files staged at `/foss/designs/_spm_xc_p12/`.
Tools: yosys 0.62, verilator 5.044, iverilog/vvp, OpenSTA 2.7.0, SymbiYosys+yices,
plus chip-agnostic plugin auditors. No copying — OUR RTL is independently generated.

| Step | Verdict | OUR vs REF (one-liner) |
|------|---------|------------------------|
| D1 — L-docs | MATCH / DIFF-OK | Input docs byte-identical; clock/param/reset/PDK agree; REF adds optional port/opcode enrichment OURS leaves honest-empty; OUR L8 ic_name correct vs REF UNKNOWN_IC |
| 1 — Spec→RTL equiv | EQUIVALENT | yosys SAT size=8 proves OUR-RTL ≡ REF-RTL (17/17); both pass 10,013 golden vectors; 32-bit covered by exhaustive+vector+induction |
| 2 — Lint | MATCH | verilator -Wall clean both (exit 0, 0 warn); rtl_hygiene `[]`; name-semantic PASS |
| 3 — CDC/RDC | EQUIVALENT | OUR single-clock posedge `clk`, 3 sdff, zero crossings; REF PASS (its chip_top synchroniser is wrapper-only) |
| 4 — Simulation | MATCH | OUR + REF both PASS same 10,013-vector golden = (x*y) mod 2^N + mid-reset recovery |
| 5 — Formal | EQUIVALENT / OURS-STRONGER | SymbiYosys k-induction PASS size=8 (unbounded); REF "formal" is a TB result, not a math proof; 32-bit direct SAT = honest GAP (intractable, not required) |
| 7 — SDC diff | EQUIVALENT | Both from L9 100 MHz; OUR 10 ns on-target; REF stage2 relaxed 20 ns; I/O delay 2 ns agree |
| 8 — SDC validation | MATCH / OURS-CLEANER | OUR sdc_syntax 0 errors; REF set has 1 NO_TIMING_CONSTRAINT error on a chip_top SDC |
| 9 — Synthesis + LEC | MATCH | OUR vs REF cell-for-cell identical: 286 cells, 64 DFF, area 2623.7664; = REF stored synth; LEC OUR-net≡OUR-RTL proven (65/65 k-induction) + 10,013-vec gate sim PASS |
| 10 — Pre-layout STA | PASS | OUR netlist MET @10 ns all corners: SS +5.82/+1.54, TT +7.49/+0.45, FF +7.68/+0.29 (setup/hold), TNS=0; single-FA critical path |
| 11 — DFT | EQUIVALENT | OUR = single 64-flop scan chain (sky130 sdf cells exist); ATPG 97.03% stuck-at by identical-netlist = REF measured 97.03% (1046/1078) |
| 12 — Post-DFT opt | EQUIVALENT | spm needs no post-scan buffering (opt no-op, STA already met); REF likewise carries scan netlist unchanged |
| 13 — LEC RTL≡post-DFT | MATCH | OUR RTL ≡ OUR netlist proven 65/65 by k-induction (equiv_induct -seq 40) + gate sim |
| 14 — Pre-PnR gate | MATCH | rtl_precheck_gate 6/6 PASS, synthesizes clean; REF passed equivalent gate |
| P0 — Structural pre-flight | MATCH | All applicable chip-agnostic auditors clean (0 findings); protocol/FSM/OTP checks correctly no-op for flat datapath; REF clean too |

## Bottom line
- **MATCH/EQUIVALENT: D1, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, P0** — every step.
- **Headline:** OUR independently-GENERATED RTL is yosys-SAT-equivalent to REF RTL
  (size=8), synthesizes to a **cell-for-cell identical** sky130 netlist (286 cells,
  area 2623.7664), passes 10,013 golden vectors, MEETS STA at SS/TT/FF @10 ns, and is
  k-induction LEC-equivalent to its own netlist.
- **Honest GAPs (none blocking):**
  - Direct **32-bit pure-SAT** multiplier proof is intractable (classic) — NOT claimed;
    covered by size=8 unbounded k-induction + size=8 SAT-vs-REF + 10,013-vector size=32
    sim. REF produced no 32-bit math proof either.
  - **ATPG** coverage on OUR netlist is asserted EQUIVALENT-by-identical-netlist to
    REF's measured 97.03%, not independently re-run end-to-end in this cross-check.
  - **Pre-layout multi-corner STA** has no directly-comparable REF phase2 artifact (REF
    stored only phase3 post-layout STA @20 ns); OUR result stands on its own + identical
    netlist.
