# caravel_user_project — Benchmark IC #7 — Round-7 RESULT (LIVE, appended incrementally)

> Robustness note: round-6 lost its report to a session cutoff. This file is
> created EARLY (right after setup) and APPENDED after each major Phase-3 step so
> partial results survive a cutoff.

## Run identity
- **Plugin under test:** PUBLIC tree **v1.0.51** (`/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`),
  commit `25824028` = "v1.0.51 — for #686 (P0) + #684 + #685 + #687: caravel round-6 Phase-3 backend backlog".
  All four round-6 fixes confirmed present in the runner tree BEFORE running.
- **Project:** `_bench7_caravel_v1034_cleanroom/caravel_r7` (fresh clean-room, input-only seed copied from `caravel/input`).
- **Shape:** A/D (full runner, SoC integration). Blind: no reference GDS, no spm_pilot, no host scorer.
- **Round-6 baseline (to beat):** phase2 PASS_WITH_WAIVERS; phase3 synth→pnr→gds→drc PASS, **HALTED at LVS** (netgen FAIL, io_out[N]↔la_data_out[N]); DEF COMPONENTS=940,896; GDS ~2.07 GB; flow_compliance HUNG (>240s).

## Field-verify targets (round-6 fixes)
- **#684** fill density cap on sparse die — expect routed DEF COMPONENTS ~hundreds (NOT ~940,896); GDS MB-scale (NOT ~2GB).
- **#685** LVS port-recovery for shared-internal-net ports — expect LVS no longer FAILs on io_out[N]↔la_data_out[M].
- **#686** flow_compliance no longer hangs on large GDS — expect --strict COMPLETES with a verdict.
- **#687** via techlef container-cat — expect no `/foss/...nom.tlef No such file` host-path skip.

---

## Progress log

### [SETUP] DONE
- caravel_r7 seeded input-only. Runner v1.0.51 confirmed. Launching full flow.

### [PHASE1+2] DONE
- Run 1: phase1 PASS; phase2 FAIL — `step_rtl_gen` WAIVED (class `bus_peripheral`, rtl_gen=null), ECO loop FAIL "rtl/ missing" (expected RTL recovery trigger).
- RTL recovery: authored 4 synthesizable sources (defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v) into `phase2/stage1/rtl/`; uprj_netlists.v deliberately NOT staged.
- Run 2: phase1 PASS; **yosys_synth PASS** (cells=189, synth_top=user_project_wrapper, frontend=read_verilog_v2005). Chain drove into Phase 3.

### [PHASE3] PnR FAIL — NEW failure mode unmasked by #684+#687
- **#684 fill cap CONFIRMED FIRING (RESOLVED, see below):** openroad.log records
  `SPARSE_DIE_TAPCELL_SKIPPED: core_util=0.022% < 5.0%`, effective util 0.000 / GPL 0.025%.
  No 940k filler flood — the fill cap works as designed.
- **But PnR now FAILs at GLOBAL ROUTE (NEW, was masked in round-6):**
  ```
  [ERROR ODB-0137] In argument -clock_layers, min routing layer is greater than max routing layer.
  SET_ROUTING_LAYERS_NONFATAL: ODB-0137
  [ERROR GRT-0229] Vertical edge usage exceeds the maximum allowed. (0, 339) usage=1 limit=0
  Error: pnr.tcl, 286 GRT-0229
  ```
- phase3_one_shot.json: synth PASS, **pnr FAIL**, drc SKIP (GDS missing), lvs SKIP (upstream pnr FAIL), canonicalize PASS.

#### ROOT CAUSE (chip-AGNOSTIC plugin regression — GAP CANDIDATE #1, HIGH)
pnr.tcl line 261 emits `set_routing_layers -signal met1-met1 -clock met1-met1`
(the v1.6.38 single-cut-via restriction). Restricting **signal** routing to a
single layer makes global routing impossible → GRT-0229 usage=1/limit=0.

