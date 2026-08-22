# HANDOFF — chip-agnostic PnR DPL-0036 legalization fix

**Worktree:** `/home/reyerchu/vibe-ic-wt-dpl-legalize`
**Branch:** `fix/dpl-legalize-timing-buffers` (local only — **NOT pushed**)
**Base commit:** `83f287a1` (main, [v1.5.60])
**Local commit:** `f2487bffa6bdd4f6393113a3a27ede478a543968` (3 files: fix + 2 tests; this HANDOFF left uncommitted in the worktree root)

> **Version:** intentionally **NOT bumped**. Reassign the version at land —
> today a rebase silently ate a version bump due to a collision. No version
> string is touched in this diff.

---

## What & why

### Symptom (real evidence)
`campaign_v1565/subservient/converge_1.5.65_gf180mcuD/phase3/stage3/pnr/openroad.log`
(the prompt's `v1574` path did not exist; the matching run — byte-identical
numbers: 564 buffers/155 nets, 13 fails, Placed 281730.8 / Free 623897.8,
density 0.38 — is this `v1565` one):

```
[INFO RSZ-0038] Inserted 564 buffers in 155 nets.
[INFO DPL-0034] Detailed placement failed on the following 13 instances: place2769 ...
[ERROR DPL-0036] Detailed placement failed inside DPL.
Error: pnr.tcl, 137 DPL-0036
```

The flow **dies at pnr.tcl:137** — the first, **unguarded** `detailed_placement`
right after `global_placement` — so `placed.def` is never written and Step-17
`placement_legality_check` FAILs on the missing DEF.

### Root cause (measured, not guessed)
- The 13 `place####` are resizer buffers inserted **inside**
  `global_placement -timing_driven` (its internal repair_design) on ultra-high
  fanout — `i_clk` fanout **1273** → 564 buffers.
- All 13 are the **widest** buffers: `buf_20` (34.72 µm = **62 sites**, ×4) and
  `buf_16` (28.0 µm = **50 sites**, ×9). Confirmed from the post-GPL DEF +
  cell-LEF widths. **Not** at the die edge (x=145–623 µm, y=189–655 µm inside
  the 839 µm die); floorplan.def has **no FIXED macros and no BLOCKAGES**.
- Die is only **42.2 %** utilized, but at that utilization the placement is
  spread ~uniformly → the free area is fragmented into short gaps. **No
  contiguous run of 62 empty sites exists anywhere reachable.** PROVEN: a
  full-die diamond search (`-max_displacement {2000 2000}` → ±3571 sites ×
  ±510 rows, covering the die several times) still leaves the 4 `buf_20`
  un-placed (`check_placement` → DPL-0033). So displacement escalation alone
  is **necessary but not sufficient**; the giant buffers must be prevented.
- Regression origin: the earlier **successful** gf180-subservient run used
  `global_placement -routability_driven -density 0.4` **without**
  `-timing_driven` — its first `detailed_placement` had 0 failures. Adding
  `-timing_driven` (template default) moved buffer insertion *before* the
  unguarded legalize.

### Fix (chip/PDK-agnostic, program-first, measured — no design/cell literal)
`phase3_one_shot_runner.py`: new `_legalize_escalation_tcl()` replaces the bare
`detailed_placement` at the primary-placement site with a 4-tier escalating,
**guarded** legalizer:
1. default diamond window — **byte-identical downstream for any design that
   already legalizes** (zero regression on the common path);
2. on DPL failure → retry with full-die `-max_displacement {die_w die_h}`
   (measured die geometry; recovers the 50-site `buf_16` → 13→4);
3. still failing → discover the physically **widest optimizer buffer master**
   at runtime (`get_lib_cells` + `is_buffer` + odb master `getWidth` — no cell
   name literal), `set_dont_use` it, re-run `global_placement` (identical
   flags) + full-die legalize, so repair rebuilds a legalizable **buffer tree**
   of narrower cells (4→**0**);
4. else **hard-`error`** — a genuine geometry/capacity problem the die-sizing
   logic must own. It never continues with overlapping cells (which would swap
   DPL-0036 for a DRC-short / LVS-mismatch downstream).

---

## Gate results

