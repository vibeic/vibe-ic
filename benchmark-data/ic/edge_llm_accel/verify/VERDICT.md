# edge_llm_accel — Functional Verification Verdict (V1 / V2) — ROUND 2 (post-fix re-verification)

Date: 2026-07-18 · Simulator: iverilog -g2012 (vibeic-eda container) · RTL untouched by verification

DUT: `phase2/stage1/rtl/edge_llm_accel.v` (DIM=64, NBANK=20) + `int4_systolic.v`;
SRAM: `input/pdk_local/fakeram45/fakeram45_2048x39.v` behavioral model.

**Round history.** Round 1 found **F1** (PE load path `w_out <= w` → half-rate chain: only 32
of 64 rows loaded per run, rows 32..63 retained the previous tile, even beats dropped —
demonstrated bit-true). The fix `w_out <= w_in` (full-rate chain) was applied upstream. This
round RE-VERIFIES everything on the fixed RTL: mapping re-extracted empirically, V1/V2 re-run,
plus the F1 regression case (back-to-back runs without reset) and full-64-row confirmation.

Golden models are computed **in the testbenches only** (independent software re-implementation
of the documented dataflow / the frozen re-extracted mapping in `mapping.json`) — never copied
from DUT internals. Hierarchical monitors (`load_w/w_beat/a_beat/ps_cap`) were used solely in
the extraction TB `tb_v2_map.v`; the check TB `tb_v2_top.v` is pure black-box.

## V1 — unit-level bit-true golden (int4_systolic 8×8, ACCW=20) — **PASS**

TB: `tb_v1_systolic.v` (golden updated to post-fix PE semantics `w_out <= w_in`) · Log: `v1_systolic.log`

| L7 item | Content | Result |
|---|---|---|
| V1.1 GEMM random | 108 tiles (≥100 random), K=32 vectors each, cycle-accurate golden compared **every cycle** (`===`, X-safe) | **PASS** — 56,760 comparisons, 0 mismatches |
| V1.2 extremes | all +7, all −8, alternating ±(7/−8) tiles/streams | **PASS** — bit-true, no overflow (20-bit acc) |
| orientation | after 8 pulses of beats B0..B7: **row r = B[7−r] for ALL rows** (full-rate); tile 2 **fully overwrites** tile 1 (no history) | **CONFIRMED** (0 bad, both cadences) |

## V2 — full-scale end-to-end (DIM=64, 20× fakeram45_2048x39) — **PASS** (incl. back-to-back), with residual finding F2

Extraction TB: `tb_v2_map.v` → `v2_map_extract.log` — controller schedule **unchanged** by the fix:
64 load pulses; beat p = words 8p−2..8p+5 (0 framing violations); a_beat slides 1 word/cycle
u=512..1031 (0 violations); capture u=1032; done u=1098. Mapping frozen in `mapping.json`.
Check TB: `tb_v2_top.v` → `func_directed.log`.

| Item | Content | Result |
|---|---|---|
| V2.1 random GEMM | **20 fully random W/A tiles** end-to-end (preload per L4 → start → done → readback) vs pure software golden, reset between runs; random scale/shift incl. 0 and 31; random junk in bits [38:32] | **PASS** — 64/64 bit-true on all 20 |
| V2.1 basis probes | T1 (A one-hot: window diag, **all 8 row-groups active**), T2/T3 (row 0), **T3b (row 32 LIVE — fix confirmed)**, T4 (**even beat now live**: word500 → row1 cols8-15), T5/T5b (row-63/beat-0 structure + word-0 aliasing at cols 40/48/56; words 510/511 still dropped), T6/T6b (row 62 pairing, off-by-one vanishes) — all vs hand-computed vectors | **PASS** |
| dequant directed | +32767 exact, +32768→sat, −32768 exact, −32769→sat, −1>>>4=−1 (floor), full-64-row ±saturation | **PASS** — bit-true |
| protocol | busy ≤1 cycle; done single 1-cycle pulse; busy=0 in done cycle; start-during-busy ignored (incl. its scale/shift, no restart for 1300 cycles); reset mid-run → clean re-run | **PASS** |
| V2.2 run bound | done latency **1099 cycles**, invariant across all runs | **PASS** — ≤ 4096 |
| V2.3 host access | all 20 banks, back-to-back pipelined 2-cycle reads; result layout `{7'b0,res,res}` on every readback | **PASS** |
| **F1 regression: back-to-back, NO reset** | 6-run suite (1 from reset + **5 without reset**), fully random tiles each | **PASS** — residue-aware golden **bit-true 64/64 on every run**; history-blind golden mismatches confined to cols 56..63 (1/3/8/1/7/4 columns; **0 outside**) — the deep F1 carryover is GONE |
| 64-row confirmation | T3b (row 32), T6 (row 62), T5 (row 63), T1 (rows 0..56 step 8), T12a/b (all 64 rows accumulate: acc=±3136 path) | **CONFIRMED** — all 64 array rows carry current-run weights |