The restriction came from `_pdk_via_analyzer.routing_layer_upper_bound(sky130 nom.tlef) = 1`
(verified directly). It is WRONG: sky130A has met1-met5 (mtotal=5) and a single-cut
via at every transition. The analyzer's `cut_layers_with_single_cut(sky130)` returns
`{VIA2,VIA3,VIA4}` but MISSES VIA1 (sky130's met1↔met2 cut is named `via`/`mcon`,
not `VIA1`). So indices={2,3,4}; the gap-walk `n=1; while n in indices` returns 1
on the first miss → routing_upper=1 → met1-met1 → routing dies.

**This is the #687 fix's side effect:** #687 made the analyzer actually FIRE on
sky130A (round-6 it was host-path FileNotFound-skipped, so sky130A routed fine with
2GB-junk GDS). Now that it fires, the wrong met1-met1 restriction breaks sky130A —
the exact PDK the v1.6.38 comment claims is "a no-op there." Chip-AGNOSTIC: hits the
entire sky130 PDK class (the most common open PDK). FILE-WORTHY.

### [field-verify so far]
- #684 = RESOLVED (fill cap fires; no flood).
- #687 = PARTIALLY RESOLVED but REGRESSION — the host-path skip is gone (analyzer now
  reads the techlef), BUT the analyzer's sky130 cut-naming blind spot now emits a
  routing-breaking restriction. Net effect on sky130A: PnR regressed PASS→FAIL.
- #685 (LVS port-recovery) = RESOLVED (unit-verified). In-flow LVS NOT reached
  (PnR FAILs first), but `_v0_3_14_detect_top_port_aliases` directly verified on a
  synthetic io_out[N]/la_data_out[M] shared-internal-net DEF: recovers
  `la_data_out[10]→io_out[5]`, `la_data_out[11]→io_out[6]`; §4.05 negative holds
  (single-port net NOT aliased). This is exactly the round-6 LVS mismatch.
- #686 (flow_compliance hang) = RESOLVED. (a) live SOLE-ACCEPTANCE run on caravel_r7
  completed in **9.31s**, RSS 115MB, `Overall: FAIL` — no hang. (b) direct unit test:
  `spare_cell_preservation_check._read_text` on a 300MB binary GDS-like file returned
  0 chars in 0.00s (binary-sniff skip fired, did NOT slurp). Both confirm the fix.

### [DIAGNOSTIC EXPERIMENT — proves GAP #1 root cause + recovers #684 in-flow evidence]
Copied pnr.tcl → pnr_diag.tcl in the RUN dir (NOT a plugin edit), replaced only the
single line `set_routing_layers -signal met1-met1 -clock met1-met1` →
`met1-met5 -clock met1-met5`, re-ran OpenROAD in the container.
**Result: PnR completed EXIT=0** — global route OK, detailed route across met1-met5
(li1=858/met1=756/met2=482/met3=239 guide regions), antenna 34→0 (289 diodes), design
area 3470 um². This PROVES the GRT-0229 is caused solely by the met1-met1 restriction.

