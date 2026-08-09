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
track. It has no RTL and needs none; its converged predecessor
`v1.9.86_sky130A` has no `phase2/` at all. Routing it down the digital track
produces `reference_tb: rtl/ missing`, which is a symptom of mis-routing and not
a missing generator.

## Combinations that are NOT cells

| combination | why not |
|---|---|
| `sha256 × gf180mcuD` | sha256 declares SKY130 only; zero gf180 mentions anywhere. Dispatched 2026-08-09 in error and stopped mid-run. |
| `edge_llm_accel × sky130A` | declares nangate45. Burned a full round once before (134 × ODB-0176 undefined-layer) and was dispatched again on 2026-08-09. |
| `u_hawaii_adc × sky130A` | declares IHP SG13G2, and is analog. |
| `spm × ihp-sg13g2` | spm declares sky130 primary + gf180 secondary. **A published run `v1.5.58_ihp-sg13g2` exists**, which is precedent but not a declaration — recorded here precisely because an existing artefact is the easiest thing to mistake for grounding. |

A run against an undeclared PDK is not forbidden — the flow supports it through
`--allow-pdk-target-mismatch`, which requires acknowledging in writing that the
measured PDK is not the declared one. Such a run is a **disclosed cross-PDK
port**: it may be published as that, and it may never claim the design's L7
sign-off, whose corners are declared per-PDK.