### Negative control — `tests/test_dpl_legalize_timing_buffers.py`
Verified **both** directions:
- against **pre-fix** `phase3_one_shot_runner.py` (from `HEAD`): **6/6 FAIL**
  (incl. the two core controls: bare-legalize-forbidden and measured-die
  escalation; and an `AttributeError` because the helper doesn't exist).
- against **post-fix**: **6/6 PASS**.

### Existing suite (no regression)
- `test_phase3_routability_driven_placement.py` + `test_v0_3_39_issue581_pnr_tcl_syntax.py`: **31 passed, 1 skipped**.
  (Updated `_gp_cmd_lines` to pin the *primary* col-0 placement and added
  `_gp_fallback_lines` for the guarded fallback — the "exactly one primary
  placement" invariant stays precise, not weakened.)
- Full pnr/placement/tcl-related subset (`-k "pnr or placement or routab or
  legal or syntax or tcl or dpl"`): **647 passed, 7 skipped**.

### Real-cell validation (container `ghcr.io/vibeic/vibeic-eda:0.2.29`, local image; OpenROAD 26Q3; gf180mcuD; NO docker pull)
Reproduction faithful (byte-identical 13-instance failure). Fix run end-to-end
on the **real** subservient netlist (fixed full `pnr.tcl` mirroring the
generator's new emission):
```
DPL_LEGALIZE_ESCALATE1: default window failed (DPL-0036)      → 13 fails
DPL_LEGALIZE_ESCALATE2: full-die {839 839} um                 → 4 fails
DPL_LEGALIZE_DONTUSE_WIDEST_BUFFER: gf180mcu_fd_sc_mcu7t5v0__buf_20
DPL_LEGALIZE_OK_AFTER_DONTUSE                                  → 0 fails
```
- `Total Placement Failures: 0`, **`check_placement` clean** (isolated
  post-GPL harness), and **`placed.def` is written** (the artifact the Step-17
  gate reads).
- **No timing regression:** pre-CTS worst slack **−21.33 ns vs −21.44 ns**
  baseline (marginally better; excluding `buf_20` is compensated by buffer
  trees). The widest buffer is discovered at runtime → PDK-agnostic.

> NOTE on downstream (route/DRC/LVS/multi-corner): the change is
> **placement-only and function-preserving** (cells moved; one buffer master
> swapped for equivalent trees — no logic/connectivity change), and the die's
> deep pre-CTS setup deficit (−20 ns, 1092 endpoints) is a **pre-existing,
> unrelated** condition (present in the earlier run that routed DRC-0/LVS-clean).
> The full route→DRC→LVS→multi-corner signoff should be confirmed by the
> gatekeeper's standard full-campaign run; it cannot be the source of a
> DPL-0036 and the placement it consumes is now legal.

---

## ⚠️ Second, newly-EXPOSED defect (same class, different stage) — needs a follow-up land

Running the **fixed** full flow end-to-end revealed a SECOND unguarded
`detailed_placement` — the **post-hold** one (template ~line 10133; original
`pnr.tcl:708`, `pnr_fixed.tcl:743`). The original v1565 run **never reached it**
(it died at line 137), so my primary fix EXPOSED a pre-existing latent failure —
it did **not** create it, and this is the **same failure mode** (DPL-0036), not
a worse one. But it means PnR does not yet COMPLETE for this particular
high-fanout-clock design.

Root cause (measured, from the fixed run's `post_cts.def`): CTS is emitted with
a **single-cell** `-buf_list {clkbuf_4}` and the **widest** clock buffer as
`-root_buf {clkbuf_16}` (50 sites). With only a weak tree buffer available, CTS
uses **130× `clkbuf_16`** (50-site) roots for the 1273-sink clock — which
cluster and cannot legalize (post-hold: 87 fails; full-die displacement still
53 fails; `check_placement` DPL-0033). Displacement escalation ALONE does not
resolve this (unlike the primary site's `buf_16`).

Validated remedy (container, real cells, from the fixed `placed.def`): give CTS
a **graded** `buf_list` **and a narrower root** —
`clock_tree_synthesis -buf_list {clkbuf_2 clkbuf_4 clkbuf_8} -root_buf clkbuf_8`
→ CTS OK, post-CTS `detailed_placement` **0 failures at the DEFAULT window**,
`check_placement` clean.

IMPORTANT nuance (measured): a graded `buf_list` while **keeping** the wide
`clkbuf_16` root does **not** help (it made it *worse*: 125 fails) — CTS still
places many 50-site roots. The root MUST be narrowed (`clkbuf_8`, 26 sites).
That narrows the clock-root drive → **clock skew/insertion-delay changes** →
this is exactly why it needs multi-corner signoff and belongs in a follow-up
land, not a blind change here. (Graded clock-buffer lists are standard
ORFS/OpenLane practice; the current single-cell `buf_list` + widest-cell root is
what forces the un-legalizable wide-root overuse.)

I did **not** land this here because it is a DISTINCT defect (CTS buffer
selection, not `repair_design`), it changes the shipped clock-tree structure
(multi-corner **skew/timing** implications that need the full signoff this
bounded task can't run), and the fix belongs in the PDK-driven `clk_buf` /
`clk_buf_root` selection (`phase3_one_shot_runner.py` ~10442-10459 / the PDK
registry `clk_buf_cell`), emitted PDK-agnostically (enumerate clock buffers,
build a graded subset + a root no wider than the legalizable cap). Recommend a
follow-up land with signoff-verified skew.

## Files changed
- `vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py`
  — add `_legalize_escalation_tcl()`; emit `{_gp_cmd}` + `{_legalize_block}`
  in place of the bare `detailed_placement`.
- `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_dpl_legalize_timing_buffers.py`
  — new negative-control suite.
- `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_phase3_routability_driven_placement.py`
  — `_gp_cmd_lines` now pins the primary placement; add `_gp_fallback_lines`.
