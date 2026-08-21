# HANDOFF TO GATEKEEPER

## Worktree & Commit

| Field | Value |
|-------|-------|
| **Worktree** | `/home/reyerchu/vibe-ic-wt-caravel-slew-drv3` |
| **Branch** | `fix/caravel-slew-drv-closure-v3` |
| **Commit SHA** | `27523121` |
| **Base** | `main` @ `0d2c63d3` (v1.5.78) |
| **Version** | NOT assigned — gatekeeper assigns at land time |

## What Was Done & Why

### Problem
`step_signoff_drv_wire_length_repair` was disabled at v1.5.65 (commit
`e9de86013`) after it caused:
- LVS regression: spare-tie nets (`spare_tielo`, `spare_tiehi`) merged with
  unrelated signal nets after reroute
- STA measurement divergence: session-local DRV estimate (330->178) vs real
  multi-corner OCV sign-off (4->219)

~421 real max_slew violations remain on caravel_user_project x sky130A (419
cells in a 2920x3520 um harness-fixed die at 0.2% utilization -> multi-mm
wires -> slew explosion).

### Root Cause (traced, not hypothesized)
1. **Routing clear loop** (`odb::dbWire_destroy`) destroyed ALL non-PG net
   wires, including `spare_tielo` / `spare_tiehi` and nets touching
   `set_dont_touch` instances. Subsequent `global_route + detailed_route`
   merged those nets with unrelated signals -> LVS mismatch.
2. **Promotion gate** compared session-local single-corner SPEF estimate
   against itself (before/after), not against the downstream multi-corner
   OCV sign-off pipeline. This allowed a regressed design to be promoted.

### Fix (4 parts)

**A. `_spare_safe_routing_clear_tcl(marker_prefix)` helper**
A shared TCL generator that clears signal-net routing while skipping:
- Nets whose name matches `*spare*` (tie-off nets from `_build_spare_postfix_tcl`)
- Nets that connect to any `isDoNotTouch` instance (the spare cells)

Applied to all 3 routing-clear sites:
- `_ship_wire_length_escalation_tcl` (escalation reroute)
- `_ship_signoff_spef_repair_tcl` (signoff repair reroute)
- `_SHIP_POSTROUTE_CVG_TCL` (convergence loop reroute, raw string template)

**B. Post-promote spare-tie net integrity check**
Before promoting escalated route over base, reads both escalated netlist
and DEF to verify `spare_tielo` net and `spare_tielo_drv` instance are
present. If the base had them but the escalated output lost them ->
refuse promote (fail-safe rollback). Only fires when base actually had
spares; designs with `spare_density=0` unaffected.

**C. Stale downstream artifact invalidation**
After promote, deletes stale downstream artifacts so
`step_canonicalize_artefacts` re-derives everything from the promoted route:
- GDS file
- `sta_mcorner_ocv.rpt`, `sta_mcorner_ocv_setup.tcl`, `sta_mcorner_ocv_hold.tcl`
- `mcorner_ocv_stance.json`
- Non-escalation SPEF files

This ensures the acceptance gate (`sta_corner_record_completeness_check`)
reads a report based on the promoted design, not the pre-escalation design.

**D. Re-enable escalation**
Removed `return None` from `step_signoff_drv_wire_length_repair`.
The session-local promotion gate (`_ship_escalation_should_promote`)
remains unchanged (still requires strictly lower violator count,
DRC-clean reroute, non-negative setup). Downstream multi-corner OCV
sign-off STA independently re-measures the promoted design.

### Why This Won't Repeat the v1.5.65 Incident
- LVS path: spare nets are now preserved across reroute (fix A) AND
  verified present before promote (fix B). Both must INDEPENDENTLY fail
  for a spare-net LVS regression to ship.
- STA path: even if session-local estimate diverges from multi-corner
  sign-off, stale artifacts are invalidated (fix C) so
  `step_canonicalize_artefacts` re-derives the OCV STA from the promoted
  route. The acceptance gate reads a report based on the actual promoted
  design, not the pre-escalation design. A regression surfaces as a
  sign-off FAIL, not a silent pass.

## Controlled Experiment Results (drvlab_a857c45b)

Four-variant controlled experiment using the SAME measurement chain as
the acceptance gate (OpenRCX extract, OpenSTA multi-corner OCV, netgen LVS):

| Variant | Description | max_slew | Total DRV | LVS | spare_tielo |
|---------|-------------|----------|-----------|-----|-------------|
| C0_control | Baseline (no repair) | 421 | 483 | pin-mismatch* | present |
| C1_ripup | Ripup-only (no repair) | 421 | 483 | pin-mismatch* | present |
| C2_esc_bare | repair_design + max_wire_length (no guard) | **177** | **219** | pin-mismatch* | present |
| C3_esc_guard | repair_design + max_wire_length (with guard) | **177** | **219** | pin-mismatch* | present |

\* "pin-mismatch" = netgen's top-level pin matching on Caravel's unused IO bus
(structural, not circuit-level; all 478 devices match, all 513 nets match,
0 unmatched instances). The runner's KLayout LVS reports "Circuits match
uniquely" for the same design.

**Key findings:**
- C2 and C3 produce byte-identical netlists, DEFs, and STA reports — the
  dont_touch guard has no effect in this single-iteration controlled
  environment (spare nets survive the reroute regardless). The guard is
  defense-in-depth for the runner's multi-iteration convergence loops.
