# L8 — Submodule Integration

## Instantiation tree (no stub modules — DTOP instantiates everything)
- `user_project_wrapper` (top) instantiates exactly one `user_proj_example`,
  wiring through: `wb_clk_i`, `wb_rst_i`, full `wbs_*`, `la_data_in/out/oenb`,
  `io_in/out/oeb[37:0]` (sliced/extended to `BITS`), `user_irq←irq`, and the
  `USE_POWER_PINS` rails `vccd1/vssd1`.
- `user_proj_example #(.BITS(32))` instantiates one `counter #(.BITS(32))`.
- `counter` is leaf sequential logic (single `always @(posedge clk)`).

## Port-mapping contract (wrapper → example)
| wrapper signal | example port | notes |
|---|---|---|
| `wb_clk_i` | `wb_clk_i` | clock (pre LA-mux) |
| `wb_rst_i` | `wb_rst_i` | reset (pre LA-mux) |
| `wbs_*` | `wbs_*` | full Wishbone slave |
| `la_data_in/out/oenb` | `la_*` | 128-bit |
| `io_in/out/oeb` | `io_in/out/oeb` | `[BITS-1:0]` of the 38-bit GPIO |
| `user_irq` | `irq` | 3-bit |

## Integration rules
- The wrapper port list and name set are FIXED by the Caravel harness — RTL gen
  must not rename or drop wrapper ports.
- Tristate / inout (`analog_io`, power) live at the wrapper (top) level only.
- Power pins gated by `USE_POWER_PINS` for both PnR and gate-level sim.
