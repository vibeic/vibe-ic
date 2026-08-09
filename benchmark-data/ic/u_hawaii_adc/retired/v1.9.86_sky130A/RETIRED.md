# RETIRED — `u_hawaii_adc × sky130A` is not a cell

**Retired 2026-08-09 by the repo gatekeeper.**
Moved here from `benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/`.
**Nothing was deleted** — all 188 tracked files moved intact (`git mv`, rename
detection preserves their history).

---

## (a) Why this is not a cell

A cell is an `(IC × PDK)` combination the design's **own input declares**
(`benchmark-data/ic/CELL_MATRIX.md`). `u_hawaii_adc` declares **ihp-sg13g2**:

| rank | declaration | says |
|---|---|---|
| 1 (authoritative) | `benchmark-data/ic/u_hawaii_adc/phase1/generated_docs/L19_CONSTRAINTS_PDK.json` | `pdk_target: sg13g2` |
| 3 | `benchmark-data/ic/u_hawaii_adc/input/docs/L1_DATASHEET.md` line 35 | `| Target PDK | **IHP SG13G2** (130nm BiCMOS, open PDK) |` |

Measured, not asserted — `sky130` appears **0 times** in this IC's design input:

```
$ grep -rIn -i sky130 benchmark-data/ic/u_hawaii_adc/input/docs/ | wc -l
0
```

`CELL_MATRIX.md` lists `u_hawaii_adc × sky130A` under **Combinations that are
NOT cells**: *"declares IHP SG13G2, and is analog."*

**The run's own L19 disagrees with the design's L19.** This folder's
`phase1/generated_docs/L19_CONSTRAINTS_PDK.json` records `pdk_target: sky130A`,
while the IC-level L19 records `sg13g2`. A published folder carrying a PDK the
design never declared is precisely the artefact CELL_MATRIX.md was written to
stop being mistaken for grounding: **published is not the same as grounded.**

A run against an undeclared PDK is not forbidden — the flow supports it via
`--allow-pdk-target-mismatch`, and the result may be published as a **disclosed
cross-PDK port**. This run was not published as one: its `RESULT.md` makes no
mismatch disclosure and states a bare `Verdict: PASS`.

## (b) This is HISTORY. It MUST NOT be cited as a result.

Retained so that *"we never ran this"* and *"we ran it and kept the record"*
never collapse into the same state (`benchmark-data/ic/INDEX.md`: nothing here
is deleted for failing — and nothing is deleted for being ungrounded either).

**Do not cite this folder as a result, a verdict, a PASS, a converged cell, or
evidence of `u_hawaii_adc` on sky130A** — in a README, an issue, a PR, a site
page, a slide, or a test that treats it as a published cell. Cite
`CELL_MATRIX.md` for what this IC's cell actually is: **`u_hawaii_adc ×
ihp-sg13g2`**, which has not been published.

What this folder contains is transcribed below **as a record of what the run
recorded**, not re-derived and not re-endorsed by this file:

- `reports/audit/phase23_completion_audit.json` → `verdict: PASS`,
  `PASS 8 / FAIL 0 / MISSING 0 / WAIVED 0` (`VACUOUS_PASS 2`,
  `SKIPPED-CONDITION 53`)
- `RESULT.md` → `**Verdict:** PASS`, plugin v1.9.86, analog A-track (no
  `phase2/`)

Those numbers were true of a run whose PDK the design does not declare. They
say nothing about `u_hawaii_adc × ihp-sg13g2`.

## (c) Decision record

| field | value |
|---|---|
| date | **2026-08-09** |
| decided by | **the repo gatekeeper** (vibe-ic) |
| decision | retire published NON-CELLS by **moving**, never deleting |
| why moving | it satisfies both standing rules at once — the benchmark-data layout contract (an IC dir holds `input/` and `v*_<PDK>/`) and INDEX.md's never-delete rule |
| plugin version current at the move | **1.10.26** |
| from | `benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/` |
| to | `benchmark-data/ic/u_hawaii_adc/retired/v1.9.86_sky130A/` |
| files moved | 188 tracked, 0 deleted, 0 symlinks |

Companion record: `benchmark-data/ic/CELL_MATRIX.md`,
`benchmark-data/ic/retention.json`, `benchmark-data/ic/INDEX.md`.
