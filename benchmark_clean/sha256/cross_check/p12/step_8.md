# Step 8 — SDC validation (OURS)

**Verdict: MATCH** (OUR SDC parses + links cleanly in OpenSTA; same period as REF)

## What ran
OpenSTA 3.1.0 sourced OUR SDC (`sha256.sdc`) against the synthesized netlist
(`synth/ours_netlist.v`) inside the tt/ss/ff STA runs (step 10). The SDC was
read, `create_clock` + all `set_input_delay`/`set_output_delay` commands applied
without syntax error, and STA produced finite WNS/TNS (i.e. constraints were
honoured, not silently dropped).

## Result
- OUR SDC: parses clean, clock 25.9 ns recognised on `clk`, IO delays bound to
  the real ports — STA returned per-corner slacks (step 10), proving the SDC is
  valid and constraint-complete.
- Earlier `remove_from_collection` syntax (unsupported in this OpenSTA build)
  was replaced with explicit per-port `set_input_delay` — the validated form.

## REF parity
REF's `sdc_check.json` reports `passed: true` with `CLOCK_PERIOD_OK
25.907 ns` and `TIMING_FOUND: 10 constraints` for sha256.sdc — same shape and
period as OURS. Both SDCs are valid; same clock target.
