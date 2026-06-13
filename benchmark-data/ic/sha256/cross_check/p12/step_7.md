# Step 7 — SDC constraints diff (OURS vs REF)

**Verdict: EQUIVALENT** (same clock period 25.9 ns; IO delay matches REF convention)

## What ran
Authored OUR SDC (`/home/reyerchu/AI_IC_design/_sha256_xc_p12/sta/sha256.sdc`)
from L9/L8 facts and diffed against REF's stored SDC convention
(`reports/phase2/sdc_check.json` + L8 timing_constants).

## OUR SDC
```
create_clock -name clk -period 25.9 [get_ports clk]
set_input_delay  -clock clk 2.0  (reset_n, cs, we, address*, write_data*)
set_output_delay -clock clk 2.0  (read_data*, error)
```

## REF SDC facts (from sdc_check.json + L8)
- Clock period **25.907 ns (38.6 MHz)** — same target (L9 period_ns 25.906736).
- chip_top.sdc / sha256.sdc: 10 timing constraints incl. `set_input_delay`,
  `set_output_delay`, `set_false_path`.
- L8 timing_constants: `t_input_delay = 2.0 ns`, `t_output_delay = 2.0 ns`.

## Finding
OUR clock period (25.9 ns) and IO delays (2.0 ns in / 2.0 ns out) **match the
REF SDC convention exactly**. REF additionally declares `set_false_path` entries
on its chip_top async wrapper boundary — OURS has no async boundary, so no
false-path is needed. Difference is benign and architecture-driven.

Note: REF's `SKY130.sdc` was flagged `NO_TIMING_CONSTRAINT` (clock-only) while
`chip_top.sdc`/`sha256.sdc` carried full constraints — OUR single SDC carries
clock + IO delays, equivalent to REF's `sha256.sdc`.
