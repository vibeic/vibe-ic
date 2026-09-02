# subservient × gf180mcuD — the first non-PASS is metal density, and why

Measured 2026-09-02/03 on **8HD-4**, host load 60–88 (other lanes active; every
number below is geometry or a deck verdict, neither of which load can move).
Plugin tree **v1.16.45 / `79d3ebbe8ff8`** for the write-up; the run measured is
arm C2 on tree `030b86c544`, image **`sha256:190b37be3407…`** (the pinned
`sha256:66c33ff2e057…` with only `/foss/tools/openroad/bin/openroad` replaced —
see `router_ns_metal_convergence_criterion.md`).

## The first non-PASS, verbatim

```
FAIL   drc      violations=2 (user=2, stdcell=0) report=drc.rpt top_rules: M2.4=1, M3.4=1
```

Everything before it passes: `synth`, `prelayout_signoff`, `pnr` (×2),
`pdn_em_resize`, `pad_side_constraint`, `signoff_spef_repair`, `gds`. After it,
`lvs` PASSes. So this is the **first** thing the flow gets wrong on a design
whose routing is now clean.

The rules, from the deck's own text:

> `M2.4 : Metal2 coverage over the entire die shall be >30% … Customer needs to
> ensure enough dummy metal to satisfy Metal2 coverage : 30%`
> `M3.4 : metal3 coverage over the entire die shall be >30% …`

## Which of the three it is: a FLOW problem

Not the design, and not measuring the wrong subject. Three measurements say so.

### 1. Canonical Step 34 added no metal at all
Step 34 is named *"Metal Fill (ECO-aware density fill insertion)"*. What it
actually ran was OpenROAD `filler_placement` — a **standard-cell row** filler:

```
metal_fill.done:  # fillers placed: 0
sha256 filled.def == sha256 routed.def == 64d46d83adaf0f30…
```

`filled.def` is **byte-identical** to `routed.def`. The 6284 `fill_*`/`fillcap_*`
instances in the DEF are row fillers placed earlier by PnR; they occupy cell
area and cannot move metal-layer coverage.

### 2. The gate PASSed while its own evidence said it had not measured
`reports/phase2/gates/metal_fill_density.json`:

```
per_layer_density_verified : false     layers_ok : 0     layers_bad : 0
WARNING FILL_NOT_LARGER : filled.def (3602343B) is not larger than routed.def
                          (3602343B) — fill may be missing
INFO PER_LAYER_DENSITY_NOT_VERIFIED_HERE : … 0 layer values examined;
                          window [20.0%, 80.0%] not applied by this gate
pass : true
```

It concluded PASS from `row_utilization_pct=100.0` plus the 6284 row fillers —
i.e. from cell-area fill, on a gate whose name is metal-fill **density**. The
question the deck then fails is the one this gate declined to ask.

### 3. The measured coverage, on the shipped GDS
416 × 416 µm die, 173 056 µm²:

| layer | drawn (x/0) | dummy (x/4) | total | rule |
|---|---|---|---|---|
| Metal1 | 31.71 % | — | — | passes |
| **Metal2** | 9.82 % | 12.20 % | **22.02 %** | M2.4 needs > 30 % |
| **Metal3** | 11.17 % | 13.58 % | **24.75 %** | M3.4 needs > 30 % |
| Metal4 | 28.18 % | — | — | not flagged |
| Metal5 | 9.41 % | — | — | not flagged |

Short by ~8 pp on Metal2 and ~5 pp on Metal3. Well inside what dummy fill
supplies at any tapeout — the die is >75 % free on both layers.

## The flow HAS a dummy-metal fill, and it is not usable here

`phase3_one_shot_runner._GDS_DUMMY_FILL_PY` exists and is driven from
`input/pdk/bridge/signoff_config.json → "dummy_fill"`. No such file exists in a
gf180mcuD project (`find … -name signoff_config.json` → nothing), so it never
runs. Wiring it naively does not work either, and this was measured rather than
assumed — three runs of the flow's own fill, each followed by the full sign-off
deck:

| fill margin | Metal2 cov | Metal3 cov | deck result |
|---|---|---|---|
| (none — as shipped) | 22.02 % | 24.75 % | `M2.4`=1, `M3.4`=1 — **2 total** |
| 0.65 µm (the code's default) | 24.80 % | 25.50 % | `DM2.3`=31557, `DM3.3`=34113 — **65 670** |
| 2.0 µm | 21.97 % | 24.51 % | `M2.4`=1, `DM2.3`=14263, `DM3.3`=16254 — **30 518** |
| 3.0 µm | 18.93 % | 21.75 % | `M2.4`=1, `M3.4`=1, `DM2.3`=11509, `DM3.3`=13738 — **25 249** |

Coverage falls as the margin rises, so no margin satisfies both requirements.

### The mechanism, at the line
`rule_decks/dummy_metal.rb`:
```ruby
dm_3_l1 = metal_dummy.separation(metal_drawn, 2.um, euclidian)
```
and `generic_layers.rb`:
```ruby
extract_single_layer_from_design.call(:metal2_dummy, 36, 4)
```
So the deck reads **dummy metal on `36/4` and circuit metal on `36/0`** (`42/4`
vs `42/0` for Metal3), and requires 2 µm between them. The shipped GDS already
carries dummy metal — 2436 shapes / 12.20 % on `36/4`, 2531 / 13.58 % on `42/4`
— placed by the streamout, not by our flow.

The fill wrote its tiles onto the layer named in its spec. Aim that at `36/0`
and every tile becomes **circuit** metal sitting inside 2 µm of the existing
`36/4` dummy — which is exactly the DM2.3/DM3.3 explosion above, and its count
tracks the tile count (35 215 tiles → 65 670; 11 027 → 30 518; 8 515 → 25 249).

**And the fill cannot simply be re-aimed at `36/4`**, because of a defect in our
own program: `_GDS_DUMMY_FILL_PY` builds its keep-out from
`existing = pya.Region(tc.begin_shapes_rec(li))` — shapes on **the one layer it
is writing to**. Filling `36/4` therefore gives it no model of the `36/0`
circuit metal it must stay 2 µm away from. A PDK whose dummy metal lives on a
different datatype from its circuit metal is outside what this routine can
express.

## What was NOT done, deliberately
No fix is landed. Re-aiming the fill needs a keep-out over a *set* of layers,
and shipping that would trade 2 violations for tens of thousands until it is
right — the acceptance a flow-level fill change requires (corpus sweep, zero
false positives, BLOCKING/ADVISORY declaration) has not been run.

This is **not** blocked on the pinned-image decision. It is downstream of a route
that already converges; the router question is settled evidence and is the
owner's call, and nothing here needs it.
