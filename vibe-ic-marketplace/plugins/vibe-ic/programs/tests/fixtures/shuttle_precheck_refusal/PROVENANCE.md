# `shuttle_precheck_refusal` — a real external refusal, not a hand-written one

This is the run directory the LIVE shuttle precheck wrote when it was pointed at
a layout this project had already published. It is captured verbatim (minus the
per-step `config.json` and the copied `.gds`, which carry no verdict and are
large) so the parser in `tapeout_readiness_check.py` is tested against what the
counterparty's tool actually emits rather than against our idea of it.

## The run

    tool     gf180mcu-precheck  (https://github.com/wafer-space/gf180mcu-precheck)
    image    ghcr.io/wafer-space/gf180mcu-precheck
             @sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f
             (content id sha256:4f58bb5de3159afe26ebf17310c5129234fe0bc7b9697723164ad0fab984fc40)
    layout   ic/spm/v1.9.96_gf180mcuD/phase3/stage4/gds/chip_top.gds
             sha256 fb08d9ed51f501ff4c3fbd6b9a30916c5927c86d586f07f147c9388388d8a255
    invoked  docker run --rm --network=none …
             python precheck.py --input … --dir … --top chip_top --slot 1x1
    date     captured 2026-08-18; RE-RUN 2026-08-21 against the digest above,
             byte-for-byte the same verdict, the same three step directories,
             and the same missing `state_out.json` on the third.

## Why the image is named by digest here

The capture was originally recorded against the `:latest` tag. A tag is a
mutable pointer, so "this is what the tool said" was a claim nobody could
re-check: the same reference resolves to different bytes whenever the operator
pushes. The digest was resolved from that tag and the run reproduced against it,
so this fixture now names the content that produced it. `tapeout_readiness_check`
runs the same digest, for the same reason.

## The verdict

REFUSED at ladder step 3 of 16, `KLayout.CheckSize`:

    [Error]: Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal
    ring (guard ring) around the die.

This is the measurement vibe-ic#1744 asked for, and it came back the way the
issue predicted: a flow that has only ever built a core has no seal ring, and
the first thing an outside party refuses for is the submission frame — before
density, before antenna, before either DRC deck.

## Why the structure matters more than the text

`01-klayout-readlayout` and `02-klayout-checktoplevel` each carry a
`state_out.json`; `03-klayout-checksize` does not. That is the discriminator the
parser keys on — a step that completed wrote its output state, and the step the
flow died in did not. The `[Error]` text is quoted as evidence and is never used
to decide, because a scraper that fails to recognise a new phrasing would fail
OPEN and report a refusal as a pass.
