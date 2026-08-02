# Transition (at-speed) ATPG plan — launch-off-capture

Design clock : wb_clk_i
Cut netlist  : phase2/stage2/dft/cut_netlist.v
Cell model   : /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
Target       : stuck-at-independent transition-fault coverage >= 90.00%

## Fault model
Transition (a.k.a. delay / at-speed) faults model a node that is
functionally correct but too SLOW: a slow-to-rise (STR) or slow-to-fall
(STF) fault at each gate terminal. Detecting them requires a TWO-PATTERN
test (an initialization vector V1 then a launch vector V2) applied so the
transition is launched and captured at the rated (at-speed) clock period.

## Launch-off-capture (LOC) mechanism
1. Scan-in the initialization pattern V1 through the scan chain
   (scan_enable = 1) — the same scan chain inserted for stuck-at.
2. De-assert scan_enable (functional mode).
3. Pulse the functional clock at the rated period to LAUNCH the transition
   (V1 -> V2 combinational evolution) and CAPTURE the response one at-speed
   cycle later.
4. Scan-out the captured response and compare against the fault-free
   expected value.
(An alternative, launch-off-shift/LOS, launches from the last scan-shift
edge; LOC is preferred because it needs no at-speed scan-enable.)

## Engine capability
Engine probed : Fault (cloudv-io/fault) `fault atpg`
Supported     : False
Limitation     : `fault atpg --help` exposes only single-pattern combinational stuck-at ATPG (no transition / at-speed / launch-off-capture / delay-fault / two-pattern flag) — the Fault engine cannot generate at-speed patterns

## Honesty note
The at-speed pattern set is NOT generated because the open-source Fault engine cannot do transition ATPG. Per DFT-honesty doctrine we emit the mechanism/plan and record the engine limitation rather than fabricate a transition-coverage number. A commercial at-speed ATPG tool (or an OSS engine that gains delay-fault support) is required to close this coverage.
