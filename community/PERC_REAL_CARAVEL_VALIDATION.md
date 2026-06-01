# PERC-equivalent — validation with the SHIPPED functions on the REAL Caravel chip_io.def

**Plugin v0.2.10.** The PERC-equivalent checks (ESD presence v0.2.8, ESD discharge topology v0.2.9,
latch-up well-tap presence v0.2.10) were each unit-validated, and composed on a *faithful synthetic*
padded chip (`PERC_EQUIVALENT_E2E_VALIDATION.md`). This doc records running the **actual shipped pure
functions** (AST-extracted verbatim from `phase3_one_shot_runner.py`) against the **real in-container
DEFs** — the real Caravel `chip_io.def` pad ring + a real core routed DEF — via the iic-osic-tools
container.

## Method

`_parse_def_components`, `_classify_io_cell`, `_esd_pad_ring_presence`, `_parse_def_net_terminals`,
`_esd_discharge_topology`, `_welltap_presence_check`, `_discover_power_nets` were extracted byte-for-byte
(Python AST) into a standalone module and run inside the container on the real DEFs. No re-implementation.

## Results (real shipped functions, real DEFs)

| DEF | components | ESD presence | ESD topology | Well-tap | power_nets |
|---|---|---|---|---|---|
| **Caravel `chip_io.def`** (real pad ring) | 818 | MANUAL_REVIEW · PRESENT (10 signal pads / 10 ESD-bearing) | **TOPOLOGY_OK** (0 gaps, 0 unrated) | **WELLTAP_GAP** (ZERO_TAPS) | 0 |
| **SPM core routed** (real) | 302 | N/A (core macro) | — | **WELLTAP_GAP** (ZERO_TAPS) | VDD / VSS |

## What this proves

1. **ESD presence + topology are correct on a REAL 818-component pad ring** — not just synthetic
   fixtures. The classifier finds 10 signal pads / 10 ESD-bearing, all clamp domains close, no
   dangling clamp, no unrated cell → `TOPOLOGY_OK`. The 612 `com_bus_slice` fillers are correctly
   excluded (the v0.2.8 over-count bug stays fixed on real data).
2. **The v0.2.10 latch-up check catches a REAL gap on Caravel too**: `chip_io.def` ships **0 well-tap
   cells** → `WELLTAP_GAP / ZERO_TAPS`. (Same as the spm/subservient/neorv32 core DEFs.) This is a
   real structural latch-up exposure in these artifacts, flagged conclusively.

## The real integration gap this surfaced (→ fixed in v0.2.11)

Caravel `chip_io.def` expresses its power via **regular NETS, not SPECIALNETS**, so the shipped
`_discover_power_nets` (SPECIALNETS-only) returns `([], [])` → the multi-domain padded chip is
**mis-classified as single-supply** → cross-voltage-domain wrongly auto-N/A. A synthetic
SPECIALNETS fixture could never have surfaced this — only the real DEF did. Fixed in v0.2.11 by
counting power domains from **both NETS and SPECIALNETS** `USE POWER/GROUND` + distinct rail
families, plus a level-shifter-presence check (an adversarial panel set the honest boundary:
presence ≠ per-crossing correctness, which stays MANUAL).

## Transport note (reproducibility)

The host repo and the EDA container do not share a filesystem; the extracted pure module was moved
in via base64 through `eda_run_tcl` and executed against the container-resident `/foss/designs/...`
DEFs. The functions are unmodified plugin code.
