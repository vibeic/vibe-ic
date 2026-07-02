# Vibe-IC — Foundry-Qualified Tape-out Sign-off: complete gap survey + roadmap

> **Goal (owner directive):** Vibe-IC's endpoint is NOT "reached a GDSII" — it is a
> **foundry-qualified tape-out sign-off**. This document is the complete, honest survey of
> everything still missing between the current OSS-flow GDS and a genuine tapeout, produced by a
> 5-way parallel read-only survey of the actual plugin code (2026-07-02). Each item is graded
> P0 (tapeout-blocker) / P1 / P2 with what to build.

## ── EXECUTION LOG (P0 build-out in progress) ──
- ✅ **P0#1 — MCP DRC vacuous-PASS stub KILLED** (v1.2.75, pushed): `eda_drc_klayout`
  gf180/sky130 now runs the PDK's real `*.lydrc` sign-off deck + honest-fail-on-no-deck; the
  false DRC-clean surface is gone. +3 source-scan guards.
- ✅ **P0 timing rigor — flat-OCV derate + recovery/removal/MPW** (committed): SPEF STA emits
  `set_timing_derate` + `report_check_types -recovery -removal -min_pulse_width`; new
  `sta_signoff_rigor_check.py` FAILs an optimistic (MET-but-no-derate) report. +7 tests.
- ✅ **P0#2 parser — `mpw_precheck_result_gate.py`** (committed): consumes a completed precheck
  rundir → PASS/FAIL/INCOMPLETE/SKIPPED; §4.05 absent-rundir → SKIPPED. +17 tests. (LIVE driver
  half pending.)
- ✅ **P0#3 XOR — `xor_layout_check.py`** (committed): computed layer-by-layer KLayout XOR with an
  explicit macro allow-list waiver — replaces the hardcoded 2/7 floor. §4.05 out-of-macro delta
  still FAILs. +22 tests. (LIVE needs real assembled+golden GDS.)
- ✅ **P0 EM — `em_current_density_check.py`** (committed): real J-vs-Jmax from PDK tech LEF,
  replaces the decap-count proxy; §4.05 absent report/Jmax → SKIPPED. +12 tests. LIVE-smoked on
  spm's real 82k-segment CSV.
- ✅ **P0 MBIST — `mbist_wrapper_gen.py`** (v1.2.76): detect RAM + emit March C- wrapper + gate;
  §4.05 no-RAM→N/A, RAM-no-wrapper→FAIL; iverilog functional proof (correct→bist_fail=0,
  stuck-at→bist_fail=1). +14 tests.
- ✅ **P0 LVS tapeout tier — `lvs_tapeout_signoff_check.py`** (v1.2.77, pushed): stops crediting
  POWER_PIN_ONLY as a genuine match at the tapeout tier (GENUINE_MATCH→PASS,
  POWER_PIN_ONLY→WAIVED_PENDING_POWER_AWARE not-a-pass, SIGNAL_NET→FAIL); triage waiver
  untouched, zero regression. +7 tests. **ROOT-FIX follow-up (needs live netgen):** emit a
  power-aware gate netlist (VPWR/VGND ports + PG connectivity) so netgen reaches a GENUINE match.

### Batch summary (v1.2.75 → v1.2.77, all pushed)
8 program-first tapeout-signoff gates landed — MCP-DRC-stub-kill, STA-OCV-rigor, mpw-precheck
parser, XOR (replaces hardcoded 2/7 floor), EM-Jmax (replaces decap proxy), MBIST, LVS-tapeout-tier
— each chip-AGNOSTIC, §4.05-verified, gatekeeper MERGE_OK. **These are the deterministic building
blocks; each carries an honest "LIVE validation pending" where a real Docker run is still needed.**

### ── LIVE-INTEGRATION RESULTS (v1.2.78, all 3 live-run on real Docker/tools) ──
The three heavy live P0s ran on REAL tools (3 dedicated worktrees + containers). Honest outcomes:

- ✅ **mpw-precheck DRIVER — LIVE-RAN THE REAL SHUTTLE PRECHECK** (`mpw_precheck_driver.py`). The
  `efabless/mpw_precheck:latest` image (6.66 GB) IS present, and a full real Caravel project +
  sky130A exist. The driver ran end-to-end → **5/7 checks PASS live** (License/Makefile/Default/
  Documentation/GPIO-Defines), **2/7 FAIL** (Consistency + XOR) = the blackbox hard-macro floor,
  now **COMPUTED LIVE** (not the hardcoded 2/7 constant). §4.05 honest: image-missing→BLOCKED, real
  fail-logs→FAIL, never fabricated. **This is a milestone — the plugin can now execute the Efabless
  shuttle gate for real.**
