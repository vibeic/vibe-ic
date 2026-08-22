# FINDINGS — the 360 KLayout DRC violations that are the CIRCUIT's own

_Measured 2026-08-20 on host 8HD-6. Companion to `SEAL_RING_DRC_SPLIT_FINDINGS.md`,
which split the operator's 1177 into 817 (seal ring) + 360 (circuit). This measures
the 360._

NDA: the PDK, its foundry/node, the shuttle operator and the design are referred to
generically below. `<lib>` = the PDK's 5V, 7-track standard-cell library. `<pdk>` =
the PDK root inside the operator's precheck image.

## Provenance of what was measured

Everything here is measured from artefacts already on this host:

| artefact | path |
|---|---|
| unsealed violation database (360 items) | `…/scratchpad/gsplit/out_unsealed/drc.klayout.lyrdb` |
| unsealed layout | `…/scratchpad/gsplit/gds_unsealed/<design>.gds` |
| rule decks | copied out of the operator's precheck image (id `4f58bb5de315`, KLayout 0.30.9) |
| our own published sign-off run | `benchmark-data/ic/<design>/v1.9.96_<pdk>/` |

The three paths named in the brief (`_gk_pc2/runs/RUN_2026-08-19_19-22-25/…`,
`_spmslot_run/debug_gds_unsealed/…`, `~/benchmark-data/…`) do **not** exist on this
host — they are on 8HD-4. `gsplit`'s scratchpad copies of the same two artefacts were
used instead, and our published run was found under `vibe-ic/benchmark-data/`.

---

## 1. THE EIGHT RULE TEXTS, quoted from the deck

Verbatim `output(...)` strings and the executable line above each, from
`<pdk>/libs.tech/klayout/tech/drc/rule_decks/`:

**`pplus.rb:49`**
```ruby
pp2_l1 = pplus.space(0.4.um, euclidian)
pp2_l1.output('PP.2', 'PP.2 : min. pplus spacing : 0.4µm')
```

**`nplus.rb:49`**
```ruby
np2_l1 = nplus.space(0.4.um, euclidian)
np2_l1.output('NP.2', 'NP.2 : min. nplus spacing : 0.4µm')
```

**`comp.rb:605`** (`df13_ntap_sized_by15` = `ntap` grown in 0.5 µm steps to 15 µm,
`.and(nwell)` after **every** step — the reach is measured *inside the n-well*, not
as a straight line)
```ruby
pactive_56v = pactive.overlapping(dualgate)
df13_l1 = pactive_56v.not_interacting(df13_ntap_sized_by15)
df13_l1.output('DF.13_MV',
               'DF.13_MV : Max distance of Nwell tap (NCOMP inside Nwell) from (PCOMP inside Nwell): 15um')
```

**`comp.rb:645`**
```ruby
nactive_56v = nactive.overlapping(dualgate)
df14_poss_bad_active = nactive_56v.not_interacting(ptap.sized(15.0.um, diamond_limit))
df14_good_active = df14_poss_bad_active.sep(ptap, 15.0.um).polygons
df14_l1 = df14_poss_bad_active.not_interacting(df14_good_active)
df14_l1.output('DF.14_MV',
               'DF.14_MV : Max distance of substrate tap (PCOMP outside Nwell) from (NCOMP outside Nwell): 15um')
```

**`nwell.rb:71`** (`connected_nwell_3p3v, unconnected_nwell_3p3v = conn_space(nwell, 0.6, 1.4, euclidian)`)
```ruby
nw2a_l1 = connected_nwell_3p3v.not_inside(ymtp_mk).not_interacting(v5_xtor).not_interacting(dualgate)
nw2a_l1.output('NW.2a_LV',
               'NW.2a_LV : Min. Nwell Space (Outside DNWELL) [Equi-potential],
                Merge if the space is less than. : 0.6µm')
```

