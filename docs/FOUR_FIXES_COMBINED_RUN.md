# All four fixes ON, in one run — what the flow produced, and where it still stops

_Run 2026-08-20 on host 8HD-6. Combines the four separately-proven fixes and reports the
shuttle operator's precheck return code._

NDA: `<PDK>` is the shuttle's PDK, `<lib>` its 5V 7-track standard-cell library; the
foundry, the node and the operator are referred to generically. Cell names are given by
family (`fill_64`, `fillcap_4`) because the family is the checkable content.

## The rc, up front

    rc 1

**and it is NOT the four fixes that stopped it.** The die never got a seal ring, because
the PDK's own seal-ring generator is broken in every EDA image on this host (§5). The
operator's precheck refuses any unsealed die, so no combination of these four fixes could
have returned 0 here. What the fixes DID deliver is measured in §3 and it is large.

Quoted verbatim from the container's `error.log`:

```
Subprocess had a non-zero exit.
Last 1 line(s):
[Error]: Layout origin is not at (0, 0)

Full log file: '../data/rundir/runs/RUN_2026-08-20_01-32-14/03-klayout-checksize/klayout-checksize.log'
```

    PrecheckFlow - Stage 3 - Check Slot Size    2/16

## 1. THE THREE RUNS

Same flow, same PDK, same slot, same RTL, same host, same container. The only variable in
A vs C is the flow code.

| | A — fixes ON | B — fixes OFF | C — fixes OFF |
|---|---|---|---|
| netlist routed | `post_dft_netlist.v` (463 inst) | `spm_synth.v` (262 inst) | `post_dft_netlist.v` (463 inst) |
| PnR | converged | converged | **NOT converged** — `ROUTE_NOT_CONVERGED: detailed route completed with 1 violations remaining (final DRT-0199)` |
| DEF `DIEAREA` µm | `(442 442) (1494 2089)` | `(0 0) (1936 2531)` | — |
| pins | 41, **0 on the die boundary**, nearest 442.260 µm from it | 36, nearest **0.260 µm** from it | — |
| filler instances | **17 236 spacers, 0 decaps** | **0** (`SPARSE_DIE_FILL_SKIPPED: core_util=0.5769%`) | — |
| sign-off DRC | **2** | **187** | not reached |
| precheck | rc 1 @ stage 3, `Layout origin is not at (0, 0)` | rc 1 @ stage 3, `Layer 'GUARD_RING_MK' is not used.` | no GDS |

**A and C route the byte-identical netlist** (`sha256 57720a8a3f90…`). C is the honest
like-for-like control and it does not produce a die at all: with the floorplan unfixed,
the same netlist on the same slot does not close routing. B is the control that DID
produce a die, and its per-rule histogram is the before-column in §3 — with the netlist
difference stated, not hidden.

## 2. THE BASE, AND HOW THE INPUTS WERE OBTAINED

* Flow: worktree `mg/gfinal-8hd6` off `origin/int/tonight` (`7676d9c56`).
* Control: a pristine worktree at the same `7676d9c56`, unmodified.
* Design: the repo's own `spm` RTL. Synthesis reproduced the flow's OWN recorded yosys
  command (read off `synth.log` of the published `<PDK>` run) with `spm` as top. It
  lands on **262 cells / chip area 8047.6032** — bit-equal to that published run's own
  figures, which is what makes it the flow's netlist and not a hand-rolled one.
  The flow then re-ran synthesis and DFT itself; both arms routed what it produced.
* Slot contract: the operator's published project template, cloned at the pinned commit
  `0de7e394337a1f`, OUTSIDE this repository, and read through the flow's own step-0.5ic
  ingester. `librelane/slots/slot_0p5x0p5.yaml`, `sha256 683e070cbd1137c4…` — matching
  the digest already recorded in `docs/research/template_ingest_run.md`, so the two
  ingests agree. It pins `DIE_AREA [0, 0, 1936, 2531]` and `CORE_AREA [442, 442, 1494, 2089]`.

## 3. PER-CATEGORY, BEFORE AND AFTER

Sign-off DRC — the PDK's own deck, run by the flow, on each arm's own streamed GDS.
BEFORE = arm B (fixes off), AFTER = arm A (fixes on).

| rule | BEFORE | AFTER | delta |
|---|---:|---:|---:|
| `NP.2`     |  53 | **0** | −53 |
| `PP.2`     |  49 | **0** | −49 |
| `NW.2a_LV` |  25 | **0** | −25 |
| `DF.13_MV` |  22 | **0** | −22 |
| `DV.5`     |  16 | **0** | −16 |
| `NW.2b_LV` |  16 | **0** | −16 |
| `NW.2b_MV` |   4 | **0** | −4 |
| `PL.8`     |   1 |   1 | 0 |
| `M1.4`     |   1 |   1 | 0 |
| **TOTAL**  | **187** | **2** | **−185** |

