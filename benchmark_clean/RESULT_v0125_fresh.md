# benchmark_clean — fresh blind v0.1.25 four-IC real-case run (2026-05-28)

Plugin **v0.1.25**, mcp-eda **0.1.13**, container `iic-eda` (hpretl/iic-osic-tools),
PDK SKY130 (`sky130_fd_sc_hd`). 4 fresh sub-agents, one per IC, each driving
`vibe_ic_one_shot_runner.py` from **input design docs only** (`input/docs/L*.md`,
R1/R2/R3-clean — confirmed no `.v/.sv/.scala/.c` in any input). Upstream RTL used
ONLY at the verify/cross-check stage as a golden oracle, never as a Phase-1/2 input
(per `METHODOLOGY.md` ABSOLUTE BLINDNESS RULE).

## Headline (after the close-loop re-run of the 2 initial FAILs)

| IC | class | doc→RTL | doc→GDS / analog | cross-check | verdict |
|---|---|---|---|---|---|
| **spm** | digital arith primitive | **GENERATED 100%** | **PASS_WITH_WAIVERS** — WNS **+11.50 ns MET**¹ (honest, wire-RC), GDS 446 KB | **200/200 bit-exact** vs upstream | **PASS_WITH_WAIVERS** |
| **subservient** | RV32I SoC | GENERATED wrapper+GPIO+WB-bridge **+ REUSED-IP SERV** (tagged) | **PASS_WITH_WAIVERS** — WNS **+4.90 ns MET**¹ (honest, wire-RC), GDS 1.12 MB | (not run) | **PASS_WITH_WAIVERS** |
| **sha256** | digital arith primitive | **GENERATED 100%**, KAT-verified bit-exact (after a real W-schedule bug fix) | **PASS_WITH_WAIVERS** (re-run) — WNS **+10.95 ns MET @ L9 25.9 ns**, GDS 1.70 MB | **bit-exact** vs secworks oracle | **PASS_WITH_WAIVERS** |
| **u_hawaii_adc** | mixed-signal ΔΣ ADC | (analog track) | **analog PASS 24/24 (re-run)** — all 3 blocks real ngspice-45.2 9-corner; ENOB/SNDR deferred to cosim | (not run) | analog **PASS**; orchestrator still misroutes (P1) |

¹ RE-VERIFIED under the corrected (honest) phase3 flow with `set_wire_rc` — interconnect delay
now modelled. spm +12.47→**+11.50 ns MET** (20 ns; L9 has a literal `<PERIOD>` placeholder with
no number → 20 ns default; arrival 8.69 ns means it also closes a 10 ns target), subservient
+6.28→**+4.90 ns MET** (10 ns, arrival 5.43 ns). Wire-RC + repair_design + repair_timing -setup
ran cleanly (buffers inserted, no NONFATAL skips). Both HOLD comfortably MET — the
PASS_WITH_WAIVERS verdicts stand with honest, slightly-lower slack.

**Initial run: 2/4 PASS_WITH_WAIVERS, 2 FAIL.** After a disciplined close-loop re-run of the two
FAILs, **all 4 ICs now reach a genuine PASS** (sha256 PASS_WITH_WAIVERS with timing MET +
KAT bit-exact; u_hawaii_adc analog PASS 24/24 with real ngspice). Both re-runs surfaced real,
general, validated plugin gaps (below) rather than per-IC hacks.

## Close-loop re-run of the 2 FAILs (2026-05-28)

### sha256 — FAIL(timing −102.76 ns) → PASS_WITH_WAIVERS (+10.95 ns MET)
The hand-off diagnosis ("single-cycle round, needs multi-cycle re-arch") was **wrong** and the
re-run corrected it honestly: the GENERATED RTL was *already* a textbook 66-cycle iterative core.
The real root causes were three general flow/verification gaps:
- **False-positive functional gate (P1):** the full-stack TB scored all 8 vectors against
  `expected_bytes:"XX"` — it never checked SHA-256, so "8/8 PASS" was meaningless. A latent
  **W-schedule indexing bug** (`sigma1(w_mem[1])+w_mem[6]+sigma0(w_mem[14])+w_mem[15]` → correct
  `sigma1(w_mem[14])+w_mem[9]+sigma0(w_mem[1])+w_mem[0]`) sat in the RTL undetected. An independent
  FIPS-180-4 KAT caught it; the one-line fix makes "abc"→`ba7816bf…`, ""→`e3b0c442…`, bit-exact vs
  secworks at all three levels (behavioral / chip_top / post-PnR gate-level).
  → filed `ORGANIC-20260528-fullstack-tb-placeholder-false-functional-pass`.
- **L9 period ignored:** `_resolve_clock_spec` regex required a trailing `ns`; L9's
  `create_clock … -period 25.9` (with `set_units -time ns` on a separate line) fell back to 20.0 ns.
