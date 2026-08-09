# RETIRED — `spm × ihp-sg13g2` is not a cell

**Retired 2026-08-09 by the repo gatekeeper.**
Moved here from `benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/`.
**Nothing was deleted** — all 211 tracked files moved intact (`git mv`, rename
detection preserves their history).

---

## (a) Why this is not a cell

A cell is an `(IC × PDK)` combination the design's **own input declares**
(`benchmark-data/ic/CELL_MATRIX.md`). `spm` declares **sky130A primary +
gf180mcuD secondary**, and nothing else:

| rank | declaration | says |
|---|---|---|
| 1 (authoritative) | `phase1/generated_docs/L19_CONSTRAINTS_PDK.json` — **including this run's own** | `pdk_target: sky130` |
| 3 | `benchmark-data/ic/spm/input/docs/L1_product_metadata.md` line 32 | `| 目標 PDK family | open-source(SKY130 主目標,GF180MCU 為次目標) |` |
| 3 (secondary, carries its own library + clock + floorplan) | same file, lines 33–40 | `sky130_fd_sc_hd` @ 10 ns / 45 % and `gf180mcu_*` @ 24 ns / 40 % — **two** PDKs, both named |

Measured, not asserted — IHP/SG13G2 appears **0 times** in this IC's design
input:

```
$ grep -rIn -i "sg13g2\|ihp" benchmark-data/ic/spm/input/docs/ | wc -l
0
```

`CELL_MATRIX.md` lists `spm × ihp-sg13g2` under **Combinations that are NOT
cells**, and names this very folder:

> `spm` declares sky130 primary + gf180 secondary. **A published run
> `v1.5.58_ihp-sg13g2` exists**, which is precedent but not a declaration —
> recorded here precisely because an existing artefact is the easiest thing to
> mistake for grounding.

**The run's own L19 contradicts its own folder name.** This folder's
`phase1/generated_docs/L19_CONSTRAINTS_PDK.json` records `pdk_target: sky130`
while the directory is named `_ihp-sg13g2`. The PDK is in the path, not in the
declaration.

A run against an undeclared PDK is not forbidden — the flow supports it via
`--allow-pdk-target-mismatch`, and the result may be published as a **disclosed
cross-PDK port**, which may never claim the design's L7 sign-off (whose corners
are declared per-PDK). This run was not published as one: its `RESULT.md`
contains no mismatch disclosure and states *"This is one cell (IC × PDK) of a
larger open-PDK matrix"*, i.e. it claims cell status directly.

## (b) This is HISTORY. It MUST NOT be cited as a result.

Retained so that *"we never ran this"* and *"we ran it and kept the record"*
never collapse into the same state (`benchmark-data/ic/INDEX.md`: nothing here
is deleted for failing — and nothing is deleted for being ungrounded either).

**Do not cite this folder as a result, a verdict, a PASS, a converged cell, or
evidence of `spm` on IHP-SG13G2** — in a README, an issue, a PR, a site page, a
slide, or a test that treats it as a published cell. `spm`'s real cells are
`spm × sky130A` and `spm × gf180mcuD`; their currently published evidence is
`benchmark-data/ic/spm/v1.10.18_sky130A/` and
`benchmark-data/ic/spm/v1.9.96_gf180mcuD/`.

What this folder contains is transcribed below **as a record of what the run
recorded**, not re-derived and not re-endorsed by this file:

- `reports/audit/phase23_completion_audit.json` → `verdict: PASS_WITH_WAIVERS`,
  `PASS 35 / FAIL 0 / MISSING 0 / WAIVED 3` (`VACUOUS_PASS 3`,
  `SKIPPED-CONDITION 22`)
- `RESULT.md` → `**PASS_WITH_WAIVERS**`, plugin v1.5.58, container
  `vibeic-eda:0.2.28`, run date 2026-07-24

Those numbers were true of a run against a PDK the design does not declare.
They are not a `spm` sign-off.

### Known dependents — this folder is READ, not merely cited

Unlike the 2026-08-07/08-09 supersession retirements, this folder is not
replaced by a newer run of the same cell: **there is no `spm × ihp-sg13g2`
cell to replace it with.** Anything that reads it as a fixture is reading a
non-cell and must be re-pointed at a real cell or at a purpose-built fixture,
not at this path. The dependents are enumerated in the retirement's own record
(commit message and the gatekeeper report); they live outside `benchmark-data/`
and are migrated in a **separate commit** — a plugin change and a benchmark
result never share a commit.

## (c) Decision record

| field | value |
|---|---|
| date | **2026-08-09** |
| decided by | **the repo gatekeeper** (vibe-ic) |
| decision | retire published NON-CELLS by **moving**, never deleting |
| why moving | it satisfies both standing rules at once — the benchmark-data layout contract (an IC dir holds `input/` and `v*_<PDK>/`) and INDEX.md's never-delete rule |
| plugin version current at the move | **1.10.26** |
| from | `benchmark-data/ic/spm/v1.5.58_ihp-sg13g2/` |
| to | `benchmark-data/ic/spm/retired/v1.5.58_ihp-sg13g2/` |
| files moved | 211 tracked, 0 deleted, 0 symlinks |

Companion record: `benchmark-data/ic/CELL_MATRIX.md`,
`benchmark-data/ic/retention.json`, `benchmark-data/ic/INDEX.md`.