## Findings (round 2)

**F1 — FIXED and regression-verified.** Full-rate chain populates all 64 rows; row r = beat 63−r;
every row overwritten each run; even beats now live. No trace of the 32-row carryover remains
(back-to-back mismatch columns are exclusively the F2 residue columns below).

**F2 — residual (small, real): beat-0 lane 7 residue → row 63, result cols 56..63.**
Mechanism (exact): the 2-cycle read-pipe skew makes beat 0 = words {−2, −1, 0..5}; the two
missing words are taken from whatever the read mux delivers in the first two S_LDW cycles.
Lane 6 (cols 48..55) is deterministic: the start branch resets `acc_bank/acc_addr` to 0, so the
in-flight idle read returns **word 0** (an alias of preloaded data). Lane 7 (cols 56..63) is the
**pre-start idle read**: after reset that is also word 0 (bank0@0), but after a completed run
S_STORE leaves `acc_bank=11, acc_addr=0x7BF`, so the idle state re-reads the previous run's
res[63] result word → row 63 cols 56..63 weights = nibbles of **{res63_prev, res63_prev}**.
Empirical proof: T35 suite — history-blind mismatches always confined to cols 56..63; golden
with the residue modeled is bit-true on all 5 no-reset runs. T5b shows the word-0 aliasing
(cols 40/48/56 mirror word 0 nibble 0). Impact: 16 of 4096 weight nibbles are aliased (8 to
word 0, 8 to residue); with **reset before each run** the design is exactly input-deterministic
(residue = word 0). Disposition options: declare it (usage contract: reset per run + ≥2 host-idle
cycles before start — as `mapping.json` does), or upstream-fix the framing (e.g. start the weight
stream 2 words early / prime the pipe before the first shift). **Not fixed here.**

**Informational:** weight words 510/511 remain unused; activation words 1022..1031 preloaded but
outside the captured window (window uses words 902..1021). Unchanged from round 1.

## Verdict

- **V1: PASS** (bit-true, 0/56,760 mismatches, post-fix chain semantics confirmed)
- **V2: PASS** — 20 random from-reset runs + 5 back-to-back no-reset runs all bit-true against
  the declared mapping; effective GEMM now spans **all 64 rows** (4080/4096 weight nibbles from
  the intended tile; 16 aliased per F2). Protocol, latency (1099 ≤ 4096), host access, layout clean.
- Declared mapping for `declaration.json`: see `mapping.json` key `declared_mapping_for_declaration_json`.

## Files

- `tb_v1_systolic.v`, `v1_systolic.log` — V1 TB (post-fix golden) + full log
- `tb_v2_map.v`, `v2_map_extract.log` — mapping extraction TB (instrumented) + round-2 log
- `tb_v2_top.v`, `func_directed.log` — V2 black-box check TB (round-2 suite incl. T35 b2b) + full log
- `mapping.json` — frozen declared mapping, round 2 (feeds declaration.json)
- `VERDICT.md` — this file