**`nwell.rb:88`**
```ruby
nw2b_l1 = unconnected_nwell_3p3v.not_interacting(v5_xtor).not_interacting(dualgate)
nw2b_l1.output('NW.2b_LV', 'NW.2b_LV : Min. Nwell Space (Outside DNWELL) [Different potential]: 1.4µm.')
```

**`nwell.rb:95`** (`connected_nwell_5p0v, unconnected_nwell_5p0v = conn_space(nwell, 0.74, 1.7, euclidian)`)
```ruby
nw2b_l1 = unconnected_nwell_5p0v.overlapping(dualgate)
nw2b_l1.output('NW.2b_MV', 'NW.2b_MV : Min. Nwell Space (Outside DNWELL) [Different potential]: 1.7µm')
```

**`dualgate.rb:56`**
```ruby
dv5_l1 = dualgate.width(0.7.um, euclidian)
dv5_l1.output('DV.5', 'DV.5 : Min. Dualgate width. : 0.7µm')
```

### Correction to the brief's working hypothesis

The brief proposed these are "the rules that govern spacing AROUND devices of
different voltage classes, and a design mixing LV and MV devices is exactly where
they bite." **Measured: there is no LV/MV mixing.** Every placed instance is from the
single 5V library `<lib>`; DUALGATE covers **100 %** of COMP (`comp.not(dualgate)`
= 0 polygons, 0.00 µm²), so every device is correctly classified MV. `NW.2a_LV` and
`NW.2b_LV` fire not on LV *devices* but on n-well *gaps* that happen not to touch
DUALGATE — the `_LV` suffix is selecting a region, not a device class. The voltage-
class hypothesis is negative.

---

## 2. ONE DEFECT, NOT EIGHT — and not eight relationships either

**One defect: no filler/spacer cells were ever placed. The placement has 3537
unfilled intra-row gaps.**

### The instance inventory

Of 3958 top-level instances:

| master class | count |
|---|---|
| `<lib>__filltie` (LEF `CLASS core WELLTAP`) | 3331 |
| real logic + `__antenna` + `__tiel` | 627 |
| **`<lib>__fill_*` / `__fillcap_*` (LEF `CLASS core SPACER`)** | **0** |
| `<lib>__endcap` | 0 |

The library ships spacers `fill_1/2/4/8/16/32/64` at 0.56/1.12/2.24/4.48/8.96/17.92/
35.84 µm — a binary set that tiles **any** multiple of the 0.56 µm site. Every one of
the 3537 gaps was fillable. None was filled.

### The library constants that turn gaps into violations

Measured over all 36 cell masters used, all 72 left/right edges — **no exceptions**:

| layer | overhang beyond the placement box |
|---|---|
| NWELL | 0.430 µm |
| PPLUS | 0.200 µm |
| NPLUS | 0.200 µm |
| DUALGATE | 0.280 µm |

Abutted cells therefore merge every layer. A gap of width *g* leaves:

* implant space `g − 0.40`
* n-well space `g − 0.86`
* and, where a row gap sits under/over a filled row, the only DUALGATE left is the
  inter-row overlap band, `2 × 0.28 = 0.56 µm` tall.

That single table predicts all eight rules:

| gap *g* | implant `g−0.40` vs 0.40 | n-well `g−0.86` vs 0.6 / 1.4 / 1.7 | dualgate |
|---|---|---|---|
| **0.56** (1 site) | **0.16 → PP.2, NP.2** | −0.30, merged — clean | merged |
| **1.12** (2 sites) | 0.72 clean | **0.26 → NW.2a_LV, NW.2b_LV, NW.2b_MV** | 0.56 neck **→ DV.5**; n-well severed **→ DF.13/14** |
| **1.68** | 1.28 clean | **0.82 → NW.2b_LV, NW.2b_MV** | ditto |
| **2.24** | 1.84 clean | **1.38 → NW.2b_LV, NW.2b_MV** | ditto |
| **≥ 2.80** | clean | ≥1.94 clean | ditto |

The last row is why only 360 violations come out of 3537 gaps: once a gap is ≥2.80 µm
the geometry has simply separated far enough, and only the two tap-distance rules and
DV.5 still fire.

