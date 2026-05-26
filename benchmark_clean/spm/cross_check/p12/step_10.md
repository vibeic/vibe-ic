# Step 10 — Pre-layout STA (multi-corner) on OUR synth netlist

## What we ran
- OpenSTA 2.7.0 on OUR gate netlist `phase2/stage2/synth/spm_synth.v` @ 10 ns
  (core_clock 100 MHz, in/out delay 2 ns), across three corners:
  - SS: `sky130_fd_sc_hd__ss_n40C_1v40.lib`
  - TT: `sky130_fd_sc_hd__tt_025C_1v80.lib`
  - FF: `sky130_fd_sc_hd__ff_n40C_1v95.lib`
- Per corner: `report_checks -path_delay max`, `report_worst_slack -max/-min`,
  `report_tns`.

## OUR result — ALL CORNERS MET @ 10 ns
| corner | WNS setup (max) | worst hold (min) | TNS |
|--------|-----------------|------------------|-----|
| SS | **+5.82 ns** | +1.54 ns | 0.00 |
| TT | **+7.49 ns** | +0.45 ns | 0.00 |
| FF | **+7.68 ns** | +0.29 ns | 0.00 |

- Critical path (SS): `x[0] → a21o_1 → and3_1 → nor3_1 → dfxtp_1/D`, arrival 3.79 ns
  vs required 9.61 ns → slack +5.82 ns. This confirms the carry-save claim in the RTL
  header: the combinational depth is a **single full adder**, INDEPENDENT of N, so even
  the slow corner clears 10 ns with >5 ns margin (a naive 33-bit ripple would NOT).
- Hold met at all corners (min slack +0.29 ns worst, FF).

## REF result
REF stage3 STA reports live under `phase3/stage3/sta` (post-layout, 20 ns SDC). REF did
not store an equivalent pre-layout 10 ns multi-corner spm-core STA in phase2. The
architectures are identical (286 cells, single-FA path), so REF's netlist would show the
same single-FA critical path. No contradictory REF datum.

## Verdict: PASS (OURS) / EQUIVALENT structurally
Pre-layout STA on OUR netlist MEETS setup and hold at SS/TT/FF @ 10 ns with large
margin (WNS +5.82 ns at SS). The carry-save micro-architecture removes the long carry
chain. REF has no directly-comparable pre-layout 10 ns spm STA artifact, but the
identical netlist guarantees equivalent timing. PASS.