All six rules the filler fix was predicted to zero went to zero, and `DF.13_MV` with them.

## 4. WHICH FIX DELIVERED WHAT

**Fix 1 — the floorplan takes the slot's CORE_AREA.** `initialize_floorplan -die_area`
and `-core_area` both become `[442, 442, 1494, 2089]`; the slot's `DIE_AREA` survives only
for the ring and the size check. Delivered, measured: DEF `DIEAREA` is exactly that
rectangle, and **all 41 pins sit 442.260 µm inside the slot die edge, none on it** —
against 0.260 µm in the control. `-core_area` alone was already known to be insufficient
(`ppl place_pins` has no core-boundary mode); setting `-die_area` is what moves the pins.
Spare-cell placement was moved onto the same rectangle in the same change, or every spare
would have landed outside the die OpenROAD was given.

**Fix 2 — spacers only.** `_discover_filler_masters_from_lef` ordered decaps first; the
discovery now returns spacers only, on both the discovery and the hardcoded-library path.
Masters used, and this is the answer to "say which you used":

    fill_64  fill_32  fill_16  fill_8  fill_4  fill_2  fill_1

Delivered, measured: **17 236 spacer instances, 0 `fillcap_*`**. `filltie` and `endcap`
are correctly not treated as fillers.

Fix 2 needed one thing that is not on the brief's list, and it is disclosed rather than
folded in: **the #684 sparse-die guard would have skipped the fill entirely**, which is
what left those seven rules violated in the first place (arm B:
`SPARSE_DIE_FILL_SKIPPED: core_util=0.5769%`, 0 filler cells). The guard exists to stop
the flow tiling a large MANDATED die that a small design was hardened into — and after
fix 1 that empty band is no longer inside the die being filled: it is outside it, where
the ring and pads go. So the guard is withheld when, and only when, the floorplan
rectangle IS the operator's own CORE_AREA (`SPARSE_DIE_FILL_NOT_APPLICABLE`). **This is
why the order matters**: the same exemption without fix 1 would hand `filler_placement`
the whole slot and reinstate the explosion the guard was built to prevent.

**Fix 3a — seal the SLOT rectangle.** `die_finishing_gen` is now passed
`--die-width 1936 --die-height 2531` from the slot record. This was not theoretical: the
control's report reads `die_source: "DIEAREA of phase3/stage3/pnr/routed.def"`, so with
fix 1 in force and fix 3a absent the generator would have built the ring around the
1052 × 1647 CORE rectangle and returned PASS. The fixed run reads
`die_source: "--die-width/--die-height"`.

**Fix 3b — the fill got a keep-out.** The engine had none: it tiled every under-target
window and kept out only of circuit metal. It now accepts declared keep-outs, and the
number is the PDK's own — `space_to_scribe_line` read out of the PDK's `fill_metal.rb`,
where the PDK itself does `scribe_line_ring = _frame - _frame.sized(-space_to_scribe_line)`
and subtracts it. **26.0 µm**, read, not chosen. The measurement bbox is deliberately NOT
shrunk: the foundry rule measures over the whole die, so a keep-out makes the target
harder to reach, never easier, and an unreachable one stays visible as `reached: false`.

Proven on a controlled fixture before the flow run: same layout, same target, fill
without the keep-out puts **6268.080 µm²** of dummy metal in the 26 µm band; with it,
**0.000 µm²**, and the density target is still reached. In the flow run the keep-out
reports `sources: ["edge:26.0um"]`, `area_um2: 137645.56`, and metals 2–5 reach
0.433/0.432/0.440/0.446 against target — with sign-off DRC still at 2. The failure mode
this fix exists to prevent (fill over the ring, 1177 → 18686) did not recur.

`metal_fill_emit` was used, not the PDK script — the brief's preferred branch, because a
keep-out could be given to it.

**Fix 4 — the antenna item.** Rides on fix 1, as expected. `antenna.json`:
`net_violations: 0, pin_violations: 0, clean: true, verdict: PASS`.

## 5. WHAT STOPPED IT, AND WHY IT IS NOT ONE OF THE FOUR

The PDK ships `libs.tech/klayout/tech/scripts/sealring.py`. Its first act is
`from sealring_cells import <the PDK's seal-ring PCell>`, and **`sealring_cells` does not exist
anywhere in the image** — checked in all five EDA images on this host (`0.2.89`, `0.3.0`,
`0.3.6`, `0.3.11`, `0.3.13`), in the operator's precheck image, and in the operator's
project template. None of them has it.

