# Step 6 — FPGA early prototype + verification report

**Verdict: PASS** (satisfied by the real FPGA build under Pillar 4)

## What ran
The FPGA early-prototype intent (does the generated RTL map to a real FPGA and
function?) is satisfied by the same real build used for Pillar 4: a Quartus
Prime 23.1std full compile (Analysis&Synthesis → Fit → Assembler → TimeQuest STA)
of a self-checking BIST harness (`sha256_bist_top.v`) wrapping the GENERATED sha256
DUT, targeting DE10-Lite MAX10 (10M50DAF484C7G) → a 3.2 MB `.sof` bitstream
(3427 LEs, 1595 regs), multi-corner FPGA STA all-pass (Fmax 68.3 MHz > 50 MHz target).

## OURS vs REF
REF (`sha256_v2_e2e`) likewise produced a compile-to-SOF only (no on-board pattern
run). OURS additionally drives 101 register-interface BIST transactions in RTL sim
(digest==NIST golden) — see `reports/hw_test.json`. Equivalent-or-better than REF.
