# Step 19 — CTS (clock-tree depth / skew / buffer count)

## What ran
Compared OUR vs REF `cts/clock_tree.rpt` (TritonCTS-extracted report).

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Clock net | clk (1 net) | clk (1 net) |
| Sinks | 33 | 64 |
| Clock buffers created | 5 | 9 |
| Clock nets created | 5 | 9 |
| Root buffer | clkbuf_16 | clkbuf_16 |
| Sink buffer | clkbuf_4 | clkbuf_4 |
| H-tree max level | 2 | 3 |
| Path depth (min-max) | 2 - 2 | 2 - 2 |
| Avg sink wire length | 118.12 µm | 145.26 µm |
| Dummy loads inserted | 3 | 7 |
| Hold after CTS | No hold violations (RSZ-0033) | No hold violations (RSZ-0033) |

## Verdict: IN-RANGE / BOTH-CLEAN
Same CTS engine, root/sink buffer cells, and balanced path depth (2-2 → low skew
by construction). OUR tree is smaller (5 buffers, 33 sinks, H-tree level 2) vs
REF (9 buffers, 64 sinks, level 3) — directly proportional to the smaller
flop/sink count of the carry-save micro-arch. Both report no post-CTS hold
violations. Buffer/level counts scale sensibly with sink count → IN-RANGE.