Worse, `sealring.py` handles the ImportError by printing and calling `sys.exit()` — which
exits **0**. A caller that trusted the return code would record a sealed die. Ours did not:
`die_finishing_gen` checked for the output layout, found none, and refused —

    "state": "FAIL",
    "reason": "the PDK seal-ring generator (…/sealring.py) produced no output layout … —
               it exited 0 and said: … Error: Couldn't load the seal ring library.
               No ring was added; the die is unsealed."

So the die is 1052 × 1647 at origin (442, 442) instead of 1936 × 2531 at (0, 0), and the
precheck refuses at the first of the six size checks. **Fix 1 is only safe when the ring
actually lands** — the two are one mechanism, which is exactly why the brief ordered them
together. Arm B, whose floorplan was unfixed, keeps the slot rectangle by accident and so
reaches the fifth check instead of the first; that is not a better die, it is the same
missing ring failing one check later.

The remedy is an environment fix, not a flow fix: the image's PDK install is incomplete.
Nothing here was worked around — no GDS was edited, no ring was drawn by hand.

## 6. WHAT SURVIVED, AND WHY

* **`PL.8` = 1 and `M1.4` = 1.** Present in BOTH arms, identical. Neither is caused nor
  cured by any of the four fixes; they are not implant/well/diffusion rules and no fill
  or floorplan change touches them. Not investigated further.
* **`DF.14_MV`** — predicted to survive (it is free-space distance, unaffected by well
  severance). It does not appear on this die in EITHER arm, so this run neither confirms
  nor contradicts that prediction. NOT DETERMINED here.
* **metal1 density** did not reach target (`0.1567`, `reached: false`, 0 fill shapes
  placed), so the fill verdict is `PARTIAL`, not `PASS`. Every other metal reached it.
  Not diagnosed.
* **The seal ring**, for the reason in §5.

## 7. NOT RUN / NOT DETERMINED

* **The submitted die was never reproduced.** The 8HD-4 project, its 3958-instance
  netlist and its layouts are not on this host, and the two upstream fixes (the floorplan
  commit `a48c40c3f`, the metal-fill commit `5cccdbc8c`) are on 8HD-7, which is not
  reachable from here. Both were **re-implemented from the brief's description**, not
  cherry-picked. Every number in this document is from THIS host's own runs; none of the
  brief's numbers (1177, 817, 360, 11964, 18686, 8317) was reproduced here and none is
  claimed to have been.
* **The before/after table crosses a netlist boundary.** BEFORE is the 262-instance
  pre-DFT netlist, AFTER the 463-instance post-DFT one, because the only fixes-off arm
  that produced a die is the one whose DFT artefacts were already cached. The clean
  same-netlist control (arm C) did not converge. Both facts are in §1; neither is
  averaged away.
* **No seal ring exists on either die**, so no GR.* rule was exercised in either arm and
  the ring half of the split is untested here.
* **The `--die-um` retry ladder was never exercised** (util ~0.5%, no upsize/downsize/
  loosen fired), so the pinned-rect branch of the floorplan rewrite is covered by a unit
  test on this host, not by a flow run.
* **Three refill paths still carry the old guard** — `_build_eco_repair_tcl`,
  `_ship_signoff_spef_repair_tcl`, `_ship_wire_length_escalation_tcl` have no `project`
  in scope and were left unchanged. None fired in this run.
* **The tap prune was NOT changed.** g360 named it as a separate defect; changing it here
  would have made the attribution in §4 unreadable.
* No LVS/ERC comparison between arms, no `programs/tests` suite, no multi-corner STA
  study, no KLayout-version divergence study.
* **One existing test assertion was INVERTED, deliberately and in the open.**
  `test_filler_masters_sky130_full_set` asserted that decap variants MUST be offered to
  `filler_placement` ("Decap is the dynamic-IR margin"). Fix 2 makes that false, so the
  test is now `test_filler_masters_are_spacers_only` and its docstring carries the
  measurement that inverted it, the old wording, and what the change COSTS. It was not
  deleted and it was not weakened to passing — it asserts the opposite thing, and a
  second test pins the exclusion as PDK-agnostic by name segment.
  **The cost is real and is not paid for anywhere:** the dynamic-IR decoupling the
  decaps provided is now simply absent. Buying it back needs decap insertion and tap
  pruning decided together, in the placement step. Named, and stopped at.
* 309 tests over the touched programs pass, 27 skipped, 0 fail. The full
  `programs/tests` suite was NOT run.
* Nothing pushed, no version bumped, no rule deck altered, no GDS edited.