### The coordinate evidence

Critical dimension of every one of the 360, read out of the lyrdb:

| rule | n | measured critical dimension | predicted by |
|---|---|---|---|
| `PP.2` | 87 | **0.160 µm × 87 — every one** | 0.56 − 2×0.20 |
| `NP.2` | 83 | **0.160 µm × 83 — every one** | 0.56 − 2×0.20 |
| `DV.5` | 28 | **0.560 µm × 28 — every one** | 2 × 0.28 inter-row band |
| `NW.2a_LV` | 39 | **0.262 µm × 39 — every one** | 1.12 − 2×0.43 |
| `NW.2b_LV` | 35 | 0.262 ×9, 0.822 ×11, 1.382 ×12 (32/35) | 1.12 / 1.68 / 2.24 gaps |
| | | 1.334 ×3 | not on the lattice — see §5 |
| `NW.2b_MV` | 9 | 0.822 ×5, 1.382 ×4 — every one | 1.68 / 2.24 gaps |
| `DF.13_MV` | 70 | not a spacing (see below) | |
| `DF.14_MV` | 9 | not a spacing (see below) | |

`0.160` cannot arise from anything except a 0.56 µm gap given a 0.20 µm overhang;
`0.262` cannot arise from anything except a 1.12 µm gap given a 0.43 µm overhang.
The agreement is exact, to the nanometre, on 271 of 271 spacing/width violations.

Worked example, `PP.2` at (932.120, 2061.124) — the two PPLUS polygons are
`915.400→932.040` and `932.200→933.720`; the cells are `<lib>__dffq_1`
(placement box right edge 931.840) and `<lib>__filltie` (left edge 932.400). Gap
0.560 µm, implant separation 0.160 µm. A single `fill_1` closes it.

### DF.13_MV / DF.14_MV — the same defect, one step removed

These are "max distance to a tap" rules and their reported polygon is the offending
`pactive`/`nactive` itself, so it carries no spacing to compare. They were tested
differently, and the result is categorical:

* Every tap in the design comes from a `filltie`: exactly **3331 ntap polygons,
  3331 ptap polygons, 3331 filltie instances**. No other master contributes one.
* Because DUALGATE/implant merge across a 0.56 µm gap but n-well does not merge
  across anything ≥1.12 µm, the n-well is shattered into **3305 islands** (median
  area 5.13 µm²) across 226 placement rows.
* **62 of those islands contain no ntap at all.**
* Recomputing DF.13_MV from the deck's own recipe yields 73 failing `pactive`
  polygons, and **73 of 73 sit inside a tap-less island — 100 %.**

The deck grows the tap by 15 µm *`.and(nwell)` at every 0.5 µm step*, so the reach is
measured **through the n-well**. Straight-line distance to the nearest tap is only
2.91–16.21 µm for these — they are not far away, they are **cut off**. Fill the gaps
and the n-well re-merges and the reach is restored.

Note the flow already knew about these two rules: `pdk_registry.json` sets
`tapcell_distance_um = 14.0` with the comment *"sits under the PDK's own 15um
max-tap-distance rule for this 5V library — DF.13_MV and DF.14_MV … both state 15um"*.
14 µm is a correct **Euclidean** margin. The rule is not Euclidean.

### Verdict

Eight rule names, **one defect**, expressed through three geometric consequences of
the same missing cells: implant separation (170), n-well separation + dualgate neck
(111), and n-well severance stranding taps (79). 360 total.

---

## 3. WHICH CELLS OR MACROS

**No cell or macro is at fault. There are no macros** — the design is 3958 flat
standard-cell instances of 36 masters, all from `<lib>`, plus no hard IP.

The violations are not *inside* any master. Measured: `PP.2`/`NP.2`/`DV.5` sit at
0.15 µm from the nearest cell-placement edge in 191 of 198 cases — i.e. **on the
abutment boundary**, in the empty site between two cells. `NW.2a_LV`/`NW.2b_LV`/
`NW.2b_MV` (83) sit in space contained by **zero** instances. The 19 items the deck
attributes to a library cell rather than to the top cell are hierarchical reporting
of the same boundary geometry.

