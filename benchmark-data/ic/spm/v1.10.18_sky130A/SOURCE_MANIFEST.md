# SOURCE_MANIFEST — spm

The `spm` design's RTL is authored in this repository. This record exists for
the THIRD-PARTY source that is committed underneath this root, which is what
Apache-2.0 §4(b)/§4(d) attach to: the obligation follows the distributed WORK,
not the run that used it.

## Vendored, Apache-2.0 — SkyWater PDK standard-cell models

- **File:** `phase2/stage2/dft/cell_model_combined.v`
  (152,616 lines), relative to this record's own directory
  (`benchmark-data/ic/spm/v1.10.18_sky130A/`).
- **Upstream:** the SkyWater Open Source PDK — `SKY130_FD_SC_HD` and
  `SKY130_EF_SC_HD` standard-cell simulation models.
- **Copyright:** `Copyright 2020 The SkyWater PDK Authors`
- **Licence:** **Apache-2.0**, declared by the file's own SPDX identifier line
  and retained verbatim in its header.

  (This record deliberately does not quote that identifier line literally.
  `vendored_attribution_retained_check` keys on the token, so quoting it would
  make this attribution record count itself as a piece of vendored source —
  harmless, since it covers itself, but it would inflate the census the gate
  reports and make an attribution record look like the thing it attributes.)
- **Modification:** none to the cell models themselves. The file is a
  CONCATENATION of upstream per-cell model files, produced by the DFT/ATPG step
  so one `-v` library argument can be handed to the simulator. A concatenation
  of Apache-2.0 sources is a derivative work and is distributed under the same
  terms; the upstream header is preserved at the top of the file.

Every fact above is taken from the file's own header and content. Nothing here
is inferred from the path.

## Why this record was missing, twice

It was missing until 2026-08-12 because it had never existed — not because
anything removed it. `vendored_attribution_retained_check`
(vibe-ic#1043) is the gate that found it: 525 tracked files under
`benchmark-data/` declare an SPDX licence and this was the only one with no
`SOURCE_MANIFEST` above it. The record is owed because the code ships, and the
code shipping is a fact about the git index, not about whether any published
run is still standing.

It went missing a second time on 2026-08-14, and that time it *was* deleted.
`d40d03215` added it at the IC level, `benchmark-data/ic/spm/`; the v1.10.40
landing (`75776dbbb`) removed it there, because
`benchmark_evidence_structure_check` refuses any IC-level entry that is not
`input/` or a version cell. The licensed source stayed; only the record left,
which is the one outcome `vendored_attribution_retained_check` names as not
lawful — *"deleting the file is the other lawful option; deleting only the
record is not."*

This copy lives inside the cell instead, which is both "at or above" the
licensed file — what the attribution gate requires — and a legal IC-level
entry — what the layout gate requires. Measured on all three placements: absent
fails attribution, IC-level fails layout, here passes both.
