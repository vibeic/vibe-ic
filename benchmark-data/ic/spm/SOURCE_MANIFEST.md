# SOURCE_MANIFEST — spm

The `spm` design's RTL is authored in this repository. This record exists for
the THIRD-PARTY source that is committed underneath this root, which is what
Apache-2.0 §4(b)/§4(d) attach to: the obligation follows the distributed WORK,
not the run that used it.

## Vendored, Apache-2.0 — SkyWater PDK standard-cell models

- **File:** `v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v`
  (152,616 lines)
- **Upstream:** the SkyWater Open Source PDK — `SKY130_FD_SC_HD` and
  `SKY130_EF_SC_HD` standard-cell simulation models.
- **Copyright:** `Copyright 2020 The SkyWater PDK Authors`
- **Licence:** **Apache-2.0** (`SPDX-License-Identifier: Apache-2.0`, retained
  verbatim in the file's own header).
- **Modification:** none to the cell models themselves. The file is a
  CONCATENATION of upstream per-cell model files, produced by the DFT/ATPG step
  so one `-v` library argument can be handed to the simulator. A concatenation
  of Apache-2.0 sources is a derivative work and is distributed under the same
  terms; the upstream header is preserved at the top of the file.

Every fact above is taken from the file's own header and content. Nothing here
is inferred from the path.

## Why this record was missing until 2026-08-12

It was never deleted — it never existed. `vendored_attribution_retained_check`
(vibe-ic#1043) is the gate that found it: 525 tracked files under
`benchmark-data/` declare an SPDX licence and this was the only one with no
`SOURCE_MANIFEST` above it. The record is owed because the code ships, and the
code shipping is a fact about the git index, not about whether any published
run is still standing.