The answer to "which cells" is therefore **the cells that are absent**: 3537 empty
sites' worth of `<lib>__fill_*`.

---

## 4. WHY OUR OWN SIGN-OFF DID NOT SEE THEM

The brief offered three possibilities. Measured, in order:

**(a) Is it a different deck? No.** Our step-31 provenance records
`klayout -b -r <pdk>/libs.tech/klayout/tech/drc/<pdk>.drc` — the same deck file
name and the same PDK variant directory the operator runs. Ours was KLayout 0.30.10,
the operator's 0.30.9.

**(b) Did it run with different options? No — the omissions are benign.** Our command
passes only `input`/`report`; it omits `topcell`, `decks`, `variant`, `workers`,
`threads`. Read from the deck's own `options.rb:292 DEFAULTS`: `variant` defaults to
the same variant we target, `decks` defaults to `all` (**broader** than the operator's
`all,-antenna,-density,-cup`), `topcell` defaults to auto-detect. No option we dropped
could hide a violation.

**(c) Was it never run on THIS layout? Yes — and it is worse than that.**

Our published sign-off run verified a **different layout**:

| | what the operator checked | what our step 31 signed off |
|---|---|---|
| file | `<design>.gds` | `chip_top.gds` |
| top cell | `<design>` | `chip_top` |
| die | 1936 × 2531 µm (4.90 mm²) | 240 × 240 µm (0.058 mm²) |
| std-cell instances | 3958 | 2269 |
| `fill_*`/`fillcap_*` | **0** | **1556** |
| `filltie` | 3331 | 387 |
| core utilization | **0.66 % of die / 1.87 % of cell extent** | 75.5 % / 100 % |
| KLayout DRC, operator's deck+options | **360** | **0** |

The last row was measured, not assumed: the operator's deck and the operator's exact
option set were run against our own `chip_top.gds` inside the operator's own image.
It returns `DRC RESULT: SUCCESS (0 violations)` in 14.3 s over 57 600 µm².

So **our sign-off was honest about what it was given.** Its report is empty because
the layout it verified really is clean. The 360 were never in front of it. The
submitted die is a second, much larger implementation whose own step-31 record lives
on 8HD-4 and which I could not inspect (see §6).

### The structural hole, which is visible without 8HD-4

This is the part worth more than the 360.

`phase3_one_shot_runner.py` carries the **#684 sparse-die fill guard**. Below a
core-utilization threshold (`_SPARSE_DIE_FILL_UTIL_PCT_DEFAULT = 5.0`) it:

* **skips `filler_placement` entirely** (`_build_sparse_die_aware_filler_tcl`,
  emitting `SPARSE_DIE_FILL_SKIPPED`), and
