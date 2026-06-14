# L4 — Command / Bus Protocol

## Wishbone B4 (classic single-word, pipelined ack)
- Access qualified by `valid = wbs_cyc_i & wbs_stb_i`.
- Write: when `valid & wbs_we_i`, byte lanes selected by `wbs_sel_i` update the
  count register: `wstrb = wbs_sel_i & {4{wbs_we_i}}`; `wstrb[0]→count[7:0]`,
  `wstrb[1]→count[15:8]`, etc.
- Read: `wbs_dat_o = {{(32-BITS){1'b0}}, rdata}`, where `rdata` is sampled `count`.
- Handshake: `wbs_ack_o (ready)` pulses high for one cycle after a valid access,
  then returns low.

## Logic-analyzer override protocol
- `la_write = ~la_oenb[63:64-BITS] & ~{BITS{valid}}` — when a LA lane is driven
  (oenb low) and no Wishbone access is in flight, `count <= la_write & la_input`.
- Clock override: `la_data_in[64]` when `la_oenb[64]==0`.
- Reset override: `la_data_in[65]` when `la_oenb[65]==0`.

No CRC, opcode, or multi-byte framing — this is a memory-mapped register block.
