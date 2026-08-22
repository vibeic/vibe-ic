# EXPERIMENT — place the fillers the layout never got, and re-measure

_Run 2026-08-20 on host 8HD-6. Tests the diagnosis in `CIRCUIT_DRC_360_FINDINGS.md`._

NDA: `<lib>` = the PDK's 5V 7-track standard-cell library; `<pdk>` = the PDK root;
the design and the shuttle operator are referred to generically.

## Verdict up front

**The confirmation failed, and the failure is the finding.**

* The six spacing/width rules went to **exactly zero**, as predicted, to the violation:
  `PP.2` 87→0, `NP.2` 83→0, `NW.2a_LV` 39→0, `NW.2b_LV` 35→0, `NW.2b_MV` 9→0,
  `DV.5` 28→0.
* **`filler_placement` run as the flow itself would run it made the die 33× worse:
  360 → 11 964.** The flow's own master list puts **decaps first**, and decaps are
  devices. 99.5–100 % of every new violation sits on a decap cell.
* Re-run with **pure spacers only**: **360 → 19**, and **all 19 were already present
  before the fill** — zero new violations.
* Of those 19: **7 are library-cell-internal**; **12 are cells 13.95–56.26 µm from any
  tap** against a 15 µm rule. Neither is a filler problem.
* **`DF.14_MV` was not fixed at all — 9 → 9.** My previous note called it "consistent
  with the same severance mechanism". It is not. That was wrong, and this caught it.

## How the filler was made to run

Not by editing the guard and not by re-running the flow. The submitted placement was
lifted out of the layout and `filler_placement` was driven directly:

1. **Placement → DEF.** Every top-level instance was read out of the unsealed layout
   (`sha256 8db0c0decb17…`, the same file `gsplit` measured) and written as a DEF.
   The placement box of each instance is its GDS bbox shrunk by the uniform 0.43 µm
   n-well overhang. Reconstruction validated before use, and it validates cleanly:
   * every placement left edge is on the **0.560 µm site grid** (exact),
   * every row bottom is on the **3.920 µm row grid** (exact), 226 distinct rows,
   * orientations are only `N` (1089) and `FS` (2869), and **no row mixes them**.
   * `ROW` records span, per row, that row's own leftmost to rightmost cell — so the
     fill covers exactly the intra-row gaps and invents no floorplan. The real core
     area is not in any artefact on this host.
2. **`filler_placement` in OpenROAD 26Q3**, in our image, one-shot
   `docker run --rm … --skip openroad -no_init -exit` (no `docker exec`, no
   long-lived container). Tech LEF + cell LEF from `<pdk>` in the same image.
