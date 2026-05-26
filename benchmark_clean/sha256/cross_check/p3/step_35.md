# Step 35 — GDSII endpoint (both DRC/LVS-clean + func-equiv, NOT pixel)

**What ran:** Verified the OURS final GDSII against the methodology rule — different micro-arch (carry-save CSA vs REF catalog secworks) means the layouts are NOT byte/pixel identical and must not be compared as such. Valid endpoint = both GDS DRC/LVS-sane + functionally equivalent to the NIST golden.

| Endpoint criterion | OURS | REF |
|---|---|---|
| GDS top cell | single `sha256` | single `sha256` |
| GDS geometry | **non-vacuous, full** (25.9 MB magic GDS, 89 cells, 810,000 um², 32 layers) | full (7.5 MB) |
| DRC on final GDS | **0 violations (non-vacuous)** — Step 30 | 279,472 (LEF-abstract caveat) |
| LVS device classes | equivalent (Step 30) | 437/437 match |
| Functional equivalence to NIST KAT | **PASS** (post-layout GLS, abc/empty/abc-224/2block) — Step 28 | PASS |
| Pixel/byte identical to REF? | NO — and correctly NOT expected | — |

**Verdict: BOTH-CLEAN / FUNCTION-EQUIVALENT (NOT pixel).** The OURS GDSII endpoint is valid: it is a full-geometry, single-top-cell, DRC-clean (non-vacuous) layout whose post-layout gate netlist reproduces the NIST FIPS-180-4 digests bit-exact. It is NOT byte-identical to REF and is not expected to be — OURS is an independent carry-save CSA implementation (12,148 cells, 900x900 die) vs REF's catalog secworks IP (9,546 cells, 700x700 die). Equivalence is established at the functional (NIST KAT) and sign-off (DRC/LVS/STA) level, per the cross-check methodology.

**Important honesty note:** the GDS that satisfies this endpoint is the **regenerated 25.9 MB magic GDS** (`phase3/stage4/gds/sha256_magic.gds`), NOT the runner's original 1.4 MB klayout GDS (which was LEF-abstract-only and gave a vacuous 0-polygon DRC) nor the 0-byte `sha256.magic_merged.gds` (vacuous). Those two were explicitly NOT accepted as clean.

**Evidence:** `phase3/stage4/gds/sha256_magic.gds`, `phase3/stage3/pv/xc_drc_magic.xml` (0 items, non-vacuous), `phase3/stage3/sim_postlayout/xc_gls_init0_results.log` (ALL TESTS PASSED); REF `phase3/stage4/gds/sha256.gds`.