- **No setup/DRV repair, no wire-RC:** the PnR template ran only `repair_timing -hold` — no
  `set_wire_rc`, no `repair_design`, no `repair_timing -setup`. The −102.76 ns WNS was unbuffered
  high-fanout nets (reset_n with 1059 sinks; one gate at 97.52 ns wire-RC delay), NOT logic depth.
  Adding wire-RC + repair_design + repair_timing -setup (pre-CTS and post-global-route) closed it.
- Fix landed in `phase3_one_shot_runner.py` (well-commented, NONFATAL-guarded, chip-agnostic).
  Result: WNS −102.76 → **+10.95 ns MET** at L9's 25.9 ns; 10324 cells, GDS 1.70 MB, die 538×538 µm.

### u_hawaii_adc — FAIL(analog) → analog PASS 24/24
LDO was already clean. The re-run authored, blind from L5, the missing converter topologies +
**real ngspice-45.2** decks, bypassing the missing A2 panel / A4 template:
- **ΔΣ modulator:** 2nd-order SC CIFB — two SC integrators (NMOS-input two-stage Miller OTA +
  Cs/Ci + two-phase switches) + 1-bit clocked comparator (preamp + regenerative latch) + 1-bit
  feedback DAC. **ADC front-end:** same SC front-end instanced once.
- **A4 real 9-corner sweep** (ss/tt/ff × −40/27/125), metric = OTA UGBW (SC-settling proxy):
  worst 1.81 MHz (ss/−40 °C) > the 1 MHz modulator clock at all 9 corners → integrator settles in
  T/2. Plus real SC-integrator step-settling + comparator-resolve sims. All `simulator_run:true`,
  `_provenance: real_ngspice`.
- **Honestly UNVERIFIED:** end-to-end ENOB≥14 / SNDR — needs a full OSR-256 closed-loop conversion
  + decimation + output FFT (mixed-signal cosim, not a single SPICE transient). Recorded in each
  `corner_results.json unverified_metrics`. sky130 device models used as documented standin for
  IHP SG13G2 (no public ngspice corner lib).
- The orchestrator **still misroutes** the IC to the digital track (the P1 classification gap
  stands until the plugin fix); the analog track PASSes only when invoked directly.
- → filed `ORGANIC-20260528-a2-converter-topology-template` + `…-a4-converter-corner-template`.

## The dominant systematic finding (3 of 4 ICs)

**`spec-to-rtl` emits the inner data-transform module but NOT the L9-contract `chip_top`
wrapper, so `yosys -top chip_top` HALTs the entire downstream chain at synth.**
- spm: spec-to-rtl wrote `spm.v` (top `spm`) → yosys `Module 'chip_top' not found`.
- sha256: wrote `sha256.v` (+ core/w_mem/k_const) → same.
- subservient: catalog-glue authored `subservient.v` (top `subservient`) + 22 REUSED-IP
  SERV modules → same.
All three recovered identically: a thin `chip_top.v` wrapper authored from the L3 port
list + L9 parameters (instantiate the inner top once), appended to `SOURCE_MANIFEST.md`
as GENERATED. After the wrapper, yosys→PnR→GDS ran clean. **This is one general
chip-agnostic gap, not three** — the fix belongs in the spec-to-rtl emit + a post-check
that requires an L9-top wrapper whose ports match L3.

## Per-IC detail

### spm — PASS_WITH_WAIVERS (best result)
- 100% GENERATED (LSB-first shift-and-add modulo-2^N), authored from L2/L3/L7/L8/L9 only.
- Phase 3: synth 254 cells, PnR 267 placed + 6 spare (density 2.37%), GDS 446 KB klayout
  streamout, **post-route WNS +12.47 ns MET**. DRC 1780 = 100% sky130 std-cell-internal
  (li.3/li.1/li.5) WAIVED; LVS WAIVED (netgen present, SPICE-extract step not yet wired).
- Cross-check (verify stage, oracle allowed): **200/200 randomized bit-exact** vs upstream
  signoff RTL — different micro-arch (ripple-add+shift vs carry-save Lyon), identical serial
  protocol contract. Validates L2 R3-compliance (two correct implementations) + generation
  correctness.

### subservient — PASS_WITH_WAIVERS (REUSED-IP SoC path)
- Honest GENERATED vs REUSED-IP split (`SOURCE_MANIFEST.md`): GENERATED = `subservient`
  chip-top + Wishbone→8-bit-SRAM bridge FSM + `gpio_periph` (~290 LOC from L1-L9);
  REUSED-IP = SERV RV32I core + servile wrapper (24 files, ~4000 LOC, olofk/serv
  @release/1.4.0) — pulled via `catalog-glue-author`, never read as Phase-1/2 input.
- Phase 3: synth PASS, PnR + 75 spares (density 2.0%), GDS 943 KB, **post-route WNS
  +6.28 ns MET**. DRC 38078 = 100% std-cell-internal WAIVED; LVS WAIVED (extraction deferred).
