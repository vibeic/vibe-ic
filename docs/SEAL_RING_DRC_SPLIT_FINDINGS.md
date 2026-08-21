# FINDINGS — which half of `spm`'s 1177 KLayout DRC violations belongs to the seal ring

_Measured 2026-08-20. Design: `spm` on `gf180mcuD`, shuttle slot `0p5x0p5`.
Sign-off deck: the PDK's own `gf180mcu.drc`, run inside the shuttle operator's
own container image `ghcr.io/wafer-space/gf180mcu-precheck:latest`
(image id `4f58bb5de315`, KLayout 0.30.9)._

## The question

The operator's precheck reports **1177** KLayout DRC violations on the sealed
die. `GR.*` (813 of them) is obviously the ring. But `PP.2`, `NP.2`, `DF.*` and
`NW.*` are implant / diffusion / n-well rules — they could equally be the ring's
context **or** the circuit's own pre-existing violations. Arguing is slower than
measuring, so this measures it: run the **same deck with the same options** on
the **same design without the ring**, and difference the rule histograms.

## The command (identical for both runs, only the input differs)

Taken verbatim from the precheck's own `14-klayout-drc/COMMANDS`, and run
directly because the unsealed die has no `GUARD_RING_MK`:

```bash
docker run --rm \
  -v <dir holding spm.gds>:/data/design:ro \
  -v <rundir>:/data/rundir \
  --entrypoint /nix/store/dljmpck53kb6zxhvd73b688286b0kwkn-klayout-0.30.9/bin/klayout \
  ghcr.io/wafer-space/gf180mcu-precheck:latest \
  -b -zz -r /workspace/gf180mcu/gf180mcuD/libs.tech/klayout/tech/drc/gf180mcu.drc \
    -rd input=/data/design/spm.gds \
    -rd topcell=spm \
    -rd report=/data/rundir/drc.klayout.lyrdb \
    -rd decks=all,-antenna,-density,-cup \
    -rd variant=gf180mcuD \
    -rd workers=1 \
    -rd threads=32
```

Deck, `decks=`, `variant=`, `workers=`, `threads=` are byte-for-byte the
precheck stage-14 values; the image id is the same one the reference run used.
Both runs exited 0 (the deck reports violations in its own summary, not in the
exit code).

Inputs (sha256 as the container itself printed them):

| run      | layout                          | sha256 (head)  |
|----------|---------------------------------|----------------|
| unsealed | `debug_gds_unsealed/spm.gds`    | `8db0c0decb17…`|
| sealed   | `debug_gds/spm.gds`             | `b8ad66774706…`|

## The table

`DRC RESULT` lines and per-rule counts as the deck printed them:

| rule       | unsealed | sealed | delta | whose |
|------------|---------:|-------:|------:|-------|
| `GR.4`     |        0 |    794 |  +794 | **RING** |
| `GR.2`     |        0 |     19 |   +19 | **RING** |
| `V1.2a`    |        0 |      2 |    +2 | **RING** |
| `V3.2a`    |        0 |      2 |    +2 | **RING** |
| `PP.2`     |       87 |     87 |     0 | circuit |
| `NP.2`     |       83 |     83 |     0 | circuit |
| `DF.13_MV` |       70 |     70 |     0 | circuit |
| `NW.2a_LV` |       39 |     39 |     0 | circuit |
| `NW.2b_LV` |       35 |     35 |     0 | circuit |
| `DV.5`     |       28 |     28 |     0 | circuit |
| `DF.14_MV` |        9 |      9 |     0 | circuit |
| `NW.2b_MV` |        9 |      9 |     0 | circuit |
| **TOTAL**  |  **360** | **1177** | **+817** | |

- pre-existing (present in both, unchanged): **360**
- introduced by the seal ring: **817**
- fixed by the seal ring: **0**

The split is total. Every rule is either exactly unchanged or exactly zero
before the ring — no rule is partly the circuit's and partly the ring's.

## What the rules are

Ring-introduced:

- `GR.4 : Minimum Metal width5: 12` — 794
- `GR.2 : Min GUARD_RING_MK space to prime die Metal5: 10` — 19
- `V1.2a : min. via1 spacing : 0.26µm` — 2
- `V3.2a : min. via3 spacing : 0.26µm` — 2

Circuit's own — all tap-distance, implant-spacing, n-well-spacing and
dualgate-width rules, none of which mention the ring:

- `PP.2 / NP.2 : min. pplus / nplus spacing : 0.4µm`
- `DF.13_MV / DF.14_MV : Max distance of Nwell / substrate tap …: 15um`
- `NW.2a_LV / NW.2b_LV / NW.2b_MV : Min. Nwell Space (Outside DNWELL)`
- `DV.5 : Min. Dualgate width. : 0.7µm`

## Corrections to two working assumptions

1. **The precheck does not refuse the unsealed die.** It does not stop at the
   slot-size stage; it prints `Skipping step 'Check Slot Size'…` and runs the
   whole ladder, DRC included. A full unsealed precheck ladder therefore needs
   no workaround.
2. **The 1177 histogram in circulation was missing `V3.2a : 2`** — it summed to
   1175. The sealed histogram has thirteen non-zero entries, not twelve.

## Side effect, measured at the same time

Comparing complete precheck ladders (not part of the DRC question, recorded
because the runs already existed):

| check           | unsealed | sealed | sealed+fill |
|-----------------|---------:|-------:|------------:|
| KLayout density |        8 |      8 |           3 |
| KLayout antenna |        4 |      1 |           1 |
| Magic DRC       |      248 |    252 |       clear |
| KLayout DRC     |      360 |   1177 |        1177 |

Metal fill contributes **zero** KLayout DRC violations — sealed and sealed+fill
give the identical 1177 and the identical histogram — while clearing Magic DRC
and taking density from 8 to 3.

## Bearing on the goal

The goal is `rc 0` from the operator's precheck. 817 of 1177 — 69% — are the
ring's, concentrated in one rule (`GR.4`, 794). The remaining 360 are the
circuit's own and are untouched by anything done to the ring; they will still be
there when the ring is fixed, and they are a separate piece of work.

Nothing here was obtained by editing a layout or relaxing a deck.