**#684 fresh in-flow evidence (from the recovered diag route):**
- routed DEF COMPONENTS = **648** (placed=329) vs round-6 **940,896** — fill cap removed ~940k filler cells.
- diag routed DEF = 37.5 MB; routing-only GDS (klayout def2gds, cells as dummy macros) = **29.6 MB**.
  vs round-6 final GDS = **2,074,657,830 bytes (~2.07 GB)**. MB-scale confirmed; ~70x smaller.
  (#684 SPARSE_DIE_FILL_SKIPPED + SPARSE_DIE_TAPCELL_SKIPPED both fire at core_util ~0.03%.)


---

## FINAL — SOLE ACCEPTANCE CRITERION (verbatim)
```
python3 .../flow_compliance_check.py _bench7_caravel_v1034_cleanroom/caravel_r7 --strict
Steps: 59 total (11/31 executed PASS, 3 DEFERRED via waiver)
  PASS=10  FAIL=5  MISSING=15 (15 blocked-by-upstream of step 7)  WAIVED-DEFERRED=3  SKIPPED=25  VACUOUS-PASS=1
Overall: FAIL  (strict=True)        wall-time 9.31s, RSS 115 MB
```
- flow_compliance's first mid-chain blocker: **Step 7 (Constraint setup / PVT matrix)**
  `pvt_matrix_check` FAIL (multi-corner PVT matrix = open-tool cap-gap, same class as round-6's
  STA-basis note) + **P0 doc-depth FAIL** (`l_doc_structured_field_count_check`, 3 L docs short of typed fields).
- The runner's own phase3_one_shot.json blocker: **pnr FAIL (GRT-0229)** → lvs SKIP.

## How far did the chain reach? (vs round-6)
| | Round-6 (v1.0.47, fixes ABSENT) | Round-7 (v1.0.51, fixes PRESENT) |
|---|---|---|
| phase2 | PASS_WITH_WAIVERS | PASS_WITH_WAIVERS |
| synth | PASS | PASS (189 cells) |
| pnr | PASS* (*false — 940,896-cell fill flood) | **FAIL (GRT-0229, sparse-die routing)** |
| gds | PASS (2.07 GB junk) | not reached |
| drc | PASS | not reached (SKIP, no GDS) |
| **lvs** | **FAIL** (io_out↔la_data_out) | not reached (SKIP, upstream pnr FAIL) |
| flow_compliance | HUNG >240s | **9.31s, Overall: FAIL** |

Round-7 halts EARLIER (PnR) than round-6 (LVS) — but this is an HONEST regression in
reach, not a quality regression: round-6's PnR "PASS" was a false pass built on a 2GB
fill flood. Once #684 removes the flood, the truthful sparse-die routing problem
(GRT-0229) surfaces. **Did LVS pass?** No (not reached). **Sign-off / tapeout?** No.

## A) Round-6 fix verdicts (fresh evidence)
| Fix | Verdict | Evidence (THIS run) |
|---|---|---|
| **#684** fill cap | **RESOLVED** | routed DEF COMPONENTS=**648** (vs r6 940,896); SPARSE_DIE_FILL/TAPCELL_SKIPPED fire at core_util≈0.03%; routing-only GDS=29.6 MB (vs r6 2,074,657,830 B / 2.07 GB). MB-scale ✓ |
| **#685** LVS port-recovery | **RESOLVED (unit)** | `_v0_3_14_detect_top_port_aliases` on synthetic io_out[N]/la_data_out[M] shared-net DEF recovers `la_data_out[10]→io_out[5]`, `la_data_out[11]→io_out[6]`; §4.05 single-port net NOT aliased. In-flow LVS blocked behind GAP#1 (PnR). |
| **#686** flow_compliance hang | **RESOLVED** | live --strict = 9.31s / 115 MB / verdict emitted (no hang, was >240s). Unit: `_read_text` on 300 MB binary GDS → 0 chars in 0.00s (binary-sniff skip). |
| **#687** via techlef container-cat | **RESOLVED (host-path) but UNMASKS GAP#1** | analyzer now READS the techlef (pnr.tcl line 261 `set_routing_layers -signal met1-met1` IS emitted = analyzer fired; round-6 it was FileNotFound-skipped so this line was absent). No `/foss…nom.tlef No such file` skip. BUT firing exposes the wrong restriction → GAP#1. |

## C) NEW chip-AGNOSTIC file-worthy gap (ranked)
### GAP #1 (HIGH, file-worthy) — sky130 single-cut-via analyzer false-positive collapses signal routing to met1, killing global route
- **Symptom:** `[ERROR GRT-0229] Vertical edge usage exceeds the maximum allowed. (0, 339) usage=1 limit=0` at pnr.tcl line 286 (global_route). Preceded by `[ERROR ODB-0137] -clock_layers min > max`.
- **Root cause (verified directly):** `_pdk_via_analyzer.routing_layer_upper_bound(sky130A nom.tlef) = 1`. sky130A has mtotal=5 met layers and a single-cut via at every transition, so it should be `None`/5 (no restriction). The analyzer's `cut_layers_with_single_cut(sky130)` returns `{VIA2,VIA3,VIA4}` but MISSES **VIA1** (sky130's met1↔met2 cut is named `via`/`mcon`, not `VIA1`). With `indices={2,3,4}`, the gap-walk `n=1; while n in indices: n+=1` returns **1** on the first miss → `routing_upper=1 < mtotal=5` → runner emits `set_routing_layers -signal met1-met1 -clock met1-met1` → single-layer signal routing → GRT-0229.
- **Proof:** diagnostic re-run with only `met1-met1`→`met1-met5` makes PnR complete EXIT=0 (global+detailed route OK across met1-met5, antenna 34→0, design area 3470 um²). The single line IS the whole blocker.
- **Why #687-coupled:** #687 made the analyzer FIRE on sky130A (was host-path FileNotFound-skipped → no restriction → sky130A routed). Now firing, it emits a routing-breaking restriction on the exact PDK the v1.6.38 comment claims is "a no-op there." Regression PASS→FAIL on sky130A.
- **Chip-AGNOSTIC:** hits the entire sky130 PDK class (most common open PDK), any design. The fix is in the analyzer's cut-layer naming recognition / the empty-indices guard (empty/low VIA-index set must return None = no restriction, never a degenerate met1-met1), NOT chip-specific. **FILE-WORTHY.**
- **Suggested fix direction (for the Core Agent):** (a) `routing_layer_upper_bound` must return `None` (not 1) when the recognized single-cut index set does not include index 1 / is sparse, since "restrict to met1 only" is never a valid routing range; (b) `cut_layers_with_single_cut` must recognize sky130 cut naming (`via`/`mcon`/`viaN` + `M{n}M{n+1}_PR` via-macro form) so VIA1 coverage is detected; (c) floor any emitted `set_routing_layers -signal` range at ≥ met1-met2 (a single signal layer can never global-route).

