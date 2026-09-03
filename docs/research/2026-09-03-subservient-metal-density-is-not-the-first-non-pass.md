# subservient × gf180mcuD — the first non-PASS is the ROUTER, and the fill room is 43%

Measured 2026-09-03 on **8HD-8** (192.168.1.114), host load 18–60 (other lanes
active; every number below is geometry or a step verdict, neither of which load
can move). Plugin tree **v1.16.82 / `637cdf091`** (`origin/main` at measurement
time), image `ghcr.io/vibeic/vibeic-eda:0.2.47`, PDK `gf180mcuD` from the
in-container `ciel` tree
(`.../versions/b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0/gf180mcuD`).

Design tree: `benchmark-data/ic/subservient` copied to a scratch run dir with
`phase3/` removed, then
`phase3_one_shot_runner.py <run> --pdk gf180mcuD --allow-pdk-target-mismatch
--allow-oss-pdk-fallback`. One run, start 05:11, finish ~08:46.

This page exists to **contradict two things that are currently written down**,
and it does it with numbers rather than argument.

## 1. The first non-PASS is `pnr`, not `drc`

Verbatim from the run's own `reports/orchestrator/phase3_one_shot.json`:

```
FAIL   pnr   ROUTE_NOT_CONVERGED: detailed route completed with 1 violations
             remaining (final DRT-0199), by type/layer (from the router's own
             DRC report `routed_router.drc.rpt`, which this run wrote and whose
             1 record(s) reconcile with the published count):
             NS Metal x1 on Metal2; net(s): net2654. Die 1234x1234µm
SKIP   drc   GDS missing: .../phase3/stage3/pnr/chip_top.gds
SKIP   lvs   LVS skipped: upstream pnr step is FAIL
```

`drc` never ran. **No GDS was written, so the M2.4 / M3.4 density verdict on
this tree is NOT MEASURED** — not passed, not failed. Anything downstream of
`pnr` on this tree is NOT MEASURED for the same reason.

The flow also declined to grow the die again, and said why:

```
ROUTE_LOOSEN_DECLINED reason=residual_not_congestion_shaped kind=evidence
  die=1234x1234um rung=1 proposed_util=0.12
  residual_series=[1, 1] stall_streak=1/2 still_improving=False
  residual_types=['NS Metal x1 on Metal2']
```

That refusal is correct: one non-congestion-shaped residual is not fixed by more
area. It is also the point at which this lane's assigned question stops being
reachable.

`docs/research/subservient_first_non_pass_metal_density.md` records metal
density as the first non-PASS. On **this** host, at **this** plugin head, on the
**shipped** `benchmark-data/ic/subservient`, it is not. The two runs are not the
same tree — see §4 — and neither observation invalidates the other; what is
wrong is treating either one as *the* answer without stating which tree it is.

## 2. "The die is too large for fill to reach 30%" is backwards

The commit message of `4277b34a1` closes with:

> The remaining shortfall is **FLOORPLAN, not fill: the die is too large for
> this design's metal.**

The mechanism says the opposite. `M2.4` counts `metal2 = metal2_drawn +
metal2_dummy`, and `rule_decks/dummy_metal.rb` requires dummy to stand 2 µm
clear of drawn metal:

```ruby
dm_3_l1 = metal_dummy.separation(metal_drawn, 2.um, euclidian)
```

So the fillable area is `die − drawn.sized(2 µm)`. That quantity **grows** as
the die grows. Measured on this run's `routed.def`, die 1234 × 1234 µm
(1 522 756 µm²):

| layer | drawn cov | legally fillable (upper bound) | ceiling, ideal tile | rule |
|---|---|---|---|---|
| Metal2 | 6.53 % | **43.14 %** | 49.66 % | M2.4 needs > 30 % |
| Metal3 | 7.37 % | **43.25 %** | 50.62 % | M3.4 needs > 30 % |
| Metal4 | 5.28 % | 61.73 % | 67.01 % | M4.4 (if 4LM+) |
| Metal5 | 2.53 % | 87.69 % | 90.23 % | M5.4 (if 5LM+) |

Against the same quantity on the 416 µm die of the earlier write-up: **4.49 %
(Metal2) / 3.77 % (Metal3)**. A 2.97× larger die side turns 4.49 % of fill room
into 43.14 %. The small die is the one with no room, because at 416 µm the 2 µm
halo around the routing blankets essentially the whole die.

**Shrinking the floorplan therefore makes M2.4 harder, not easier.** The brief
this lane was given asks for a utilization that reaches 30 %; on the fill route
the answer is that no change is needed — the current floorplan already carries
13 pp of headroom over the requirement before any tile-efficiency derate.

## 3. And drawn metal alone cannot reach 30 % at any legal utilization

