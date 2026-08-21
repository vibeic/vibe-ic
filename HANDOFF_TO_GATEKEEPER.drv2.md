# HANDOFF TO GATEKEEPER

## Worktree & Commit

| Field | Value |
|-------|-------|
| **Worktree** | `/home/reyerchu/vibe-ic-wt-caravel-slew-drv2` |
| **Branch** | `fix/caravel-slew-drv-closure-v2` |
| **Commit SHA** | `b2c404a9` |
| **Base** | `main` @ `0d2c63d34` (v1.5.78) |
| **Version** | NOT assigned — gatekeeper assigns at land time |

## What Was Done & Why

### Problem
`step_signoff_drv_wire_length_repair` was disabled at v1.5.65 (commit
`e9de86013`) after it caused:
- LVS regression: spare-tie nets (`spare_tielo`, `spare_tiehi`) merged with
  unrelated signal nets after reroute
- STA measurement divergence: session-local DRV estimate (330→178) vs real
  multi-corner OCV sign-off (4→219)

~421 real max_slew violations remain on caravel_user_project × sky130A (419
cells in a 2920×3520 um harness-fixed die at 0.2% utilization → multi-mm
wires → slew explosion).

### Root Cause (traced, not hypothesized)
1. **Routing clear loop** (`odb::dbWire_destroy`) destroyed ALL non-PG net
   wires, including `spare_tielo` / `spare_tiehi` and nets touching
   `set_dont_touch` instances. Subsequent `global_route + detailed_route`
   merged those nets with unrelated signals → LVS mismatch.
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
present. If the base had them but the escalated output lost them →
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

## Gate Results

### Unit Tests
| Suite | Count | Result |
|-------|-------|--------|
| test_ship_drv_wire_length_escalation | 24 (17 existing + 7 new) | ALL PASS |
| test_phase3_one_shot_runner | 6 | ALL PASS |
| test_phase3_backend_fixes | 78 | ALL PASS |
| test_phase3_signoff_chain_organic | 121 | ALL PASS |
| test_ship_repair_drv_closure_loop | 5 | ALL PASS |

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
Full caravel_user_project × sky130A phase3 re-run needed to confirm:
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

## Diff from v1 Attempt

This is v2 of the fix, superseding the previous attempt at
`/home/reyerchu/vibe-ic-wt-caravel-slew-fix` (branch
`fix/caravel-slew-drv-closure`, commit `39d694a00`). Key differences:

| Aspect | v1 (`39d694a00`) | v2 (`b2c404a9`) |
|--------|------------------|-----------------|
| Stale artifact invalidation | Not included | Deletes GDS, STA reports, SPEF after promote |
| Negative control tests | 6 | 7 (added `test_escalation_step_is_not_disabled`) |
| Test count verification | 23 total | 24 total |
| AST-based disable detection | Not included | Uses `ast.parse` to check first statement |
| Regression suite coverage | 205 tests | 210 tests (added repair_drv_closure_loop) |

## Version Note
Version is NOT pre-assigned. The gatekeeper assigns the monotonic version
at land time (previous attempt had a version collision from rebase;
pre-assigning would create another).
