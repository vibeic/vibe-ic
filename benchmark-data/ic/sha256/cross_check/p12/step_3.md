# Step 3 — CDC / RDC (OURS vs REF)

**Verdict: BOTH-CLEAN** (single clock domain; no real CDC in either)

## What ran
- Structural review of clock/reset usage in OUR RTL (all 3 files).
- Comparison against REF's stored `reports/phase2/cdc/{crossing,async_input,reset_dep}.json`.

## Result
OUR design (`sha256`/`sha256_core`/`sha256_k`) is **single-clock** (`clk` only)
with one synchronous active-LOW reset (`reset_n`). Every `always @(posedge clk)`
block is in the same domain; the K ROM and read path are combinational. There
are **no clock-domain crossings and no asynchronous inputs** → CDC/RDC trivially
clean.

REF's stored CDC reports show:
- `crossing.json`: PASS — but the crossing it lists (`id_bus` external_async →
  clk_main via 3-FF `id_rx_syn{1,2,3}`) lives in REF's **`chip_top.sv`
  aid-class wrapper**, not in the SHA core. That wrapper is REF-specific
  benchmark scaffolding.
- `async_input.json`: PASS (same `id_bus` 3-FF synchroniser).
- `reset_dep.json`: PASS, "async-assert sync-deassert", reset_n.

## Finding (HONEST)
Parity holds: both are CDC-clean. OUR `sha256` has genuinely **no CDC** because
it does not include the aid-class `chip_top` wrapper (OUR top is the bare
`sha256` register block). REF's lone synchroniser is in harness logic, not the
hash datapath. Reset strategy: OURS uses **synchronous** active-LOW reset
(`if(!reset_n)` inside `posedge clk`), REF documents "async-assert sync-deassert"
for its chip_top — different reset disciplines, but both clean and both
active-LOW. No dedicated CDC tool (e.g. SpyGlass-CDC) was available; analysis is
structural — sufficient for a single-clock design.