- ✅ **Caravel XOR gate — LIVE-VALIDATED on real klayout** (`caravel_wrapper_harden_driver.py` +
  B1/B3/B4 wiring). XOR ran end-to-end (zero-delta→PASS, in-macro+allowlist→PASS_WITH_WAIVER,
  outside-macro→FAIL, merge preserved top=caravel). **The live run caught 2 real bugs the mocks
  could not** (a `pya.Region` copy-ctor crash that only fires on a non-zero delta; a Path coercion)
  — proof that live validation is load-bearing. The real caravel HARDEN is **BLOCKED on sky130A PDK
  absent** (image + fixed-outline config.json present; PDK the sole missing prereq) — honest, no
  DRT-0302 mislabel.
- ⚑ **LVS power-aware emitter — netgen-PROVEN, but spm blocked on the EXTRACTION side**
  (`lvs_power_aware_netlist_emit.py`). Controlled real-netgen proof: the power-aware netlist vs a
  CLEAN-rail layout → **GENUINE MATCH, all 4 rails verified**. BUT spm's phase-3 DEF-direct
  extraction **collapses the 4 power nets onto ~2 substrate nodes** (reproduced by fresh
  re-extraction → inherent to the method). So the LVS root fix is **2 parts**: (1) power-aware
  netlist [DONE, proven] + (2) a **power-aware EXTRACTION that keeps VPWR/VGND separated** [the
  remaining blocker]. The wiring is monotonic (spm stays PASS, no regression). aes's 517 rows are
  top-level SIGNAL ports collapsed onto VSUBS — a **port-promotion extraction defect, NOT power**;
  correctly stays SIGNAL_NET_MISMATCH.

### What a REAL green sky130 (Efabless) submission still needs — the honest short list
The plugin logic is now largely in place (it runs the real precheck, the real XOR, the proven LVS
emitter). The remaining blockers are **infrastructure + data + one extraction gap**, not plugin logic:
1. **A full sky130A PDK install** (`PDK_ROOT` → built sky130A) — blocks BOTH the caravel harden AND
   the full precheck ladder (magic_drc / klayout_feol-beol-offgrid / lvs / oeb). The precheck host
   here has only a partial volare PDK (`SKY130A: None`).
2. **Power-aware EXTRACTION** (LVS root fix part 2/2) — keep VPWR/VGND separated through
   `extract`/`ext2spice` so the proven emitter reaches a genuine match on a real design.
3. **Golden full-chip `caravel.gds`** + the **pre-hardened `user_proj_example.gds/.lef` macro** +
   the **fixed pin_order.cfg / user_project_wrapper.def** — the XOR reference + harden inputs.
4. **OR** the chipignite **signoff waivers** for the 2/7 blackbox floor (step_c4 already auto-emits
   these when the fail-set == {Consistency, XOR}).

### ── "cont" BATCH DONE (v1.2.79) ──
- ✅ **LVS ROOT FIX COMPLETE — spm has a GENUINE power-verified match, LIVE-proven.** Part 2/2
  (power-aware EXTRACTION: `set SUB <ground-rail>` + DEF-seeded `label <power-rail>` + well-tie)
  turned spm's real netgen from power-blind (VSUBS/_438_) to **VGND|VGND, VPWR|VPWR, "Circuits
  match uniquely"** (real Magic + netgen, 201,441 instances). classify=MATCH,
  lvs_tapeout_signoff_check=GENUINE_MATCH. The LVS sign-off is now REAL, not a POWER_PIN_ONLY
  waiver. This closes the single load-bearing LVS gap.
- ✅ **The 11 gates are now WIRED into the release ladder** (`signoff_ladder_run --mode tapeout`):
  EM=real J-vs-Jmax (decap proxy gone), LVS=genuine-match-required (POWER_PIN_ONLY non-releasing),
  +STA-rigor/MBIST/mpw-precheck/XOR tiers, new NOT_RELEASED verdict + `released` flag + `--strict`.
  §4.05: POWER_PIN_ONLY at tapeout mode no longer releases; triage mode unchanged.
- ✅ **Dynamic (transient) IR-drop gate** (`dynamic_ir_drop_check.py`) + **per-layer metal-density
  gate** (`metal_layer_density_check.py`, replaces the row-util axis). Deterministic verdict gates;
  §4.05 absent→FAIL. (Producing the reports — phase3 emission of a transient-IR run + a real
  per-layer KLayout metal-fill/density pass — is the remaining emission-side follow-up.)

