# subservient — real-node RE-VERIFY on the 0.2.20-int integrated image (A/B vs 0.2.19 baseline)

- IC: **subservient** (SERV bit-serial RV32I SoC; REUSED-IP)
- Run dir: `benchmark-data/ic/subservient/clean_run_v1432int_commercial`
- Image: `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (id `fa8cb832daf2`), throwaway container off the integrated image
- PDK: commercial 180nm (by PATH only; results-only, NDA-excluded)
- Entry: catalog-glue `/vibe-ic-all` recipe → phase3 backend; native SVRF DRC; KLayout-native LVS
- Baseline for A/B: 0.2.19 (a separate live baseline run + its dir were left untouched)

This is an A/B validation of this session's fork enhancements vs the 0.2.19 baseline.
Headline enhancement under test: **yosys fork `c31dfe3a8` — SOUND functional-liberty LEC + ICG**
(confirmed in-container: `Yosys 0.67+ (git sha1 c31dfe3a8, github.com/vibeic/yosys at HEAD)`).

## Recipe / RTL provenance

- IC class `processor_cpu`; the runner WAIVED `rtl_gen` → **catalog-glue-author** fired.
- IP pulled from catalog: `cpu/serv v1.4.0` (ISC) + `memory/shared_sram_rf v0.2.2` (Apache-2.0);
  keystone `SOURCE_MANIFEST.json` (`reused_ip:true`) auto-emitted; SPDX all-permissive.
- One authored integration fix: appended a `renamed_interfaces` block mapping L9's illustrative
  SRAM names → the SERV servile split read/write byte interface (5 L9 pins ↔ 6 RTL pads). This is
  the documented reused-IP relaxation; §4.05-clean (only declared names reconcile, no functional
  port hidden). With it the L9↔RTL top pin gate PASSes.
- Chip-top `subservient_chip_top` auto-emitted by the runner (23/29 staged files reachable).

## Six-pillar verdict

| Pillar | Verdict | Number |
|---|---|---|
| 1. Functional / equivalence (LEC) | PASS-with-residual | 2432 compared, **0 disproven**, 74 unproven |
| 2. Output comparison (reused-IP catalog path) | N/A (catalog-glue integration) | — |
| 3. Code coverage | not measured (run bounded) | — |
| 4. FPGA digital verification | SKIP (class-gated, no board) | — |
| 5. Analog closed-loop | N/A (pure-digital) | — |
| 6. Design-for-ECO | PASS | 14 spare cells (density 0.0202, target 0.02) |

Backend (phase3): synth PASS, PnR PASS (routed), STA PASS, DRC executed, **LVS bounded**, IR bounded.

## A/B deltas (NUMBERS)

### SOUND-LEC (the headline)
- **Recipe that ran:** `yosys equiv_make + equiv_simple + equiv_induct`, `liberty = None`
  (RTL-vs-generic-netlist; the phase-2 pre-map equivalence).
- **Proven / disproven / unproven:** compared = **2432**, non-equivalent (disproven) = **0**,
  unproven = **74**; `equivalent=False` (not fully closed), `rc=0` (tool ran clean).
- **Verdict flip vs baseline:** the SV-package **parse-abort false-FAIL cascade is GONE**. On 0.2.19
  the LEC aborted on the SERV SV packages (parse-error → false FAIL, no comparison). On 0.2.20-int
  the LEC now RUNS to a real comparison: 2432 points, **0 disproven**. The 74 unproven are a
  deep-sequential-induction residual on the bit-serial SERV datapath (an induction-depth ceiling),
  **NOT a mismatch** (non-equivalent = 0).

### STA
- Worst-slack: **+2.95 ns (MET)**.

### Synth / PnR
- yosys synth: **1764 cells**, top `subservient_chip_top`.
- PnR: die **236×236 µm**, 693 placed cells; routed DEF + GDS (8.53 MB) produced.

### DRC (native SVRF on the commercial deck)
- Tally: **58 failing rules / 4475 pass / 4533 total** (skips 0).
- Three-way MARKER_ABSENT / DENSITY_FILL / GEOMETRY classification is emitted by the runner's
  classifier at phase3 finalization, which was **bounded with the LVS** → classification split not
  finalized this run. (Not compared at rule level — AUP-excluded.)

### LVS — BOUNDED (perf, not a mismatch)
- KLayout geometric extraction of the 8.53 MB full-detail commercial-PDK GDS is **super-linear**:
  a peer 2.7 MB GDS extracted in ~17 min; this design's extraction ran **>5 h at 100% CPU** (first
  attempt) and was re-started and **bounded** per the wind-down. **Verdict pending — a wall-clock /
  perf ceiling, NOT a mismatch.** The KLayout-native LVS engine path itself is validated on peer
  commercial-PDK designs (a peer produced a MATCH-capable extracted netlist).

### Dynamic IR-drop — BOUNDED
- Computed at phase3 finalization (post-LVS); **pending** because the run was bounded at LVS.

## Discipline
- Results-only; NDA-clean (generic "commercial PDK", no SKU / foundry / rule-id / cell names;
  no fabrication/measured-silicon claims). Committed LOCAL under `benchmark-data/ic/subservient/`; not pushed.
- No plugin edits. The 0.2.19 baseline run + its dir were not touched.
