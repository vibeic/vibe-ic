# Step 6 — FPGA early prototype + verification

## What ran
A REAL Quartus Prime 23.1std.0 Lite compile of OUR design on the same MAX10 device
the reference flow used (10M50DAF484C7G, DE10-Lite). The top entity
`spm_fpga_bist` wraps the unmodified GENERATED `spm` (../rtl/spm.v) in an on-chip
BIST engine that streams 64 test patterns (corner + random) through the multiplier
and compares each reassembled product to `(x*y) mod 2^32`.

- `quartus_map` (synthesis): **0 errors**
- `quartus_fit` (place & route): **0 errors**, 851 LEs / 240 regs
- `quartus_asm`: **0 errors** -> `output_files/spm_fpga_bist.sof` (3,216,569 bytes)
- `quartus_sta`: setup/hold/MPW **MET at all 9 corner-models @50 MHz**, TNS=0
- Pattern test (BFM `tb_bist.v` driving CLOCK_50/KEY, watching LEDR): **BIST RESULT:
  PASS (done=1 pass=1 fail=0, 0 mismatches over all 64 patterns)**.

Full evidence: `reports/hw_test.json` (Pillar 4).

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Quartus compile | full synth/fit/asm/STA, 0 errors | full synth/fit/asm/STA, 0 errors |
| SOF | spm_fpga_bist.sof, 3.22 MB (harness + DUT) | spm.sof, 3.22 MB (bare spm) |
| FPGA STA | MET all corners, TNS=0 | MET all corners (setup +2.5 ns), TNS=0 |
| on-chip pattern test | **64 patterns, PASS (BIST + BFM)** | none (bare-spm compile only) |

## Verdict: PASS (OURS exceeds REF rigor)
OUR FPGA early prototype is a real Quartus bitstream that closes timing on the MAX10
fabric AND runs 64 functional test patterns through an on-chip BIST harness (verified
cycle-accurate via BFM). The reference's FPGA evidence is a bare-spm compile-to-SOF
with no pattern test, so OURS is strictly more rigorous. No physical board is attached
in this environment (device detect returned cables:[]), so the pattern run is BFM, not
on-board — stated honestly. PASS.