## ── CAMPAIGN STATE (v1.2.75 → v1.2.79) ──
**~15 program-first tapeout-signoff deliverables landed**, all chip-AGNOSTIC, §4.05-verified,
gatekeeper MERGE_OK, pushed; the heavy ones LIVE-run on real Docker/tools. The plugin now: runs the
real Efabless shuttle precheck (5/7 live), runs the real XOR on real klayout, and reaches a GENUINE
LVS match on real spm. **The path to a real green sky130 submission is now bounded and mostly
infrastructure/data, not plugin-logic:**
1. A full sky130A PDK install (blocks the caravel harden + the full precheck ladder).
2. Golden full-chip `caravel.gds` + the pre-hardened `user_proj_example` macro (XOR + harden inputs),
   OR the chipignite 2/7 blackbox waivers (auto-emitted).
3. Emission-side follow-ups (not gates): a transient-IR PSM/DVD run + a real per-layer KLayout
   metal-fill/density pass to feed the two new deterministic gates.

### ── P1 DEPTH + FINAL INTEGRATION DONE (v1.2.80 → v1.2.81) ──
- ✅ **STA depth (v1.2.80, LIVE on spm):** multi-corner min/nom/max SPEF (setup@max-RC / hold@min-RC),
  AOCV/POCV ingest (flat-OCV fallback — open PDK ships no AOCV, disclosed), REAL SI delta-delay
  verdict (computed, not forced-0), post-layout LEC (synth≡routed 286/286 PROVEN).
- ✅ **DFT depth (v1.2.80):** ATPG floor 80%→95% (to 98), transition-fault mechanism (OSS engine is
  stuck-at-only → engine_limited honestly documented, never fabricated), BSDL + boundary-scan.
- ✅ **Reliability (v1.2.80):** aging-derate STA gate + thermal power-density screen (open PDK lacks
  aging Liberty / a thermal solver → honest SKIP, mechanism ready).
- ✅ **RELEASE LADDER COMPLETE (v1.2.81):** all 17 gates wired into `signoff_ladder_run --mode
  tapeout`; phase3 emits their reports. LIVE: per-layer metal-density = REAL KLayout (met1=13% →
  FAILs the CMP min → the Efabless met_min_ca_density fix); aging-STA = REAL OpenSTA (fresh 7.49 →
  aged 7.45). HONEST: thermal SKIPs (power not numerically computed), dynamic-IR is BLOCKED (no OSS
  transient di/dt tool → no fabricated number). §4.05: metal-density-below-CMP / dynamic-IR-over-budget
  turn a releasing tapeout into `released=False`.

## ★★ TAPEOUT-SIGNOFF CAMPAIGN COMPLETE — all program-first work landed (v1.2.75 → v1.2.81) ★★
**~20 program-first deliverables**, all chip-AGNOSTIC, §4.05-verified, gatekeeper MERGE_OK, pushed;
the heavy ones LIVE-run on real Docker/tools. Vibe-IC now: **runs the real Efabless shuttle precheck
(5/7 live)**, **runs the real XOR on real klayout**, **reaches a GENUINE power-verified LVS match on
real spm**, **has a complete honest release ladder** (17 gates, POWER_PIN_ONLY / decap-proxy /
row-util-density / vacuous-DRC / hardcoded-floor all replaced by real measured gates), and **P1 depth**
(multi-corner STA, AOCV, SI, LEC, DFT-95%, aging, thermal) — each honest about what the open PDK/OSS
tools can and cannot do.

### What remains — NOT plugin logic (external dependency / infrastructure / OSS-tool limits)
1. **A full sky130A PDK install** — blocks the live caravel harden + the full precheck ladder
   (only a partial volare PDK is present).
2. **Golden full-chip `caravel.gds` + the pre-hardened `user_proj_example` macro** — the XOR
   reference + harden inputs; OR the chipignite 2/7 blackbox waivers (auto-emitted).
3. **A vectorless/transient dynamic-IR (DVD) tool** — no OSS tool produces di/dt droop; the gate +
   emission stance are ready, honestly SKIPping until a tool exists (commercial Voltus/RedHawk).
4. **Commercial-grade depth** where the open stack cannot reach: AOCV/POCV tables + CCS-Noise SI +
   StarRC PEX + transition ATPG + aging Liberty + a thermal solver — each has the mechanism wired and
   an honest disclosure; a real foundry flow supplies the data/tool.

**These are data/environment/commercial-tool dependencies, not Vibe-IC capability gaps.** The plugin's
program-first tapeout-signoff surface is complete and honest end-to-end.

