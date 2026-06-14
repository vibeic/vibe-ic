# L3 — External Interface (user_project_wrapper ports)

Fixed Caravel user-project-wrapper interface (must not be renamed; the harness
wires these by name):

| Port | Dir | Width | Description |
|---|---|---|---|
| `wb_clk_i` | in | 1 | Management Wishbone clock (40 MHz, 25 ns) |
| `wb_rst_i` | in | 1 | Management Wishbone reset (active high) |
| `wbs_stb_i` | in | 1 | Wishbone strobe |
| `wbs_cyc_i` | in | 1 | Wishbone cycle |
| `wbs_we_i` | in | 1 | Wishbone write-enable |
| `wbs_sel_i` | in | 4 | Wishbone byte-select |
| `wbs_dat_i` | in | 32 | Wishbone write data |
| `wbs_adr_i` | in | 32 | Wishbone address |
| `wbs_ack_o` | out | 1 | Wishbone acknowledge |
| `wbs_dat_o` | out | 32 | Wishbone read data |
| `la_data_in` | in | 128 | Logic-analyzer probe inputs |
| `la_data_out` | out | 128 | Logic-analyzer probe outputs |
| `la_oenb` | in | 128 | Logic-analyzer output-enable (active low) |
| `io_in` | in | 38 | User GPIO inputs (`io_in[37:0]`) |
| `io_out` | out | 38 | User GPIO outputs |
| `io_oeb` | out | 38 | User GPIO output-enable (active low) |
| `analog_io` | inout | 29 | Analog I/O (unused by this design) |
| `user_clock2` | in | 1 | Second user clock (unused) |
| `user_irq` | out | 3 | User interrupt request lines |
| `vccd1`/`vssd1` | inout | 1 | User area 1 1.8 V supply / ground (USE_POWER_PINS) |

The example block consumes `io_*[37:0]` mapped down to `BITS`; upper/unused bits
are tied per `user_defines.v` GPIO POR config.
