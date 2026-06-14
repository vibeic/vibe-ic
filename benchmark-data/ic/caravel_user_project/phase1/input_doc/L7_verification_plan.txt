# L7 — Verification Plan

The stock caravel_user_project ships three reference testbenches under
`verilog/dv/` (RISC-V firmware + cocotb), all of which the benchmark must
reproduce functionally:

1. **io_ports** — management firmware starts the counter, reads back GPIO
   `io_out` and checks it advances; verifies the GPIO output path.
2. **la_test1** — drives the counter through the logic-analyzer probe bus:
   override clock/reset via `la_data_in[64]/[65]`, force `count` bits via the
   `la_write` path, check `la_data_out` mirrors the count.
3. **la_test2** — second LA scenario exercising the LA-write masking and the
   simultaneous Wishbone/LA arbitration.

## Coverage targets
- Functional coverage: 100 % of the three DV scenarios passing (closed-loop).
- Wishbone read-after-write of COUNT register returns the written value.
- Counter free-run increments by exactly 1/clock when idle.
- LA override priority over free-run when a LA lane is active.
- Reset clears count to 0.

## Tool substitution (open-source)
- Simulation: iverilog 12 (substitutes Synopsys VCS).
- Synthesis: yosys; PnR: OpenROAD/OpenLane (substitutes Design Compiler).
- DRC/LVS: KLayout + Magic + netgen.
- mpw_precheck (ChipFoundry/eFabless) for shuttle structural gates.
