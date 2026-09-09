# netgen `-json` output, captured from the shipped image

Produced 2026-09-10 by running the real tool, not hand-written:

    docker run --rm ghcr.io/vibeic/vibeic-eda:0.3.54 --skip bash -lc \
      'netgen -batch lvs "lay.spice top" "src.spice top" setup.tcl out.rpt -json'

`lay.spice` and `src.spice` are the two-line inputs beside this file: one nfet
against two, so the compare mismatches and there is something to localize.

`lvs.json` is netgen's output verbatim. It is a top-level OBJECT
(`_looks_like_e1` returns True for it) whose `cells[0]` carries
`name`/`devices`/`nets`/`badnets`/`badelements`/`pins` — the records
`localize()` reads. Keeping the real bytes is the point: the defect this
fixture pins is a SHAPE disagreement, and a hand-written array would have
reproduced the assumption instead of the tool.
