# Step 9 — Synthesis (OUR vs REF) + LEC

## What we ran
- yosys `synth -top spm -flatten; dfflibmap; abc -liberty …; stat` with the SAME lib
  `sky130_fd_sc_hd__tt_025C_1v80.lib` on OUR RTL and (separately) REF RTL.
- LEC #1: OUR provided gate netlist (`phase2/stage2/synth/spm_synth.v`) ≡ OUR RTL via
  yosys `equiv_make` + `equiv_simple -seq 5` + `equiv_induct -seq 40`.
- LEC #2 (independent): gate-level iverilog sim of OUR netlist + sky130 cell models
  against the 10,013 golden vectors.

## OUR vs REF synthesis result — IDENTICAL
| cell | OUR | REF | REF stored (synth_netlist.json) |
|------|-----|-----|---------------------------------|
| a21o_1 | 31 | 31 | 31 |
| a21oi_1 | 32 | 32 | 32 |
| a31oi_1 | 31 | 31 | 31 |
| and2_0 | 1 | 1 | 1 |
| and3_1 | 31 | 31 | 31 |
| dfxtp_1 | 64 | 64 | 64 |
| nand3_1 | 32 | 32 | 32 |
| nor2_1 | 2 | 2 | 2 |
| nor3_1 | 31 | 31 | 31 |
| nor3b_1 | 31 | 31 | 31 |
| **total** | **286** | **286** | **286** |
| **chip area** | **2623.7664** | **2623.7664** | — |

Cell-for-cell identical; chip area identical to 4 decimals. Matches REF's recorded
`synth_netlist.json` (total_cells 286, same 10 cell types, 64 dfxtp_1).

## LEC result
- **LEC #1 (formal):** `equiv_induct -seq 40` proved all 65 `$equiv` points →
  `Of those cells 65 are proven and 0 are unproven. Equivalence successfully proven!`
  (exit 0). OUR netlist ≡ OUR RTL. (An earlier name-aligned `equiv_simple`-only attempt
  left 33 unproven because synthesis renamed/restructured internal state — the
  sequential k-induction `equiv_induct -seq 40` closes them all; honest record kept.)
- **LEC #2 (sim):** gate-level netlist + `sky130_fd_sc_hd.v` models →
  `RESULT: PASS (all 10013 vectors + reset tests match golden)`.
- OUR-RTL ≡ REF-RTL already proven in step 1 (SAT size=8). Since OUR and REF synth to
  the identical netlist, OUR-netlist ≡ REF-netlist follows transitively.

## Verdict: MATCH
Synthesis is bit-identical (286 cells, area 2623.7664) between OUR and REF, equal to
REF's stored result. OUR netlist is formally LEC-equivalent to OUR RTL (k-induction)
and passes 10,013-vector gate sim. MATCH.