Taking the other route — shrink the die until the *routing itself* covers 30 %,
using the most optimistic assumption available (metal2 wire area held CONSTANT
under the shrink; in reality wirelength falls with the die, which makes this
worse):

```
drawn Metal2 area                       99 418.05 µm²
die area at which that is 30 %         331 393.5 µm²   → side 575.7 µm
drawn Metal3 area                      112 178.91 µm²
die area at which that is 30 %         373 929.7 µm²   → side 611.5 µm
```

The design does not fit in either. This run's **post-PnR design area is
397 327 µm²** (`metal_fill.log`, verbatim: `Design area 397327 um^2 28%
utilization`), which needs a **630.3 µm** side at 100 % utilization — larger
than the 575.7 µm the Metal2 target demands. Expressed as the knob the brief
asked about, a 575.7 µm die implies **61.3 % core utilization against synth cell
area, or 119.9 % against the post-PnR design area**. The second number is the
binding one and it is over 100 %.

So: **unreachable by floorplan, reachable with ~13 pp to spare by fill.** That
is the exact inverse of the premise this lane was handed.

## 4. Ground truth of this tree, so the next lane does not re-derive it

| quantity | value | source |
|---|---|---|
| synth cell area | 203 207.4688 µm² | `phase2/stage2/synth/stats.json` |
| synth cells | 8 322 (33 types) | same |
| post-DFT instances | 9 750 | `post_dft_netlist.v` |
| post-PnR design area | 397 327 µm² | `pnr/metal_fill.log` |
| auto-sized die | 1047 × 1047 µm | first `initialize_floorplan` in `pnr.tcl` |
| final die (after upsize retry) | **1234 × 1234 µm** = 1 522 756 µm² | `routed.def` `DIEAREA` |
| final core | 1214 × 1214 µm (10 µm margin) | `pnr.tcl` |
| core util, synth cell area | **14.02 %** | derived |
| core util, post-PnR design area | **27.41 %** | derived |
| stuck-at ATPG coverage | 58.40 % (rc=1) | step `step11_dft_insertion` |
| metal fill (Step 34) | `# fillers placed: 0`, `filled.def` byte-size identical to `routed.def` (21 749 197 B) | `metal_fill.done` / `ls` |
| M2.4 / M3.4 verdict | **NOT MEASURED** — no GDS | step `drc` = SKIP |

The earlier write-up's tree is a different one: its die is 416 × 416 µm, which
under `_auto_die_side_um` (`side = sqrt(cell_area / util)`) implies a cell area
near 43 000 µm² — about a fifth of the 203 207 µm² this tree synthesizes. Any
comparison of the two must say which is meant. This page is the 8HD-8 /
`637cdf091` / `benchmark-data` tree throughout.

## Method, and what it does NOT measure

Per-layer coverage was taken from `routed.def`, not from a GDS, because this run
produced no GDS. Wire segments of `NETS` and `SPECIALNETS` were expanded to
rectangles at the tech LEF's per-layer routing `WIDTH` (with the DEF half-width
end extension) and unioned exactly by `pya.Region`; 153 251 rectangles in,
5 layers with a routing width. Scripts are in the run dir
(`def_metal_rects.py`, `merge_metal_rects.py`, `fillable.py`).

Excluded, and therefore NOT MEASURED:

* **Via cut and enclosure metal.** Small relative to wire area, but real.
* **Standard-cell internal and pin metal.** This is why **Metal1's row above is
  not usable**: its 369 rectangles are essentially the PDN rings and stripes, so
  its drawn figure is an undercount and its fillable figure an overcount. Metal2
  and above are router wires almost in full and are the rows this page rests on.
* **The streamout's own dummy metal** (`36/4`, `42/4`). It does not exist in a
  DEF. It both *adds* to the 30 % numerator and *subtracts* fill room via
  DM.2b's 0.98 µm dummy-to-dummy rule. The fillable figures above therefore
  omit one term of the real rule and are stated as an **upper bound**.
* **Everything the deck would have said.** `gf180mcu.drc` was never run on this
  tree; there is no GDS to run it on.

No DRC threshold was touched. No test was skipped, xfailed or deleted. No
baseline was written.

## What this leaves open

The reachable next question on this tree is **the router**, not the fill: one
`NS Metal` residual on `net2654` at 12 % proposed utilization. Until `pnr`
converges there is no GDS, and without a GDS the density question cannot be
asked at all — which is the honest reason this lane produces a contradiction
and a measurement rather than a floorplan sweep.

If someone still wants the fill route closed, the measurement above says the
room is there and the blocker is elsewhere: `_GDS_DUMMY_FILL_PY` is opt-in on a
`signoff_config.json → dummy_fill` that no gf180mcuD project writes, and
`4277b34a1` landed its multi-layer keep-out **ADVISORY**, changing no gate
verdict. That is a wiring question with its own acceptance, and it is not this
page's to decide.
