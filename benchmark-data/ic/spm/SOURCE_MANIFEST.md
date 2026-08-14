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

## Why this record was missing until 2026-08-12

It was never deleted — it never existed. `vendored_attribution_retained_check`
(vibe-ic#1043) is the gate that found it: 525 tracked files under
`benchmark-data/` declare an SPDX licence and this was the only one with no
`SOURCE_MANIFEST` above it. The record is owed because the code ships, and the
code shipping is a fact about the git index, not about whether any published
run is still standing.

## Vendored, Apache-2.0 — GlobalFoundries GF180MCU standard-cell models

- **File:** `v1.9.96_gf180mcuD/phase2/stage2/dft/cell_model_combined.v`
  (39,971 lines)
- **Upstream:** the GlobalFoundries Open Source PDK — `gf180mcu_fd_sc_mcu7t5v0`
  standard-cell simulation models.
- **Copyright:** `Copyright 2022 GlobalFoundries PDK Authors`
- **Licence:** **Apache-2.0**, stated by the file's own header in full — the
  "Licensed under the Apache License, Version 2.0" notice with the URL and the
  AS-IS paragraph, retained verbatim.
- **Modification:** none to the cell models themselves. As with the SkyWater
  file above, this is a CONCATENATION of upstream per-cell model files produced
  by the DFT/ATPG step so one `-v` library argument can be handed to the
  simulator. A concatenation of Apache-2.0 sources is a derivative work and is
  distributed under the same terms; the upstream header is preserved at the top.

Every fact above is taken from the file's own header and content. Nothing here
is inferred from the path.

### Why this one was missed when the SkyWater file was found

**It carries no machine-readable SPDX identifier line.** Grepping its head for
that token matches zero times, while the licence itself is stated in full
prose. The gate that found the SkyWater file keys on that token alone — its
`_SPDX_RE` matches the identifier and nothing else — so this file is not in
its 525-file denominator at all. It could never have been reported as
uncovered, because it was never counted.

(Like the SkyWater entry above, this record deliberately does not quote the
identifier token literally: the gate keys on it, so quoting it would make this
attribution record count itself as a piece of vendored source and inflate the
census the gate reports.)

Measured on `a38902d16`, classifying every tracked file under `benchmark-data/`:

    tracked files                 17216
      with SPDX                     525   <- the gate's denominator
      licence header, NO SPDX         2   <- invisible to it
      no licence                  16657

Of those two, one is a Yosys build log carrying the tool's banner and owes
nothing. This file is the other, and it is the same KIND of artefact as the
SkyWater one — the same DFT step, the same concatenation, the same licence.

The obligation does not depend on the gate seeing it: Apache-2.0 §4(b)/§4(d)
attach to the distributed WORK, and this code ships in the git index. The
record is owed either way, which is why it is written here rather than filed as
a request for the gate to be widened first.
