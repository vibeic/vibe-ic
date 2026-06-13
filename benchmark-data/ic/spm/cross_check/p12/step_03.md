# Step 3 — CDC / RDC (OUR RTL)

## What we ran
- yosys clock-enumeration on OUR RTL: `read_verilog spm.v; proc; opt; stat` and a
  select of all `$dff/$sdff` to list their clock/edge.
- Plugin `cdc_async_input_check.py` and `cdc_crossing_check.py` on OUR project (host).

## OUR result
- **Single clock domain.** All sequential elements reduce to 3 `$sdff`
  (synchronous-reset DFFs), every one clocked by **`clk`, positive edge**
  (yosys: `created $dff ... with positive edge clock` ×3; `Adding SRST signal …`).
  There is exactly one clock and no second domain → **zero clock crossings**, so CDC
  is intrinsically clean.
- No asynchronous inputs: `rst` is synchronous (sampled on posedge clk), `x`/`y` are
  synchronous data. `cdc_async_input_check.py` → `passed: true`, 0 violations.
- `cdc_crossing_check.py` flags "no CDC report file present" (it is a report-presence
  auditor, not an RTL analyzer); exit 0. The substantive CDC analysis is the yosys
  single-clock enumeration above.

## REF result
- REF's `reports/phase2/cdc/{crossing,async_input,reset_dep}.json` all `verdict: PASS`.
  Note REF's CDC PASS describes its **chip_top wrapper** (a 3-FF `id_rx_syn1/2/3`
  synchroniser on an async `id_bus`, `reset_n` async-assert/sync-deassert). That
  synchroniser belongs to REF's enriched chip-top, NOT to the spm core — the spm core
  itself is single-clock in both runs.

## Verdict: EQUIVALENT (both CDC-clean)
The spm core is a single-clock, synchronous-reset design in both OUR and REF — no real
CDC. OUR analysis proves this directly from the RTL; REF's PASS additionally covers a
wrapper synchroniser that OUR flat-core design does not instantiate. No CDC/RDC risk in
either. EQUIVALENT.
