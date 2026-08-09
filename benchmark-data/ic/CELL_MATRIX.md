# The (IC × PDK) cell matrix — derived, not asserted

**Every cell in this table points to a declaration in the design's own input.**
A combination with no declaration is not a cell, however reasonable it looks and
regardless of whether `benchmark-data/` already contains a published run under
that name. **Published is not the same as grounded.**

This file exists because on 2026-08-09 a 12-cell matrix was dispatched in which
**at least four combinations had been invented by the dispatcher** — the matrix
had no single source, so nothing could contradict it, and every progress report
built on it inherited the fiction. That is
`proxy-instead-of-property` applied to the denominator itself.

## How to establish a cell's PDK — in this order

1. **`phase1/generated_docs/L19_CONSTRAINTS_PDK.json` → `pdk_target`.** This is
   the authoritative field.
2. If L19 is `NOT_YET_EXTRACTED`, use what the design input **ships**: the
   liberty files under `input/pdk/liberty/` are a concrete commitment.
3. `input/docs/L1_*.md` may name a **secondary** target. A secondary target only
   counts when it carries its own library, clock period and floorplan settings —
   a passing mention is not a declaration.

**Do NOT grep `input/docs/` alone.** Several cells declare nothing in docs while
L19 declares plainly. Deriving "no PDK declared" from a docs grep is how the
2026-08-09 re-derivation went wrong a second time, while correcting the first.

## The matrix — 11 cells

| # | IC | PDK | Evidence |
|---|---|---|---|
| 1 | `caravel_user_project` | sky130A | L19 `pdk_target: sky130a` |
| 2 | `edge_llm_accel` | **nangate45** | L19 `pdk_target: nangate45` |
| 3 | `edge_llm_matmul_accel` | sky130A | L19 `pdk_target: sky130A` |
| 4 | `ibex` | sky130A | L19 unextracted; input ships `sky130_fd_sc_hd__*.lib` |
| 5 | `opentitan_aes` | sky130A | L19 unextracted; input ships `sky130_fd_sc_hd__*.lib` |
| 6 | `sha256` | sky130A | L19 `pdk_target: sky130`; L1 "SKY130 主目標" |
| 7 | `spm` | sky130A | L19 `pdk_target: sky130`; L1 primary |
| 8 | `spm` | gf180mcuD | L1 "GF180MCU 為次目標" + `gf180mcu_*` library + 24 ns |
| 9 | `subservient` | sky130A | L19 `pdk_target: sky130`; L1 primary |
| 10 | `subservient` | gf180mcuD | L1 "GF180MCU secondary" + library + 20 ns (from `reference/data/gf180.tcl`) |
| 11 | `u_hawaii_adc` | **ihp-sg13g2** | L19 `pdk_target: sg13g2`; L1 "Target PDK **IHP SG13G2**" |

`u_hawaii_adc` runs the **analog A1–A9 track**, not the digital RTL→synth→PnR
track. It has no RTL and needs none; the run that used to sit at
`u_hawaii_adc/v1.9.86_sky130A` — retired 2026-08-09 to
`u_hawaii_adc/retired/v1.9.86_sky130A/`, see its `RETIRED.md` — has no
`phase2/` at all. Routing it down the digital track
produces `reference_tb: rtl/ missing`, which is a symptom of mis-routing and not
a missing generator.

## Combinations that are NOT cells

| combination | why not |
|---|---|
| `sha256 × gf180mcuD` | sha256 declares SKY130 only; zero gf180 mentions anywhere. Dispatched 2026-08-09 in error and stopped mid-run. |
| `edge_llm_accel × sky130A` | declares nangate45. Burned a full round once before (134 × ODB-0176 undefined-layer) and was dispatched again on 2026-08-09. **Still staged after this row was written** — see "A recorded non-cell that keeps getting dispatched" below. |
| `u_hawaii_adc × sky130A` | declares IHP SG13G2, and is analog. A published run `v1.9.86_sky130A` existed; **RETIRED 2026-08-09 to `u_hawaii_adc/retired/v1.9.86_sky130A/`** — moved, not deleted. Its own L19 recorded `pdk_target: sky130A` while the IC's L19 records `sg13g2`. |
| `spm × ihp-sg13g2` | spm declares sky130 primary + gf180 secondary. **A published run `v1.5.58_ihp-sg13g2` existed**, which was precedent but not a declaration — recorded here precisely because an existing artefact is the easiest thing to mistake for grounding. **RETIRED 2026-08-09 to `spm/retired/v1.5.58_ihp-sg13g2/`** — moved, not deleted. Its own L19 says `pdk_target: sky130`; the PDK was in the folder name only. |

