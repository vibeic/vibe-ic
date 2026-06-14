# L2 — Architecture

## Hierarchy
```
user_project_wrapper          (Caravel-fixed top; power pins + 128b LA + 38b GPIO + Wishbone)
└── user_proj_example #(BITS)  (example user block)
    └── counter #(BITS)        (the actual sequential logic)
```

## Functional description
`user_proj_example` is a `BITS`-wide (default 32 in the wrapper instantiation,
parameter default 16) free-running up-counter with three control/observation paths:

1. **Wishbone (B4 classic, single-word):** the management SoC can read the current
   count (`wbs_dat_o`) and write a new count value (`wbs_dat_i`, byte-strobed via
   `wbs_sel_i`). `valid = wbs_cyc_i & wbs_stb_i`; `ready` (`wbs_ack_o`) asserts one
   cycle after a valid access.
2. **Logic Analyzer (128-bit):** `la_data_in`/`la_oenb` can override the clock
   (`la_data_in[64]`), reset (`la_data_in[65]`), and directly force counter bits
   (`la_write = ~la_oenb[...] & ~valid`); `la_data_out` mirrors the count.
3. **GPIO:** `io_out = count` (digital output only); `io_oeb` driven from reset.

## Clocking / reset
- Clock source muxed: `clk = la_oenb[64] ? wb_clk_i : la_data_in[64]`.
- Reset source muxed: `rst = la_oenb[65] ? wb_rst_i : la_data_in[65]`.
- Single clock domain, synchronous active-high reset.

## IRQ
`irq[2:0] = 3'b000` (unused).
