# V2 extended soak — 8 parallel seeds

Same tb_v2_top.v with 8 distinct RNG seeds (32'hA5EED001..8), run concurrently
(iverilog -g2012 / vvp). Each seed executes the FULL V2 suite: 20 random 64x64
W/A tiles end-to-end bit-true, dequant saturation directed cases, protocol
checks (start/busy/done, start-ignored-while-busy, reset-mid-run), 20-bank
pipelined host access, and the 6-run back-to-back no-reset suite
(residue-aware golden).

Result: 8/8 seeds — V2 RESULT: ALL TESTS PASS (56 PASS checks each, 0
mismatches). Combined random-tile coverage across the campaign: 180 distinct
random 64x64 tiles bit-true (20 original + 8x20 soak).