## D) Environment-only blockers (NOT plugin gaps — separated)
- **Step 7 PVT-matrix / multi-corner STA** (`pvt_matrix_check` FAIL) — open-tool cap-gap (`cap:` flagged), not a chip-agnostic plugin bug; same class as round-6's STA-basis note.
- **FPGA early-proto + final sign-off** (Steps 6/39) — ENV_UNAVAILABLE (no DE10 board / no Quartus on host); already a sanctioned waiver (ticket fpga-board-prototype-capgap-v1.0.18).
- **DFT scan/ATPG, post-DFT opt, LEC** (Steps 11/12/13) — `cap:` platform gaps (#430), not new.
- **P0 doc-depth FAIL** (`l_doc_structured_field_count_check`, 3 L docs) — a phase1 ingestion depth issue independent of the Phase-3 work; pre-existing class, NOT a round-7 backend gap. Not re-filed (not the round-7 focus; tracked separately under phase1 coverage).

## Already field-verified (NOT re-filed): #643-652, #661, #662, #673-677, and now #684/#686.

## Convergence status
**NOT converged.** #684 + #686 RESOLVED (fresh in-flow + unit evidence). #685 RESOLVED at
unit level (in-flow LVS blocked behind GAP#1). #687 host-path fix RESOLVED but its firing
unmasks GAP#1. The chain moved from "false-PASS PnR + LVS FAIL on a 2GB junk GDS" (round-6)
to "honest sparse-die routing FAIL at PnR" (round-7) — a TRUTHFUL state, with one clean new
chip-AGNOSTIC gap (GAP#1, the sky130 single-cut-via analyzer false-positive) as the next loop
iteration. Per role rules: captured + reported only; NO GitHub issue filed, NO plugin edit.
