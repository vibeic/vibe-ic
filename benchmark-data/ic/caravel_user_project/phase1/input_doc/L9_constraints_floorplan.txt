# L9 — Constraints & Floorplan

## PDK / target
- PDK: SKY130A. Standard-cell lib: sky130_fd_sc_hd.

## Clock / timing (from upstream OpenLane config)
- `CLOCK_PORT = wb_clk_i`, `CLOCK_PERIOD = 25 ns` (40 MHz).
- `set_input_delay = 0.5 * CLOCK_PERIOD` on `wb_rst_i` relative to the clock.
- Single clock domain; synchronous active-high reset.

## Floorplan (user_project_wrapper — Caravel-fixed)
- `FP_SIZING = absolute`, `DIE_AREA = [0, 0, 2920, 3520]` µm (2.92 mm × 3.52 mm).
- Wrapper pin order / power-pin locations are FIXED (`fixed_dont_change/` DEF +
  `pin_order.cfg` + power `vsrc/*.loc` from the upstream template).
- Power: vccd1/vssd1 (user area 1, 1.8 V). met1 follow-pins + met4/met5 stripes
  PDN; the wrapper relies on the harness power ring.

## user_proj_example block
- Hardened as a macro inside the wrapper, then the wrapper is hardened with the
  macro placed. `CLOCK_PERIOD = 25 ns` for sky130 (tighter corners 8–10 ns exist
  in the multi-corner sweep config).

## Sign-off gates (shuttle-ready)
- DRC clean (KLayout + Magic), LVS clean (netgen), antenna clean.
- mpw_precheck structural gates PASS.
- STA: setup/hold met at the 25 ns period across sky130 corners.