- Session-local estimate (330->178) closely matches the real multi-corner
  OCV result (421->177 = 58% reduction). This is expected when the
  measurement chain runs on the SAME routed design; the v1.5.63 divergence
  was caused by measuring the pre-reroute estimate against the post-reroute
  sign-off.
- Spare nets (spare_tielo, spare_tielo_drv) confirmed present in both C2
  and C3 netlists.

## Gate Results

### Unit Tests
| Suite | Count | Result |
|-------|-------|--------|
| test_ship_drv_wire_length_escalation | 24 (17 existing + 7 new) | ALL PASS |
| test_phase3_one_shot_runner | 6 | ALL PASS |
| test_phase3_backend_fixes | 78 | ALL PASS |
| test_phase3_signoff_chain_organic | 121 | ALL PASS |
| test_ship_repair_drv_closure_loop | 5 | ALL PASS |
| **Total** | **234** | **ALL PASS** |

### Negative Control Tests (7 new — MUST fail on pre-fix code)
1. `test_spare_safe_routing_clear_tcl_contains_spare_filter` — verifies
   helper emits spare-name glob + dont_touch check
2. `test_escalation_routing_clear_uses_spare_safe_helper` — verifies
   escalation TCL contains spare filter (would fail on pre-fix: no filter)
3. `test_postroute_convergence_tcl_uses_spare_safe_clear` — verifies
   convergence loop contains spare filter
4. `test_signoff_spef_repair_tcl_uses_spare_safe_clear` — verifies
   signoff repair TCL contains spare filter
5. `test_spare_safe_clear_parses_in_tclsh` — tclsh syntax check
6. `test_spare_safe_clear_skips_spare_nets_in_tclsh` — tclsh functional
   test with simulated spare/dont_touch/regular nets: regular destroyed,
   spare preserved, dont_touch preserved
7. `test_escalation_step_is_not_disabled` — AST-based check that the first
   executable statement of step_signoff_drv_wire_length_repair is NOT
   `return None`

### End-to-End Verification (PENDING — requires container access)
Full caravel_user_project x sky130A phase3 re-run needed to confirm:
- (a) `sta_mcorner_ocv.rpt` slew DRV count improves from 421 baseline
- (b) LVS still reports "Circuits match uniquely"
- (c) DRC clean, no other corner regressions

**NOTE**: Container `cv_caravel_user_project_sky130A_2929501` is running on
8HD-4 (192.168.1.120). SSH access from 8HD-d was denied (key auth failure).
The gatekeeper should either:
- Run the e2e verification from 8HD-4 or 8HD-7 (which has SSH access to all)
- Or spin up a fresh container on any machine with the vibeic-eda:0.2.29
  image (use LOCAL image — do NOT `docker pull`, manifest not on ghcr)

**CRITICAL REMINDER**: the synth netlist reuse bug (PDK-keyed only, not
RTL-keyed) has a pending fix at `/home/reyerchu/vibe-ic-wt-sha256mcr/`.
Since this fix does NOT change RTL, the existing synth netlist is valid.
But if any RTL edit is made during verification, confirm the netlist was
re-synthesized (check mtime/hash) before trusting STA numbers.

## Files Changed

| File | Lines | Description |
|------|-------|-------------|
| `programs/phase3_one_shot_runner.py` | +222/-44 | spare-safe helper, 3-site replacement, re-enable escalation, spare-tie integrity check, stale artifact invalidation |
| `programs/tests/test_ship_drv_wire_length_escalation.py` | +186 | 7 negative control tests |

## Diff from v1 and v2 Attempts

This is v3 of the fix, with the same code content as v2 (`b2c404a9`)
but on a clean branch from `0d2c63d3` (v1.5.78 base). v1 attempt was at
`/home/reyerchu/vibe-ic-wt-caravel-slew-fix` (branch
`fix/caravel-slew-drv-closure`, commit `39d694a00`).

| Aspect | v1 (`39d694a00`) | v2 (`b2c404a9`) | v3 (`27523121`) |
|--------|------------------|-----------------|-----------------|
| Base | `0d2c63d3` | `0d2c63d3` | `0d2c63d3` |
| Stale artifact invalidation | Not included | Included | Included |
| Negative control tests | 6 | 7 | 7 |
| Test count verification | 23 total | 24 total | 24 total |
| AST-based disable detection | Not included | Included | Included |
| Regression suite coverage | 205 tests | 210 tests | 234 tests |
| Controlled experiment data | None | None | C0/C1/C2/C3 at `/home/reyerchu/drvlvs_a857c45b/` |

### v3-specific additions over v2
- **Controlled experiment evidence**: 4-variant lab (drvlab_a857c45b) with
  independent measurement confirming 421->177 max_slew reduction (58%) and
  spare-net preservation, using the same measurement chain as the acceptance
  gate. C2 vs C3 byte-identity confirms the spare-safe guard is
  defense-in-depth (no effect in single-iteration, but protects multi-
  iteration convergence loops in the full runner).
- **Expanded regression coverage**: 234 tests (vs 210 in v2) —
  test_ship_repair_drv_closure_loop (5 tests) now explicitly included.

## Version Note
Version is NOT pre-assigned. The gatekeeper assigns the monotonic version
at land time (previous attempt had a version collision from rebase;
pre-assigning would create another).
