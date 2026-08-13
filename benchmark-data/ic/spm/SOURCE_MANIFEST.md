# SOURCE_MANIFEST — `benchmark-data/ic/spm`

Attribution for third-party source vendored into this IC's published run output.

Added for vibe-ic#1043. Apache-2.0 §4(b) and §4(d) attach to distributing the
**work**, not to publishing a run that used it, so the record has to travel with
the file for as long as the file is in the tree. These two were shipped without
one; measured on `a38902d16`, they were the only Apache-2.0 files under
`benchmark-data/` with no `SOURCE_MANIFEST.md` at or above them (493 declared,
491 covered, 2 uncovered).

This file is an **attribution record**, not run evidence. It asserts nothing
about whether any run passed and changes no verdict.

## Vendored files

### `v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v`

| | |
|---|---|
| Origin | SkyWater Open Source PDK — standard-cell Verilog models |
| Copyright | Copyright 2020 The SkyWater PDK Authors |
| Licence | Apache License, Version 2.0 |
| Licence text | <https://www.apache.org/licenses/LICENSE-2.0> |
| How it got here | concatenated cell models staged for the DFT/ATPG step of this run |

The Apache-2.0 header, including the copyright notice, is retained verbatim at
the top of the file itself.

### `v1.9.96_gf180mcuD/phase2/stage2/dft/cell_model_combined.v`

| | |
|---|---|
| Origin | GlobalFoundries 180nm MCU Open Source PDK — standard-cell Verilog models |
| Copyright | Copyright 2022 GlobalFoundries PDK Authors |
| Licence | Apache License, Version 2.0 |
| Licence text | <http://www.apache.org/licenses/LICENSE-2.0> |
| How it got here | concatenated cell models staged for the DFT/ATPG step of this run |

The Apache-2.0 header, including the copyright notice, is retained verbatim at
the top of the file itself.

## Scope

`SOURCE_MANIFEST.md` covers the subtree it sits in, which is how the other eight
records in this repository are organised and how
`vendored_attribution_present_check` resolves coverage — nearest record at or
above the file. A future vendored file under `benchmark-data/ic/spm/` is covered
by this record's existence but is **not** described by it until it is added
above; the gate enforces presence, and presence is what §4(d) turns on.