3. **DEF → GDS.** The 8317 filler components were parsed out of the written DEF and
   inserted into a **copy** of the original layout, with the master definitions
   imported from the PDK's own cell GDS. Nothing in the original was altered, removed
   or redrawn: the only difference is added filler instances. Every inserted
   instance's resulting bbox was asserted equal to `(x−0.43, y−0.43, x+W+0.43,
   y+H+0.43)` — **8317 of 8317 exact, 0 mismatches**.
4. **DRC**: the operator's deck, the operator's exact option set, the operator's image
   — byte-identical to the command in `SEAL_RING_DRC_SPLIT_FINDINGS.md`. Run detached,
   each with a done-file.

### The guard's own measurement, reproduced

The Tcl block from `_build_sparse_die_aware_filler_tcl` was executed verbatim on the
reconstructed block, so the utilization is computed by **the guard's own odb code**:

```
GUARD_CORE_UTIL_PCT: 1.8669664052854362  (threshold 5.0)
```

This upgrades last night's inference to a measurement: on this placement the #684
guard **does** take the skip branch. It still is not proof that it fired in the
original run — no log from that run exists here (see NOT RUN).

## The before/after histogram

| rule | unsealed BEFORE | unsealed FILLED (flow's masters) | unsealed FILLED (spacers only) | sealed BEFORE | sealed FILLED |
|---|---:|---:|---:|---:|---:|
| `PP.2`      |  87 | **0** | **0** |  87 | **0** |
| `NP.2`      |  83 | **0** | **0** |  83 | **0** |
| `NW.2a_LV`  |  39 | **0** | **0** |  39 | **0** |
| `NW.2b_LV`  |  35 | **0** | **0** |  35 | **0** |
| `NW.2b_MV`  |   9 | **0** | **0** |   9 | **0** |
| `DV.5`      |  28 | **0** | **0** |  28 | **0** |
| `DF.13_MV`  |  70 | **8124** | **10** |  70 | 8124 |
| `DF.14_MV`  |   9 | **1971** | **9** |   9 | 1971 |
| `M1.2a`     |   0 | **1787** | **0** |   0 | 1787 |
| `M1.1`      |   0 | **82** | **0** |   0 | 82 |
| `GR.4`      |   0 | 0 | 0 | **794** | **794** |
| `GR.2`      |   0 | 0 | 0 | **19** | **19** |
| `V1.2a`     |   0 | 0 | 0 | **2** | **2** |
| `V3.2a`     |   0 | 0 | 0 | **2** | **2** |
| **TOTAL**   | **360** | **11 964** | **19** | **1177** | **12 781** |

## Does ~817 remain?

**Yes, exactly — and bit-for-bit.** `GR.4` 794, `GR.2` 19, `V1.2a` 2, `V3.2a` 2 = **817**,
identical before and after the fill in the sealed run. The filler touches the ring
half not at all. `gsplit`'s split survives a third independent test.

The predicted 1177 → ~817 did **not** happen, because the circuit half did not go to
zero: with the flow's own masters it went to 11 964, and with spacers to 19. Spacers
only would give 817 + 19 = **836**, not 817.

## Why the flow's own filler makes it 33× worse

`_discover_filler_masters_from_lef` returns decaps largest→smallest **before** fills
largest→smallest. Run with that list, greedy tiling consumed the empty sites with
decaps: **7295 of the 8317** inserted cells were `fillcap_*`.

Measured contents of the two families (merged polygon counts per master):

| cell | COMP | POLY2 | CONT | MET1 | gate area (COMP∩POLY2) |
|---|---:|---:|---:|---:|---:|
| `fill_1` / `fill_2` / `fill_4` | **0** | **0** | **0** | 2 | **0.000 µm²** |
| `fillcap_4`  | 2 | 2 | 10 | 4 | 2.040 µm² |
| `fillcap_16` | 8 | 8 | 40 | 10 | 8.160 µm² |
| `fillcap_64` | 32 | 32 | 160 | 34 | 32.640 µm² |
| `filltie`    | 2 | 0 | 5 | 2 | 0.000 µm² |

`fill_*` carries only NWELL / PPLUS / NPLUS / DUALGATE and the two power rails — the
exact four layers the diagnosis needs bridged, and **no device**. `fillcap_*` is a
decoupling capacitor: real gate, real active, real contacts, extra metal1.

So the unguarded fill dropped thousands of new `pactive`/`nactive` polygons across
silicon whose taps had been **pruned away on the assumption that it carried no
devices**, and its extra metal1 landed under existing routing:

| new violation | count | fraction sitting on a `fillcap_*` instance |
|---|---:|---:|
| `DF.13_MV` | 8124 | **99.8 %** |
| `DF.14_MV` | 1971 | **99.5 %** |
| `M1.2a` | 1787 | **100.0 %** |
| `M1.1` | 82 | **100.0 %** |

**The two halves of #684 are mutually inconsistent.** It prunes taps because empty
silicon carries no devices, and then — if the fill is allowed to run — fills that same
silicon with devices.

## What the spacer-only fill proves, and what it disproves

With `fill_64 … fill_1` only, same 8317 sites:

**Proved.** The n-well re-merges exactly as diagnosed:

| | before | after spacer fill |
|---|---:|---:|
| NWELL islands | 3305 | **128** |
| islands containing no `ntap` | 62 | **1** |
| `DF.13_MV` | 70 | **10** |

and all six spacing/width rules go to zero. **Zero new violations were introduced** —
every one of the 19 survivors is identical, same reporting cell and same coordinates,
to a violation already present before the fill.

**Disproved — a correction to the previous findings.** I wrote that `DF.14_MV` was
"consistent with the same severance mechanism; not demonstrated". Measured: **9 → 9,
not one fixed.** The reason is in the rule text I already quoted and failed to read
closely enough: `DF.13_MV` grows the tap `.and(nwell)` at each of 30 steps — reach
*through the well*, which severance breaks and filling restores. `DF.14_MV` uses
`ptap.sized(15.0.um, diamond_limit)` with **no `.and(...)`** — plain free-space
distance, which n-well severance never affected. `DF.14_MV` is a **separate defect**:
tap coverage, not fill.

The 19 survivors, characterised:

* **7 reported inside library cells** (`buf_16`, `clkbuf_2` ×2, `clkbuf_4` ×3, in
  cell-local coordinates) — internal to `<lib>`, outside the flow's reach.
* **12 at three isolated spots**, every one genuinely un-tapped in straight line:
  nearest `ntap` 13.95 / 15.54 / 15.96 / 54.08 / 56.26 µm and one with **no tap within
  the 60 µm search window at all**; nearest `ptap` 16.92 / 17.65 / 18.49 / 53.32 /
  55.43 µm and the same isolated site. Rule limit 15 µm. These are tap-coverage
  failures — the prune, or the tap grid, left these cells untied. No spacer can fix
  them, because `fill_*` contains no COMP and therefore no tap.

---

# THE GUARD FIX, described — not built

Nothing below was implemented. No flow step was changed.

## What the guard should emit instead

Today `reports/phase3/sparse_die_skip.json` is an **exemption**: the tap and fill gates
read its presence and vacuous-pass. It should be an **obligation**:

* the **region** where fill/tap was withheld, as an explicit rectangle/row list — not a
  boolean; a downstream check cannot reason about "somewhere",
* the measured utilization and the threshold it was compared against,
* `verified: false`, plus an explicit `obligations: [...]` naming the checks the skip
  may have invalidated,
* and it must be **insufficient on its own to close any gate**.

The principle in one line: *an attestation may record why a step did not run; it may
never assert that the outcome is acceptable.* Only a measurement on the resulting
artefact can do that. **A skip is a skip: it changes the artefact, so it re-opens every
check that reads the artefact — it does not close them.**

## Which gate should refuse, and on what predicate

**Step 31 (physical verification) — an identity predicate, not a cleanliness one.**
This is the predicate that would have caught tonight regardless of fillers:

> Refuse unless the layout DRC verified is byte-identical to the layout being handed on.

Step 31 records `{sha256, top_cell, die_bbox, instance_count}` of the exact file it
read. Step 37 (`gdsii_output_only_if_step_31_pv_fully_clean`) refuses to emit unless
the artefact it is about to ship carries **that sha256**. Tonight step 31 verified a
240 × 240 µm top with 1556 spacers and a 1936 × 2531 µm top with 0 spacers shipped, and
nothing compared them. Cheap, chip- and PDK-agnostic, catches the whole class.

**The tap/fill gates** (`latchup_esd_spacing_check`, the `perc_equivalent` welltap
category, `metal_fill_density_check`) — refuse on:

> a skip is attested **and** no DRC run exists whose recorded input sha256 equals the
> post-guard layout's.

That inverts the current logic: the attestation **raises** the evidence bar instead of
lowering it. Outcome is REVIEW / BLOCKED, never VACUOUS-PASS.

## The concrete form, with this experiment's numbers

1. **Scope the guard by region; do not gate it by boolean.** What #684 must prevent is
   fill over *empty* silicon. What caused these 360 is gaps *inside* the logic island
   (1051 × 1642 µm inside a 1936 × 2531 µm die). Fill every row span that contains
   placed logic; leave spans with none. Measured cost of exactly that here: **8317
   instances, 4.2 MB**. Full-die rows would be **2 229 765 sites — 10.6× more, all over
   empty silicon**. The all-or-nothing dichotomy is the bug, not the threshold value.
2. **Never fill a tap-pruned region with device-bearing cells.** Measured: the flow's
   own master order gives **11 964** violations, 33× worse than doing nothing; pure
   spacers over the identical 8317 sites give **19**. Decap insertion and tap pruning
   must be decided **together** — decap only where tap coverage is retained. As it
   stands, turning the guard off would be far worse than leaving it on.
3. **Measure tap coverage the way the rules measure it.** `tapcell_distance_um = 14.0`
   is a Euclidean margin picked against a 15 µm rule, and the prune's docstring claims
   coverage is "GUARANTEED". Neither rule is Euclidean-to-nearest-tap: `DF.13_MV` is
   reach *inside the n-well*, `DF.14_MV` is *free-space* diamond distance. 12 survivors
   sit 13.95–56.26 µm from any tap. Whatever the prune keeps must be validated against
   both metrics, not one proxy.

**Which step each belongs to:** (1) and (2) are step 17
`placement_global_detailed`; (3) is step 17's tap prune; the identity predicate is
step 31 + step 37. **Named and stopped at — I have not touched any of them.**

---

## NOT RUN / NOT DETERMINED

* **The original run's own logs were never seen.** No `SPARSE_DIE_FILL_SKIPPED` marker
  and no `sparse_die_skip.json` for the submitted die exists on this host; those are on
  8HD-4. That the guard *would* skip on this placement is now measured with the guard's
  own code (1.867 % < 5.0 %); that it *did* skip in the original run is still inferred.
* **The reconstructed DEF is not the original DEF.** It was rebuilt from the GDS. Row
  spans are per-row leftmost→rightmost cell, because the real core area is in no
  artefact here. A different core rectangle would give a different filler count and
  could give a different result at the island edge — where 12 of the 19 survivors are.
* **Nets, pins and routing were not in the DEF.** `filler_placement` does not need
  them, but OpenROAD therefore could not have avoided routing when placing decaps. Some
  part of the 1787 `M1.2a` may be an artefact of that rather than of decap insertion —
  **NOT DETERMINED**, though all 1787 do sit on decap cells and `fill_*` produced none.
* **No spacer+re-tapped variant was run.** Whether re-running `tapcell` (or a
  rule-aware prune) clears the remaining 12 was not tested; `tapcell` cannot simply be
  re-run post-placement (DPL-0005, as the flow's own comment notes).
* The 7 library-internal survivors were not investigated further.
* KLayout 0.30.9 (operator) vs 0.30.10 (ours) still untested for divergence.
* No LVS, ERC, antenna, density or Magic DRC. The `programs/tests` suite was not run.
* Nothing pushed, no version bumped, no flow step changed, no rule deck altered, and
  the original layouts were never modified — the filled layouts are new files.
