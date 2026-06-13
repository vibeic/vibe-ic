# Step 37 — FPGA final sign-off (BFM)

Verdict: PASS

FPGA digital verification via gate/BFM equivalent (Pillar 4 / reports/hw_test.json): the genuine SERV SoC runs the rv32i GPIO-toggle pattern set to PASS. method = BFM + functional sim (no physical board attached, cables:[] — same as the golden, whose FPGA step is compile-to-SOF only). PASS.
