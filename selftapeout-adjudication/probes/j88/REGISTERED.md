# J88 — predictions registered BEFORE the two full post-hold probes ran

## Why

J86 settled that CTS instantiates whatever `-root_buf` names ~2 052 times, and that a
26-site root gives the SAME tree (2 363 buffers, 11 levels) with BETTER skew and
latency. Two consequences follow that this report has not measured:

1. **The residual.** J83 needed the flow's clkswap rung to take the post-hold residual
   from 2 344 to 303. If the 2 052 fifty-site cells never exist, the residual may never
   be there to remove.
2. **The published build-to die.** §6's fixed point `A* = (M+S)/(UTIL-f)` is solved on
   the post-hold `movable` area M, and those 2 052 cells carry
   `2052 x (28.000-14.560) x 3.920 = 108 109.21 um^2` of it. **Arithmetically** that
   moves the top of the published band from 6 164.8 um to 6 117.0 um (2.154x -> 2.137x
   the pad floor). **That is a consequence of a census, not a measurement of a run**,
   which is what these probes are for.

## The two probes, identical but for one argument

Both from `proj/matmul_d3800/phase3/stage3/pnr/placed.def`: width cap (the flow's own,
re-emitted from main's function) -> `estimate_parasitics -placement` ->
`set_propagated_clock` -> CTS -> `repair_timing -hold` -> post-hold DPL rungs 1-4.
**The full-die rung is absent from the generated Tcl by construction.** They differ ONLY
in `-root_buf`.

    j88_rootbig    -root_buf clkbuf_16  (50 sites -- what the flow names today)
    j88_rootfit    -root_buf clkbuf_8   (26 sites -- inside the 48-site inter-tap run)

`j88_rootbig` IS the entry control: it must land near the arm's own post-hold numbers.

## E4 — the entry control

**E4 HOLDS if** `j88_rootbig`'s post-hold rung-1 residual is inside **2 296-2 418** (the
band all four measured dies occupy) **and** its post-hold movable is within **+/-0.5 %**
of the arm's 6 054 418.68 um^2. The +/-0.5 % bound is 30 272 um^2 -- smaller than the
108 109 um^2 effect being tested, so it cannot be passed by a probe that fails to
reproduce the thing under test.
*(`placed.def` predates spare insertion, so an offset is expected and 0.5 % is where I
am willing to call it the same state. If E4 fails both probes are still reported and
compared to EACH OTHER, which is the controlled comparison; only the tie to the arm's
absolute numbers is lost.)*

## Predictions

**P11.** `j88_rootfit`'s post-hold rung-1 residual is **below 500**, against
`j88_rootbig`'s ~2 350. FALSIFIER: >= 500. This is the one that matters: it says the
residual five arms cannot clear is created by the root-buffer choice and not by the
design.

**P12.** `j88_rootfit`'s post-hold movable area is lower than `j88_rootbig`'s by
**97 000-119 000 um^2** (the census figure 108 109 +/- 10 %). FALSIFIER: outside that
band -- which would mean the resizer responds to the swap rather than leaving the rest
of the netlist alone, and the arithmetic above is not the whole story.

**P13.** Re-solving `A* = (M+S)/(UTIL-f)` on `j88_rootfit`'s M puts the build-to die
**below 6 139 um**, the current published low end. FALSIFIER: >= 6 139 um.

**P14, the one I expect to be wrong and am recording anyway.** `j88_rootfit` legalizes
outright -- `POST_HOLD_LEGALIZE_OK` at one of rungs 1-4. FALSIFIER: it does not.
A residual near 300 is what J83 measured AFTER the clkswap rung, and that state did NOT
legalize (`PROBE_POSTSWAP_OK=0`), so the honest expectation is that P11 holds and P14
fails. Recording it makes the difference between those two outcomes a stated one.

## Rules

Probe only. No flow change, no arm touched, no `-root_buf` altered anywhere but inside
these two generated files. `docker run`, `--skip` first, never `docker exec`. Stops
after rung 4. No geometry edited, no rule relaxed, no `--write-baseline`.