* **runs `tapcell` full-die and then prunes it** by a *Euclidean* locality test
  (`_build_tapcell_prune_tcl`, "keeps only the full-die taps that have a PLACED
  non-tap core cell within the latch-up neighbourhood (2x the tapcell distance)").

The submitted die's artefact is exactly what that path emits: **zero spacers, 3331
surviving taps**, at 0.66–1.87 % utilization against a 5.0 % threshold. Our own
`chip_top.gds`, at 75–100 %, is above the threshold and duly has 1556 spacers.

The guard's own docstring claims *"Coverage is GUARANTEED chip-AGNOSTICally … so
every placed cell retains a well-tie within the PDK max-tap-distance rule (PERC
latch-up tap-spacing PASS)"*. **That guarantee is Euclidean and the DRC rule is not.**
Skipping the spacers severs the n-well the rule must reach through; the prune then
measures reach in straight lines. 62 tap-less n-well islands and 79 DF.13/DF.14
violations are the result.

And the flow does not catch it, by construction. Its own regression test
`test_v1_0_56_round8_sparse_die_signoff_consistency.py` documents that when the guard
fires, the runner writes `reports/phase3/sparse_die_skip.json` and the downstream
gates — the latch-up well-tap presence check, `latchup_esd_spacing_check`, the
`perc_equivalent` welltap category, and `metal_fill_density_check` — **read the
attestation and VACUOUS-PASS**. So the guard removes cells from the layout and
simultaneously silences every gate that would have noticed. **No gate re-runs DRC on
the post-guard layout to ask whether the skip was DRC-safe.** On this design it was
not, by 360.

Step 37 is literally named `37_gdsii_output_only_if_step_31_pv_fully_clean`. That
interlock held — on `chip_top`.

---

## 5. WHAT IS LEFT

**Not fixed, and deliberately not attempted.** No layout was edited, no geometry
deleted, no rule relaxed. Per the brief, the fix belongs in a flow step, so it is
named and stopped at:

* **Step 17 `placement_global_detailed`** owns `filler_placement` and the #684 guard
  in `phase3_one_shot_runner.py`. Whether the guard should fill the *occupied* region
  while still not tiling empty silicon — the gaps here are inside a 1051 × 1642 µm
  logic island, not out over empty die — **is your call, not mine.**
* Whichever gate should re-verify DRC after the guard fires is likewise a step change.

Open, un-run, or unresolved:

* **3 of 35 `NW.2b_LV` measure 1.334 µm**, which is not on the 0.56 µm lattice
  (1.12/1.68/2.24 → 0.262/0.822/1.382). Cause NOT DETERMINED. The other 32 are exact.
* **`DF.14_MV` (9) was not individually proven** the way DF.13_MV was. 3 of the 9 lie
  16.92–18.52 µm from the nearest ptap in straight line — already over the 15 µm rule
  — and 6 return no ptap within the 40 µm search window I used. Consistent with the
  same severance mechanism; not demonstrated to the standard DF.13_MV was.
* My independent recount of `PPLUS.space(<0.4)` on raw layer 31/0 gives **73**
  edge-pairs against the deck's **87**. The deck's `pplus` is a derived layer and runs
  hierarchically in `deep` mode; the discrepancy is my simplification, not a finding.
  The per-violation 0.160 µm measurement (87/87) is taken from the deck's own output
  and is unaffected.
* My row scan found **62** one-site gaps between consecutive placed cells, against
  87 `PP.2` + 83 `NP.2`. The scan counts only gaps *between two placed cells* in a
  row and not row-end gaps, and one gap yields separations in more than one implant
  band. The ratio is not reconciled instance-by-instance.
* **Whether filling the gaps actually clears all 360 was NOT tested.** Testing it
  means producing a modified layout, which the brief forbids.

---

## 6. NOT RUN / NOT DETERMINED

* **The submitted die's own step-31 record was never inspected.** It is on 8HD-4
  (`_gk_pc2/runs/RUN_2026-08-19_19-22-25/`, `_spmslot_run/`), which is not reachable
  from 8HD-6. So "our DRC ran on the submitted layout and passed it" is **NOT
  DETERMINED** — what is determined is that our *published* sign-off artefact is a
  different, genuinely clean layout.
* **No `SPARSE_DIE_FILL_SKIPPED` marker or `sparse_die_skip.json` was found** for the
  submitted die. The guard firing is inferred from the artefact (0 spacers, 3331
  pruned taps, 0.66–1.87 % utilization vs a 5.0 % threshold) and from the code path
  that uniquely produces that combination. **Not confirmed from a log.**
* The 0.30.9 vs 0.30.10 KLayout difference between the operator's image and ours was
  **not** tested for behavioural divergence.
* Our own EDA image's copy of the deck was not diffed against the operator's; only
  the operator's copy was read.
* No LVS, ERC, antenna, density or Magic DRC work was done — KLayout DRC only.
* The full `programs/tests` suite was **not** run, per the brief. Only
  `test_v1_0_56_round8_sparse_die_signoff_consistency.py` was *read*, not executed.
* Nothing was pushed; no version was bumped; no flow step was changed.
