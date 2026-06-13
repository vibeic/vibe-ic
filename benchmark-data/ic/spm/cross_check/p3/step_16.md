# Step 16 — Clock Planning

## What ran
Compared OUR vs REF `cts/clock_plan.json` (pre-CTS clock plan / buffer strategy).

## Metrics side-by-side
| field | OURS | REF |
|---|---|---|
| tool | openroad | openroad |
| primary_clock | clk | clk |
| buf_strategy | clkbuf chain (heuristic) | clkbuf chain (heuristic) |

## Verdict: MATCH
Both designs are single-clock (`clk`), planned with the same clkbuf-chain
heuristic strategy via OpenROAD TritonCTS. Identical clock-planning intent.
The realized tree differs in size (step 18) only because of differing sink
counts (33 vs 64), which is the expected micro-arch consequence, not a planning
difference.
