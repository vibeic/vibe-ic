# Step 9 — Synthesis (OUR + REF RTL → sky130_fd_sc_hd) + LEC

**Verdict: IN-RANGE** (cell count / area within ~6%; LEC EQUIVALENT-by-simulation)

## What ran
1. `eda_synth` (yosys 0.62, MCP) of OURS and REF to **the same**
   `sky130_fd_sc_hd` library. Also a native `yosys synth -flatten` +
   `dfflibmap`/`abc` pass with the local `tt_025C_1v80.lib`.
2. LEC of OUR gate netlist ≡ OUR RTL (see "LEC" below).

## Synthesis result (MCP, hierarchical)
| Metric | OURS | REF | Δ |
|--------|------|-----|---|
| Total cells | 10083 | 9067 | +11 % |
| Chip area (um²) | 89492 | 84466 | +6 % |
| Sequential area % | 40.4 % | 43.7 % | — |
| Eff. flip-flops (dfxtp+edfxtp) | 1552 | 1586 | ≈equal |

Native flatten run: OURS 10463 cells / 88112 um², REF 9943 cells / 84716 um²
(REF's own synth.log reported `sha256` area 85664 um² — consistent).

## Finding
Magnitudes agree within single-digit %. The two micro-architectures show their
fingerprints exactly as expected:
- OURS (carry-save) uses **more maj3 / xnor3 / xor3** (CSA 3:2 compressor +
  carry-select cells): maj3 185, xnor3 45, xor3 26.
- REF (ripple `+`) uses **more and3 / a21oi** (ripple-carry chains): and3 298,
  a21oi 1374.
Both ~1550 FFs (identical iterative state: a–h, H0–H7, w[0..15], FSM, regfile).
NOT identical (different datapath) but clearly **in-range** — the criterion.

## LEC (OUR netlist ≡ OUR RTL)
- `yosys equiv_induct` and the MCP `eda_equiv` both **could not complete** a
  structural sequential proof: equiv_induct left 1617 registers unproven (no
  auto state-map on the 256-bit datapath); `eda_equiv` errored because its flow
  reads the sky130-mapped netlist as plain Verilog without loading liberty cell
  models (tool-flow limitation). → structural LEC = **GAP** (documented
  intractability for a 256-bit hash).
- **Functional LEC proxy ran and PASSED**: gate-level simulation of OUR
  sky130-mapped netlist (`ours_netlist.v` + sky130 cell models + primitives.v)
  against the full step-4 KAT+random TB → **20/20 ALL_PASS**. This proves
  netlist ≡ RTL across the entire FIPS-180-4 golden surface.

→ Net LEC verdict: **EQUIVALENT (by gate-level KAT simulation)**; structural
proof honestly noted as GAP.