## ── PDK-UNLOCK LIVE RUN (v1.2.82) — the caravel DRT-0302 "floor" is OVERTURNED ──
Pushed on the biggest external dependency (a full sky130A PDK for the live caravel harden + full
precheck). Findings (all LIVE, dedicated containers, honest):
- **A full sky130A PDK was already present** (1.3 GB at the Caravel project's `dependencies/pdks/sky130A`,
  open_pdks 54435919; a second copy in iic-osic-tools `/foss/pdks`). The `SKY130A: None` seen earlier
  is a COSMETIC skywater-subversion label — the full PDK was already mounted (the precheck reported the
  exact open_pdks hash). The real blocker was OpenLane's version guard, cleared with the sanctioned
  `-ignore_mismatches`.
- **★ The caravel wrapper HARDEN ROUTES CLEAN — DRT-0302 is GONE.** Real OpenLane on
  `user_project_wrapper` at the fixed 2.92×3.52 mm outline: **`DRT-0199 violations = 0`, "No DRC
  violations after detailed routing"**, produced a fresh hardened GDS. The historical DRT-0302
  multi-bterm power-net wall (long cited as the 2-of-7 floor's cause) was NOT hit — a third campaign
  "floor" overturned. The flow only exits non-zero at STEP-24 KLayout XOR (blackbox `spm` macro, 4831
  diffs) — the documented blackbox-macro floor, honestly reported.
- **The FULL 12-check precheck ran with the real PDK** (the 5 PDK-dependent checks that couldn't run
  before): **klayout_beol PASS, klayout_offgrid PASS** (2/5 outright); magic_drc 2 + klayout_feol 11 =
  macro-boundary nwell (blackbox floor); **LVS FAIL only because `verilog/gl/user_project_wrapper.v` is
  ABSENT** (extraction against the real PDK worked — the harden's own `results/final/verilog/gl/`
  produces that netlist). So the remaining fails are (a) a project-input gap the harden itself fills,
  and (b) the blackbox-macro floor (needs the macro's real GDS/taps or explicit chipignite waivers).
- **§4.05 bug caught + fixed (v1.2.82):** the live run exposed a false-PASS — `run_harden` returned PASS
  off a STALE GDS from an unrelated prior run when the flow actually aborted (rc=255). Fixed: run-scoped
  GDS search + rc-aware verdict; proven live (same command now FAILs). This is exactly why live
  validation is load-bearing.
- **Still BLOCKED (honest, one input):** the golden full-chip `caravel.gds` is not in the project (only
  `user_project_wrapper_empty.gds`), so the full-chip XOR-vs-golden needs that reference placed at
  `<project>/gds/caravel.gds`.

**Net:** with the real PDK wired, the caravel harden CONVERGES and 2/5 PDK-checks PASS outright; every
remaining fail is now a NAMED, bounded item (the gl-netlist input the harden emits, the blackbox-macro
floor + its waivers, and the golden caravel.gds for XOR) — not a Vibe-IC capability gap.

## ── gl-NETLIST WIRED (v1.2.83) — precheck Consistency+LVS now run for REAL ──
The plugin's last WIRING gap on the caravel path is closed: `run_stage_gl` stages the harden's produced
`results/final/verilog/gl/user_project_wrapper.v` into the project's `verilog/gl/` (tag-scoped, §4.05 —
stages ONLY a netlist the harden actually produced; a harden that produced none → BLOCKED, no fabrication).
LIVE (real PDK + efabless/mpw_precheck), both checks advanced from "can't run / missing netlist" to REAL
comparisons:
- **Consistency** now runs a genuine structural compare → LAYOUT/COMPLEXITY/MODELING/POWER **PASS**; the
  only remaining fail is **PORTS** — the spm PILOT wrapper omits `analog_io[0:28]`/`user_clock2` vs the
  caravel fixed pinout (a DESIGN non-conformance of the pilot, not a plugin gap).
- **LVS** now runs a real netgen extract+compare (16s) → the residuals are genuine DESIGN issues in the
  pilot wrapper (`wbs_dat_o[0:29]`↔`wbs_ack_o` shorts) + the expected `spm` blackbox-macro floor.

**The DIVIDING LINE is now sharp and honest:** every remaining precheck fail is either (a) a DESIGN
non-conformance of the *spm pilot* wrapper (reduced port set + wbs shorts — needs a chip-specific real
submission wrapper, NOT a plugin change), (b) the `spm` blackbox-macro floor (allow-list/waiver), or
(c) the absent golden `caravel.gds` (fetch: `git clone -b 2024.09.12-1 efabless/caravel && make
uncompress`, or `make ship`). **The Vibe-IC program-first surface for the full Efabless tapeout flow is
complete** — harden→stage-gl→precheck→(merge+XOR) all run for real; what's left is design/data, not
capability.

## ── CROSS-IC TAPEOUT-SIGNOFF SWEEP (6 ICs) + DISTILLATION (v1.2.85) ──
Applied the complete `signoff_ladder_run --mode tapeout` + every individual gate to all 6 digital
benchmark ICs (each in a dedicated container, read-only on the plugin). ALL honestly NOT_RELEASED; the
scorecard + the chip-agnostic gaps it surfaced:

| IC | route | LVS (power-aware) | STA | genuine per-IC finding |
|---|---|---|---|---|
| spm | ✅ converged | ✅ **GENUINE_MATCH** | MET | (small, few ports — the only genuine LVS match) |
| sha256 | ⚠️ v1264 route incomplete (DRT-0085) | FAIL | rigor-absent | that run shouldn't have entered signoff |
| subservient | ✅ converged | FAIL (routed; wbs port-alias) | rigor-absent | back-end clean; masked antenna FAIL surfaced |
| ibex | ✅ converged | FAIL (routed; 16 port-shorts) | **ss −88.30ns** (single-corner+no DRV) | timing NOT closed multi-corner |
| opentitan_aes | ✅ converged (GDS) | FAIL — **signal-UNROUTED DEF** | rigor-absent | 87 real congestion DRC; write_def dropped signal routing |
| caravel | ✅ harden converged | — | — | golden XOR ran on real geometry; pilot-wrapper design non-conformance |

**Distilled (v1.2.85), all §4.05-verified + LIVE-validated:**
1. **Ladder honesty + EM Jmax** (4-IC): old tiers read DEAD legacy paths → masked real FAILs; now
   discover `reports/phase3/*` + parse real artifacts (surfaces subservient's masked antenna FAIL);
   EM tier resolves the PDK tech-LEF from `$PDK_ROOT`.
2. **STA multi-corner OCV + DRV** (ibex): auto-SDC gains set_max_transition/max_cap from real liberty
   (LIVE: slew 423→0); multi-corner OCV signoff STA surfaces the real ss −88.30ns (was hidden by
   typical-only). **+ 2 OpenSTA-3.1.0 latent bugs fixed** (`set_timing_derate` one-command rejection —
   which had been silently failing the v1.2.76 rigor report — + the report_check_types marker).
3. **LVS signal-unrouted-DEF guard** — the "signal-port label seeding" hypothesis (I was confident it
   was 4-IC-converged) was **REFUTED by live validation**: Magic already labels DEF PINS; the real aes
   root cause is a signal-UNROUTED DEF (write_def dropped routing). Shipped the honest guard
   (`LVS_INPUT_DEF_SIGNAL_UNROUTED`) instead of the no-op.

**METHODOLOGY LESSON (load-bearing):** even a hypothesis that "converges" across 3 independent IC runs
can be a SHARED mis-diagnosis — 3 agents all assumed label-seeding without checking whether the DEF was
routed. Only live validation refuted it. This is exactly why the doctrine is *program + independent
AI-solve + converge on disagreement*, and why a "floor"/"root-cause" label is never accepted until
live-proven. Two false conclusions were caught this sweep: subservient's "genuine-match needs
device-level = floor" (refuted by spm's real match) and the cross-IC "label-seeding" root cause
(refuted by the unrouted-DEF evidence).

**Honest per-IC residuals that are NOT plugin gaps** (design/data/upstream): aes write_def drops signal
routing (upstream flow gap) + 87 congestion DRC; ibex needs a multi-corner re-PnR/ECO to close ss
timing; sha256 v1264 route was incomplete; subservient/ibex LVS port-alias/port-short are design or a
separate (routed-DEF) extraction question; caravel pilot-wrapper isn't caravel-pinout-conformant.

## ── aes + ibex ROOT-CAUSE FIXES (v1.2.86) — both distilled + LIVE-validated ──
The two residuals above turned out to be a chip-agnostic PLUGIN fix (aes) and a real per-IC floor +
a general plugin improvement (ibex). Both traced LIVE, not assumed.

**aes — the "write_def drops signal routing" residual was actually an UNROUTABLE-CELL root cause (fixed).**
Traced live: `_dont_use_tcl` depended ENTIRELY on a PDK exclude file
(`.../openlane/sky130_fd_sc_hd/drc_exclude.cells`) that iic-osic-tools does NOT ship → ZERO exclusions →
repair inserted 41 `probe_p_8` characterization cells → TritonRoute can't pin-access a probe cell →
DRT-0085 ×26 aborts the route BEFORE any net is routed → write_def emits a signal-unrouted DEF. New
`_dont_use_family_fallback_tcl` excludes the unroutable characterization/low-power FAMILIES
(`*__probe_*`/`*__probec_*`/`*__lpflow_*`) via OpenROAD `get_lib_cells` over the loaded liberty.
LIVE: DRT-0085 26→0, probe cells 41→0, signal `+ROUTED` 0→39,003, the v1.2.85 guard fires→does-NOT-fire,
netgen reaches a real compare. spm unchanged. **Same DRT-0085-on-probe root also explains sha256's
incomplete route — a cross-IC chip-agnostic cause now fixed for every design.** §4.05: only lets a real
route complete; never fabricates a match.

**ibex — HONEST FLOOR + a general plugin improvement.** DRV-aware multi-corner ECO recovered +20.3 ns at
ss (−35.78 → −15.49) but ibex@20ns-ss does NOT close at ANY ss corner even after a full re-repair (the
slew fix recovered only 2.2 ns; the bulk is real slow-corner path delay). Achievable clock ~28 MHz
(1v40) / ~42 MHz (1v60) — reported AS a relaxation, never as closing 20 ns. So the 20ns-ss residual is a
REAL per-IC floor. The multi-corner-aware ECO (`_build_eco_repair_tcl` + `corner_libs`, ss-first) is a
genuine chip-agnostic plugin improvement (helps other ICs whose ss violation is within recovery range) +
it fixed 2 latent ECO-TCL bugs (ODB-0251 / DPL-0027) that would have aborted the emitted ECO if run.
§4.05: ss VIOLATED before+after; DRV limits from real liberty; no fabricated closure.

**Cross-IC latent bugs caught by the live sweep + fixes (v1.2.75→86):** the MCP-DRC vacuous stub; the
`set_timing_derate` one-command rejection (silently failed the v1.2.76 rigor report); the XOR
`pya.Region` copy-ctor crash; run_harden's stale-GDS false-PASS; the ECO-TCL ODB-0251/DPL-0027 aborts;
the `drc_exclude.cells`-missing → unroutable-probe-cell DRT-0085. Every one surfaced only under LIVE
tool execution — the load-bearing evidence that live validation (not mock/self-report) is what makes the
tapeout-signoff surface honest.

## THE reframing that changes everything (Efabless = no Calibre gap)

The one **real, free** tapeout path for sky130 is the **Efabless / chipIgnite / Google-sky130 open
MPW shuttle**. Its "foundry-qualified sign-off" is defined **entirely on the same open-source decks
Vibe-IC already runs** in `phase3_one_shot_runner.py`: Magic DRC, KLayout `sky130A.lydrc`
(FEOL/BEOL/offgrid), the antenna/latch-up decks, and Netgen LVS with `sky130A_setup.tcl`. **There is
NO Calibre gap to close for sky130.** So the real gap is **INTEGRATION + RIGOR**, not tool
credibility: the plugin can synth/PnR/DRC/LVS/streamout a correct CORE, but has never executed the
three things that make a submission a submission — (a) harden the core into `user_project_wrapper`
at Caravel's fixed pad-ring via OpenLane, (b) run `mpw_precheck` end-to-end and PARSE its verdict,
(c) the XOR proof vs the golden harness. Today those are stubs (`NOT_RUN` / command-hints /
hardcoded floors).

For a REAL commercial foundry (TSMC/GF/…), Calibre/PrimeTime/StarRC with the encrypted NDA runset is
fundamentally unrunnable open-source and is correctly left a documented WAIVER. **The honest target
is therefore: foundry-qualified == Efabless-shuttle-submittable for sky130.**

---

## ⛔ THE HIGHEST-INTEGRITY BUG FOUND (fix first, independent of everything else)

**MCP `eda_drc_klayout` gf180/sky130 branch is a VACUOUS NO-OP that returns `success`.**
(`mcp-eda/src/index.js` ~line 2202: reads the GDS, checks a top cell exists, prints
`DRC_COMPLETE=YES`, runs ZERO rules; the custom-PDK path derives only WIDTH+SPACING.) Any flow that
calls the MCP DRC tool on a foundry PDK gets a **false DRC-clean**. The only real DRC is the
phase3-runner KLayout-deck path. **This false-PASS surface must be killed or hard-routed to the real
deck before ANY DRC verdict from the MCP tool can be trusted. P0, do first.**

---

## The P0 tape-out blockers (must all be real before any "tapeout-ready" claim is honest)

### Foundry-handoff / shuttle (the load-bearing cluster)
1. **mpw-precheck is never run or parsed.** The whole shuttle gate (license/makefile/documentation/
   consistency/gpio_defines/**XOR**/Magic-DRC/KLayout-FEOL-BEOL-offgrid/**LVS**/oeb) exists only as a
   `NOT_RUN` Docker command-hint in `caravel_integration_runner.py`. **Build: a driver that runs
   `efabless/mpw_precheck` in Docker end-to-end and parses `*/logs` into a hard pass/fail gate.**
2. **No real Caravel harness hardening + no XOR.** The main flow yields a BARE-CORE GDS, not a
   hardened `user_project_wrapper` at Caravel's fixed 2.92×3.52 mm outline / pad ring (wrapper PnR
   step B1 = `NOT_RUN`; the campaign flattened caravel and hit the DRT-0302 multi-bterm power-net
   wall). The XOR check that proves the assembled GDS matches the golden harness **does not exist** —
   the "2/7 floor" is a hardcoded memory constant. **Build: wire `caravel_wrapper_emit.py` → OpenLane
   wrapper-harden (real Docker) → full-chip merge into `caravel.gds` → a KLayout XOR gate.**

### LVS (a real MATCH is the definition of a tapeout)
3. **No genuine LVS MATCH — the runner WAIVES the universal power-pin mismatch.** `_run_extraction_lvs`
   converts every sky130 OSS `failed pin matching` (POWER_PIN_ONLY) into `LVS_MATCH_POWER_AWARE` PASS.
   That is a REASONED WAIVER, not the "Circuits match uniquely, zero mismatch" a foundry requires.
   **Root fix: emit a POWER-AWARE GATE NETLIST (VPWR/VGND ports + PG connectivity, OpenLane
   power-aware flow) so netgen returns a REAL clean MATCH; stop crediting POWER_PIN_ONLY as PASS at
   the tapeout tier.** (This is the honest correction to v1.2.67/72's verdict-classifier waiver — that
   waiver is fine for triage, but a tapeout needs the real MATCH.)
4. **The aes real SIGNAL_NET_MISMATCH (517 rows → one node) is an open, unresolved defect.** Correctly
   FAILs (kept out of the waiver) but has no automated fix. **Build: correct pin-label layer / DEF
   port-seeding / PG tie-cells + a mirrored-port/tie-off resolver + regression.**

### Timing (foundry-qualified STA)
5. **No OCV/AOCV/POCV derating + no real all-PVT MCMM.** Timing is signed off at (typically) a single
   TT corner with NO on-chip-variation margin and NO multi-mode. **Build: an MCMM driver
   (corner×mode scenario matrix, per-mode SDC, SPEF-annotated) + `set_timing_derate`/AOCV support;
   fail sign-off when full PVT is not covered + not waived.**
6. **No SI-aware STA + no recovery/removal/MPW.** Crosstalk is advisory-only (`violations_count`
   hardcoded 0); async-reset recovery/removal and min-pulse-width arcs are never analyzed. **Build:
   coupled delta-delay SI STA (or documented per-net PrimeTime-SI waiver) + `report_check_types
   -recovery -removal -min_pulse_width` in every STA view with gates.**
7. **No closed ECO timing-closure loop + no real CDC/RDC.** Setup closure is one-shot best-effort
   (ibex shipped an UNCLOSED setup violation); multi-clock CDC is punted to SKIPPED-CONDITION; RDC is
   absent. **Build: an iterate-to-WNS≥0 ECO loop (STA→triage→targeted repair→LEC→re-STA) + a real
   structural CDC + RDC analyzer.**

### Power / reliability / test
8. **No dynamic (transient) IR-drop + no real EM current-density (Jmax) sign-off.** Static IR is a
   simplified OpenROAD PSM; EM current is measured but never compared to a foundry Jmax (the "EM
   tier" is a decap-cell-count proxy); dynamic droop is a keyword string only. These two most often
   kill real silicon. **Build: a vectorless/VCD DVD engine + a per-segment Jmax verdict (Black's
   equation) from the PDK.**
9. **No MBIST for on-chip RAM.** Zero memory-BIST insertion/simulation; any design with a RAM tapes
   out with untestable memories (the checklist lists MBIST with no enforcing program). **Build: an
   MBIST wrapper generator + march-pattern sim gate. P0 whenever RAM is present.**
10. **No true metal-density fill + no first-class Magic-DRC gate.** "Metal fill" is OpenROAD
    `filler_placement` (std-cell fillers only); the density metric is ROW utilization, not per-layer
    METAL density — so sparse designs FAIL Efabless `met_min_ca_density`. **Build: real per-layer
    metal-fill (KLayout/Magic/ODB density-fill) + a per-layer metal-density checker + a first-class
    authoritative Magic full-deck DRC gate.**

---

## P1 (needed for a robust sign-off, not an absolute first-submission blocker)

- **Post-layout LEC** — re-prove RTL ≡ routed netlist after CTS/PnR/ECO/fill (Step 13 today only
  proves RTL ≡ post-DFT synth). Wire `eda_equiv` on `routed.v` vs `synth.v`.
- **Formal to induction + coverage** — default is BMC depth-20 (bounded); add `mode prove`
  (k-induction) default + a formal-coverage/COI metric.
- **Functional coverage** — verilator gives line/toggle only; add SVA covergroup/cover-point closure.
- **DFT to foundry bar** — raise ATPG stuck-at target 80%→≥98%, add transition/at-speed patterns,
  BSDL + boundary-scan-cell-per-pad.
- **GDS-level antenna DRC** (Magic/KLayout antenna deck) as the authoritative gate (today: OpenROAD
  router antenna count only).
- **Signoff-grade PEX** — StarRC/QRC when licensed; at minimum a gate that OpenRCX (not the
  `estimate_parasitics` stub) was used + multi-corner (min/nom/max) SPEF + an SPEF-pedigree gate.
- **Foundry latch-up / PERC / ESD decks** — run the PDK's own latch-up rule + a real PERC-class deck
  where the PDK ships one; keep device-physics ESD (HBM/CDM) as honest MANUAL_REVIEW.
- **Efabless-shuttle handoff profile** — `foundry_handoff_pack_gen.py` currently models a
  commercial-NDA mask/WAT/scribe kit; add the actual Efabless deliverable shape (hardened wrapper +
  precheck-clean caravel GDS + gds/verilog manifest).
- **Sign-off gating rigor** — `signoff_ladder_run`/`tapeout_checklist_gen` currently accept WAIVED
  LVS → PASS_WITH_WAIVERS; make LVS-MATCH a HARD release gate; forbid POWER_PIN_ONLY-as-PASS at the
  tapeout tier; require signoff-SPEF substance.
- **Clock/jitter/skew numeric sign-off**, **RDC**, **full connectivity ERC deck** (shorts/soft-connect
  beyond floating nets), **pin-ring conformance gate** vs Caravel's fixed 38-IO ring.

## P2 (completeness / product-grade, not gating a first shuttle run)
Aging/BTI/HCI-derate STA, thermal, signal-net EM, multi-mode (scan/test) SDC, dynamic power w/
SAIF/VCD, DFM via-doubling/recommended-rules (OPC/RET/hotspot stay honestly foundry-side),
management-SoC/firmware co-verification, boundary-scan/BSDL completeness.

---

## What is ALREADY substantive (don't rebuild — the base is real)
- **Real OSS DRC** via the phase3 runner (KLayout `sky130A.lydrc` + Magic re-stream tiebreak + stdcell
  classification + offgrid) — genuine for the CORE.
- **Real OSS LVS** (Magic `ext2spice lvs` → netgen) with an honest MATCH/MISMATCH classifier and a
  §4.05 no-leak guard that keeps signal-net mismatches FAILing.
- **Real OpenRCX SPEF** (captable-driven) + SPEF-annotated STA + multi-corner discovery from the
  container PDK (v1.2.66).
- **Real LEC** RTL≡synth (Yosys equiv, anti-vacuous) + real SymbiYosys formal (BMC) + real DFT/ATPG
  coverage parse + real antenna repair/report + honest ESD/latch-up presence/geometry gates
  (MANUAL_REVIEW / conclusive-fail-only, never auto-PASS on device physics).
- **A complete sign-off orchestration skeleton** (`signoff_ladder_run`, `signoff_audit`,
  `tapeout_checklist_gen`, `signoff_waiver_emit`, `foundry_signoff_plan_check`) — it just needs the
  P0 tiers to run FOR REAL and to stop accepting WAIVED-LVS as a pass.

---

## The shortest honest path to a genuine sky130 (Efabless) tapeout
**~4 P0 integration builds + 1 P1**, because the OSS sign-off tools are already the qualified ones:
1. **Kill/redirect the MCP DRC false-PASS stub** (highest-integrity, smallest).
2. **Real `mpw_precheck` driver + parser gate** (the shuttle gate, run + consumed).
3. **Caravel wrapper-harden in-flow** (OpenLane macro-in-wrapper at the fixed pad ring) + **full-chip
   merge** + **KLayout XOR gate**.
4. **Power-aware gate netlist → genuine LVS MATCH** (VPWR/VGND ports; stop waiving POWER_PIN_ONLY at
   tapeout tier) + resolve the aes SIGNAL_NET tie-off artifact.
5. **(P1) Post-layout LEC** + the MCMM/OCV/SI/recovery timing rigor for a defensible STA sign-off.

Everything downstream of those already exists and is substantive. Until the P0 items run FOR REAL, no
"tapeout-ready" claim for a Caravel submission is honest — but the plugin is **materially closer than
its stubs suggest**, and (crucially) **not blocked by any commercial-tool gap for sky130**.