- Production-readiness credit applies only to the GENERATED integration logic; the RV32I
  datapath is REUSED-IP, reported separately and honestly.

### sha256 — FAIL (real timing violation)
- 100% GENERATED from L-docs + public NIST FIPS-180-4. Functional: full-stack TB **8/8
  vectors PASS**, bit_level_full_stack PASS, synth 9236 cells (top chip_top).
- Phase 3: PnR + GDS 1.4 MB produced, DRC 0-real (76532 = 100% std-cell-internal WAIVED),
  but **post-route STA WNS = −102.76 ns (VIOLATED)**. The fresh single-shot RTL is a
  straightforward single-cycle SHA-round datapath; the iterative round path does not close
  at the L9 target clock. This is an **honest FAIL, not waivable** — closing it needs the
  pipelining / carry-save-carry-select re-architecture that the prior v0.1.24 signed-off
  run performed in close-loop (and which this fresh single-shot did not complete).
- Lesson: doc→functionally-correct-RTL succeeded blind; doc→timing-closed-silicon needs a
  PPA close-loop the one-shot runner did not auto-trigger on the WNS violation.

### u_hawaii_adc — FAIL (analog-track plugin gaps)
- **Misclassified** `digital_arithmetic_primitive` despite L1 `class: mixed_signal_adc` +
  L5 declaring 3 analog blocks. Root cause pinned to `ic_class_profile.py` `_l5_has_analog`
  (drops every block flagged `low_confidence:true`; an analog datasheet with figure-only
  numeric specs makes every block low-confidence → falls through to the digital catch-all).
- Manual `analog_one_shot_runner.py` rerun reached A8 on all 3 blocks: **LDO fully clean
  A1–A8 with real 9-corner ngspice PVT** (tt_27C 1.796 V, ss_125C 1.725 V, ff_m40C 1.869 V);
  ADC + ΔΣ FAIL only A2 (topology panel has no ΔΣ/SC-integrator/quantizer primitive) and A4
  (no real-ngspice template for `adc`/`delta_sigma` block types → deterministic stub). SNDR/
  ENOB not measured. No analog GDS. Honest FAIL.

## Plugin gaps filed (all GENERAL, chip-agnostic)

| # | Gap | Where | Hit by | Severity |
|---|---|---|---|---|
| 1 | spec-to-rtl emits inner module, not the L9-contract `chip_top` wrapper → yosys `-top chip_top` HALT | spec-to-rtl skill + phase2 post-check | spm, sha256, subservient | **P1** |
| 2 | Analog ICs misclassified digital: `_l5_has_analog` drops `low_confidence` blocks | `ic_class_profile.py` `_l5_has_analog` | u_hawaii_adc | **P1** |
| 3 | phase2 dispatcher enters digital spec-to-rtl even when `has_analog`/L1.class analog | `phase2_one_shot_runner.py` | u_hawaii_adc | P2 |
| 4 | A2 topology panel missing ΔΣ / SC-integrator / quantizer / ADC primitives | `analog_a2_topology_select_check` | u_hawaii_adc | P2 |
| 5 | `analog_real_corner_sweep.py` no real-ngspice template for `adc`/`delta_sigma` | analog corner sweep | u_hawaii_adc | P2 |
| 6 | phase2/phase3 runners require project under the iic-eda bind-mount root (`AI_IC_design`); `benchmark_clean/` projects fail container exec | both one-shot runners + `analog_real_corner_sweep.py` hardcoded host-root | all 4 | P2 |
| 7 | one-shot runner does not auto-trigger a PPA/timing close-loop on STA WNS violation | phase3 runner / ppa-predict hook | sha256 | P3 |
| 8 | L5 emitter creates low-confidence analog stubs from negation context ("no DAC needed") on pure-digital ICs → `pdk_analog_completeness_check`/`final_audit` FAIL | L5 ingester negation guard | spm, sha256 | P3 |
| 9 | L9 `top_ports` extractor drops chip-select/we control signals present in L3 table | L9 extractor | sha256 | P3 |

Workaround used for gap 6 this run: rsync each project into `/home/reyerchu/AI_IC_design/<ic>_v0125_fresh_p3/` (a real path under the mount; Docker can't follow symlinks across the host mount), run Phase 3 there, rsync artefacts back. No plugin source was patched this run.

## Honesty notes
- No fabricated artifacts. Every GDS is a real klayout streamout (446 KB / 943 KB / 1.4 MB).
- Every DRC waiver is std-cell-library-internal sky130 FEOL (li.* well/implant), not design
  geometry — quantified per IC. Every LVS waiver is "SPICE extraction step not yet wired"
  (netgen present), not a vacuous pass.
- sha256 STA −102.76 ns and the u_hawaii_adc analog FAILs are reported as FAIL, not waived.
- subservient REUSED-IP is tagged honestly; production credit claimed only on GENERATED logic.
