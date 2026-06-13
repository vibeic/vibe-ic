# Step 4 — Simulation (golden-vector)

## What we ran
- iverilog + vvp on OUR RTL with OUR self-checking `tb_spm.v` and `vectors.hex`
  (10,013 vectors), in container iic-eda.
- Same TB+vectors run against REF RTL to confirm a shared golden.

## OUR result
```
INFO: loaded 10013 vectors
INFO: mid-computation reset recovery PASS
RESULT: PASS  (all 10013 vectors + reset tests match golden)
```
- Golden model in TB = `(x*y) mod 2^N` reassembled LSB-first; OUR DUT matches every
  vector and survives a mid-stream synchronous-reset recovery test.

## REF result
- REF RTL run against the IDENTICAL `tb_spm.v` + `vectors.hex`:
  `RESULT: PASS (all 10013 vectors + reset tests match golden)`. REF satisfies the
  SAME golden = `(x*y) mod 2^N`.
- REF's own stored sim/full-stack results (`phase2/stage1/formal/results.json`,
  `reports/phase2/gates/bit_level_full_stack.json`) also report PASS, derived from the
  same modulo-product spec (L2 §"整數編碼說明").

## Verdict: MATCH
Both DUTs pass the same 10,013-vector golden = `(x*y) mod 2^N`. MATCH.
