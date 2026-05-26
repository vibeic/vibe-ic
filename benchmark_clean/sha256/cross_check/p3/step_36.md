# Step 36 — FPGA final sign-off (recompile + on-board test)

**Verdict: PASS** (real Quartus final compile + multi-corner FPGA STA; on-board = BFM path)

## What ran
The GENERATED sha256 (in a BIST harness) was taken through a real Quartus Prime
23.1std final compile to a 3.2 MB `.sof` bitstream with multi-corner TimeQuest STA
all-pass (worst setup +5.359 ns, worst hold +0.306 ns, TNS = 0, Fmax 68.3 MHz).
101 register-interface BIST patterns assert digest == NIST golden.

No physical DE10-Lite/USB-Blaster board was attached (`device_fpga_de10lite_detect`
→ `cables:[]`), so on-board JTAG programming was not executed; the harness was
verified via RTL simulation (the BFM / pre-silicon-equivalent path the
benchmark-verify skill permits when no board is available) — stated honestly.
Evidence: `reports/hw_test.json`, `phase2/stage1/fpga/`.

## OURS vs REF
REF also did compile-to-SOF only (no on-board run); OURS is equivalent-or-better
(adds the 101-pattern self-checking BIST verification).
