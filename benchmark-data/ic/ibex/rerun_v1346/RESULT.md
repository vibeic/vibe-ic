# ibex — phase3 re-run on plugin v1.3.46 (fork vibeic-eda:0.2.5)

> Authored by the orchestrator from the on-disk artifacts — the re-run agent completed the compute
> (flow finished ~05:49) but idled without writing this deliverable (see the empty-RESULT root-cause +
> the v1.3.51 completeness gate that now catches exactly this).

## 1. Verdict — timeout→GDS CONFIRMED

The definitive test of the v1.3.46 antenna incremental repair→reroute loop. In the v1342 run ibex's
antenna step did a full ~1900-net reroute and **timed out with no GDS**. On v1.3.46 the incremental loop
**converged and ibex completed to GDS**.

| Bar | v1342 | v1.3.46 re-run |
|---|---|---|
| antenna | full-reroute TIMEOUT | **`ANTENNA_LOOP_CONVERGED: iter=3`** + `ANTENNA_POSTROUTE_DONE` ✅ |
| GDS | none | **`ibex_top.gds` = 167,659,258 B** (SHA-256 `aa823f7c…6ec800`) ✅ |
| DRC | — | **0** ✅ |
| SPEF | — | non-empty via **librelane** captable ✅ |
| synth | 31,790 cells (slang) | reproduced ✅ |
| flow_compliance | — | **PASS=29 · FAIL=2 · MISSING=0 · SKIPPED=24 · VACUOUS-PASS=1** |

## 2. The two FAILs (honest residual — NOT antenna/timeout defects)
- **STA setup timing not fully closed** — `sta.rpt` shows a `−3.20 ns slack (VIOLATED)` path after a hard
  217-violation `eco_timing_repair` (the ECO ran to completion; ibex at sky130 with these constraints is a
  genuine timing-closure workload, Category-H-like, not a tool/antenna bug).
- Aggregate roll-up FAIL cascades from the STA residual (phase3/phase23 completion audit).
Everything the v1.3.46 fixes touch (antenna, SPEF) PASSED.

## 3. Root-cause that needed a manual timeout bump (already fixed upstream)
The v1342/v1.3.46 fixed-timeout ESTIMATE undersized ibex: it got **4395 s** where the size formula was due
~7958 s, and the initial detailed_route ALONE takes ~60 min — so the antenna loop was killed mid-run. This
run used a confirmation-only timeout override (10795 s) on the v1.3.46 worktree to prove GDS is reachable.
**That root-cause is now FIXED GENERALLY** by the **v1.3.47 progress-stall watchdog** (kill only on
no-progress, never a still-progressing route) + **v1.3.48 plugin-wide enforcement** — a fresh v1.3.48+ ibex
run needs NO manual timeout.

## 4. Tool substitution
Synopsys VCS→iverilog 14; Design Compiler→yosys (built-in `read_slang`) + OpenROAD 26Q3 (fork); Calibre
DRC→KLayout sky130A; parasitics→OpenRCX (librelane captable). Container: `vibeic/vibeic-eda:0.2.5`.

## 5. Captured enhancements
- R11 (this file): STA-setup residual is a real sky130 timing-closure workload → analog/timing follow-up, not a v1.3.46 gap.
- The empty-RESULT failure mode (this run's own missing deliverable) → v1.3.51 `run_output_completeness_check` gate + orchestration discipline.

Next: fresh clean-room ibex on v1.3.48+ (no manual timeout) to confirm the watchdog auto-lets it finish.

## 6. Close-loop of the STA-setup residual (v1.3.56, 2026-07-10) — proven **Category-H spec-vs-technology floor**

The §2 "STA setup not fully closed" residual was driven to a rigorous verdict (§4.1 discipline:
try hard BEFORE labelling a floor; §4 A–H triage). It is **Category-H (genuine timing-closure
workload)**, NOT a fabricated floor and NOT a tool/antenna bug.

**The real number is worse than the `−3.20 ns` PnR-internal estimate.** That figure was a
single-corner PnR-internal (no-SPEF) value. On the REAL routed parasitics the worst setup path is
**−21.89 ns @ 10 ns (TT + SPEF)**, `startpoint _25216_/Q → endpoint _24481_/D` — a ~30-level
combinational path whose middle stages carry gross **max-slew violations** (1×-drive gates at
2–4.5 ns slew vs the 1.5 ns limit → 2–4 ns of delay per stage), i.e. under-buffering PLUS genuine
logic depth.

**10 ns / 100 MHz is the DESIGN's own target** (staged `input/constraints/constraint.sdc`:
`set clk_period 10.0`, scoped to `ibex_core` inside the `ibex_top` wrapper). Not an arbitrary
default.

**We TRIED to close it** (repair_design + repair_timing, both parasitic models):

| repair state | placement-est WNS | real-SPEF WNS |
|---|---|---|
| start @10 ns | −2.96 | **−20.29** |
| + repair_design (DRV/slew) | −2.96 | **−14.82** (539 resized) |
| + repair_timing -setup | −2.84 (plateau) | **−11.45** ("Unable to repair all") |

Post-route SPEF-annotated repair hits `RSZ-0075 makeBufferedNet failed` on >1000 drivers — the
**fork P0 post-route-repair limitation** (Signal-11 is fixed, but the SPEF-topology buffer-tree
build is still limited); this is why the plugin ECO restarts repair from `post_hold.def` (placed)
and repairs on an estimate. Neither model reaches 10 ns because 100 MHz is genuinely infeasible for
a full RV32 core at sky130 in the OSS flow.

**Achievable Fmax (period sweep on the final `eco_routed.def`, confirming exact linearity):**

| corner / model | achievable period | Fmax |
|---|---|---|
| placement-est, TT | ~13 ns (MET +0.36 @ 13 ns) | **~77 MHz** |
| real-SPEF, TT (after best-effort repair) | ~21.5 ns | **~47 MHz** |
| SS + OCV (sign-off) | worse | < 47 MHz |

All below the 100 MHz target — consistent with published ibex@sky130 (~50 MHz). Hitting 100 MHz
needs a faster node / commercial tools, or microarchitectural pipelining of the load→ALU→writeback
path (a design change; ibex's pipeline is spec-fixed). This is the **same honest class as sha256's
10 ns single-cycle-round residual** (reported at its achievable 25.9 ns, not "closed to 10 ns").

**CAPTURE (Bucket-A, program-first, v1.3.56):** `programs/sta_achievable_fmax_report.py` — a
deterministic, chip-agnostic honest achievable-Fmax reporter. Exact core
`achievable_period = spec_period − worst_setup_slack` (reg→reg slack is linear in period; verified
here). It is a MEASUREMENT, never a clock relaxation (`relaxation_applied` always False; the
sign-off verdict stays FAIL). Wired into `phase3_one_shot_runner` at the multi-corner OCV sign-off:
when setup is SURFACED as violated it now emits `reports/phase3/achievable_fmax.json` ALONGSIDE the
FAIL, so every future CPU-class Category-H residual self-reports its Fmax instead of a bare FAIL
(sha256 got this by hand; ibex did not — now automatic). 20 unit tests + real-artifact validation.