A run against an undeclared PDK is not forbidden — the flow supports it through
`--allow-pdk-target-mismatch`, which requires acknowledging in writing that the
measured PDK is not the declared one. Such a run is a **disclosed cross-PDK
port**: it may be published as that, and it may never claim the design's L7
sign-off, whose corners are declared per-PDK.

### What happens to a non-cell that was already published

It is **RETIRED by moving**, to `benchmark-data/ic/<IC>/retired/<version>_<PDK>/`,
and it is **never deleted**. Deleting would make *"we never ran this"* and *"we
ran it, kept the record, and later established it was never a cell"* the same
state — the exact collapse `INDEX.md` exists to prevent. Moving resolves that
against the layout contract at the same time: the `<IC>/` level goes back to
holding `input/` plus `v*_<PDK>/` cells, and the history sits one level down
under `retired/`, out of the `v*_<PDK>` namespace that every discovery glob in
this repo walks.

Each retired folder carries a `RETIRED.md` stating (a) why it is not a cell,
citing the L19/L1 declaration, (b) that it is history and **must not be cited
as a result**, and (c) the date and that the repo gatekeeper decided it.
Retired 2026-08-09: `spm/retired/v1.5.58_ihp-sg13g2/`,
`u_hawaii_adc/retired/v1.9.86_sky130A/`.

## A recorded non-cell that keeps getting dispatched

Writing a combination into the table above does not stop it being dispatched.
`edge_llm_accel × sky130A` is the worked example, and the timestamps are the
point:

| when | what |
|---|---|
| 2026-08-09 16:41 | container `c_r11014_edge_sky130A` created |
| 2026-08-09 18:27 | the non-cell row above committed |
| 2026-08-09 18:30 | `_r11014_edge_llm_accel_sky130A` still being written to |

The staged tree carried `edge_llm_accel` — `L19 pdk_target: nangate45`, L1
`目標 PDK | nangate45`, and `fakeram45` nangate libraries under
`input/pdk_local/` — while the surrounding container and dispatch named
sky130A. It produced no `reports/orchestrator/` output at all.

Whether the 18:30 write is a distinct dispatch or the tail of the 16:41 one is
**not determinable from what is on disk**, and this file should not guess. What
*is* established is that the record and the dispatch did not meet: the row was
committed at 18:27 and the combination it forbids was still live three minutes
later.

**The mechanism is a name near-collision.** Two distinct designs exist:

- `edge_llm_accel` — declares **nangate45** (matrix row 2)
- `edge_llm_matmul_accel` — declares **sky130A** (matrix row 3)

They differ by one token, and the abbreviated container name
`c_r11014_edge_sky130A` collapses that token entirely. Anything that reads the
cell identity off the container — or off a run directory named for the
container — resolves the wrong design and inherits a PDK the design never
declared.

### The rule

**A container name is not a cell identity.** Neither is a run-directory name.
Derive the cell from the **staged input's own `L19` / `L1`**, the same way every
row in this file is derived, and confirm the PDK you are about to pass matches
what that input declares. A directory is where a design was *found*; the L-docs
are what it *is*.

Concretely, before dispatching against a staged tree:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1]));
print(d.get('ic_name'), '->', d['fields'].get('pdk_target'))" \
    <run>/phase1/generated_docs/L19_CONSTRAINTS_PDK.json
```

If that name is not the cell you were dispatched for, stop — you are holding a
different design.
