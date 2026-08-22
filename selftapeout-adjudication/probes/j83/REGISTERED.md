# J83 — predictions registered BEFORE the post-hold probe ran

Subject: `proj/matmul_d3800/phase3/stage3/pnr/post_cts.def` + the flow's OWN
`repair_timing -hold`, then ladder rungs 1-4 and the clkswap rung. The FULL-DIE rung
(`pnr.tcl:8318-8324`) is absent from the generated Tcl by construction -- five arms are
inside it and this probe must not become a sixth.

## Why this exists

J80 probed the POST-CTS state and had to bound the distance to post-hold by ARGUMENT:
hold repair adds 222 cells, 3 644.04 um^2 (0.06 % of movable) and moves the residual by
7. An argument is not a measurement. This probe removes it by running hold repair.

## E — the ENTRY CONTROL, which decides whether anything after it counts

After `repair_timing -hold`, the probe must land in the die-3800 ARM'S OWN post-hold
state. The arm printed, at its first post-hold DPL block:

    cells 391 980   movable 6 054 418.68 um^2   fixed 667 191.53 um^2   util 47.3 %
    rung-1 residual 2 352

**E HOLDS if** the probe's cell count is within +/-1 % of 391 980 AND its rung-1
residual is inside 2 296-2 418 (the band all four measured arms occupy).
**E FAILS if** either misses. A known reason it could: the probe enters from a DEF and
does not inherit `set_propagated_clock` from the CTS run, so `repair_timing -hold` may
see different slacks and insert a different number of buffers. **If E fails, P4-P6 are
still reported but the probe is the weaker instrument and says so.**

## P4 — the load-bearing one

**The clkswap rung, run in the true post-hold state, leaves a residual STRICTLY BELOW
2 296** -- the bottom of the band all four measured arms have held at every rung.
Reason: J80 measured 296 in the post-CTS state, and hold repair differs from it by
0.06 % of movable area.
FALSIFIER: a post-swap residual >= 2 296.

## P5 — the sharp version of the same thing

**Below 500.** J80 got 296; hold repair adds 222 cells.
FALSIFIER: >= 500. P5 dying while P4 lives means hold repair matters far more at the
legalizer than its 0.06 % of area suggests -- which would be a finding in itself.

## P6 — the swap population is unchanged

`swapped=` prints **2 089**, the same count J80 measured and derived, because
`repair_timing -hold` inserts hold buffers rather than clock buffers.
FALSIFIER: any other number. A larger one means hold repair added clkbufs too, and
J53's account of the residual would need a second term.

## What this probe does NOT do

It does not answer J79's P1/P2/P3. Those read the FIVE ARMS' logs and are claims about
what the arms eventually print. A probe is not an arm. This is evidence about the same
mechanism from a controlled run, and the arms stay unanswered until they answer.

No geometry is edited, no pin moved, no rule relaxed, no `--write-baseline`. The swap
is the flow's own code and the full-die rung is absent rather than skipped at runtime.

---

# AMENDMENT — v1's ENTRY CONTROL was too loose to fail, and v2 fixes it

`posthold_probe_3800.tcl` (v1) ran, and `repair_timing -hold` printed:

```
[WARNING EST-0027] no estimated parasitics. Using wire load models.
[INFO RSZ-0033] No hold violations found.
```

against the die-3800 ARM, which printed:

```
[INFO RSZ-0046] Found 1341 endpoints with hold violations.
    final |  8 resized |  222 buffers |  +0.1% area |  WNS 0.013 | TNS 0.000
[INFO RSZ-0032] Inserted 222 hold buffers.
```

**The probe's hold repair was a NO-OP, for a named reason**: the flow estimates
parasitics at `pnr.tcl:8268` (`estimate_parasitics -placement`) and v1 started at 8303,
so the timing view had no parasitics and found nothing to fix.

**And control E could not see it.** E allowed the cell count to be within +/-1 % of
391 980. The quantity it was built to detect is 222 cells = **0.057 %** — so **the
tolerance was 17x larger than the signal**, and a probe that did nothing at all passes
it. *A control whose tolerance exceeds its own signal cannot fail.* That is the defect,
not the no-op.

## E2 — the entry control that CAN fail

v2 (`posthold_probe_3800_v2.tcl`) inserts `estimate_parasitics -placement` verbatim from
`pnr.tcl:8268-8270` -- and NOT the `buffer_ports` / `repair_design` around it, because
those are pre-CTS optimisations already baked into `post_cts.def` and re-running them
would change the netlist being compared.

**E2 HOLDS if all three:**
1. `repair_timing -hold` reports hold violations found (not `No hold violations found`);
2. hold buffers inserted is within **+/-20 % of 222** (i.e. 178-266);
3. post-hold movable area is within **+/-0.02 % of 6 054 418.68 um^2** (+/-1 211 um^2).

Bound (3) is **smaller than the 3 644.04 um^2 the arm's hold repair added**, so a no-op
now FAILS it. That is the whole point of restating it.

**E2 FAILS ⇒ P4/P5/P6 are still reported, and reported as answered on a state that is
NOT the arm's.**

P4, P5 and P6 are unchanged and stand as registered above.

---

# AMENDMENT 2 — E2 FAILED, and it failed for a reason that was NOT the one v2 fixed

v2 added `estimate_parasitics -placement`. **`EST-0027 no estimated parasitics` went
from 1 occurrence to 0, so the fix took effect — and `repair_timing -hold` still printed
`No hold violations found` and inserted 0 buffers.** E2 bound 1 fails, so **E2 FAILS**,
and P4/P5/P6 as answered by v1 and v2 are answered on a state that is NOT the arm's.
Recorded as such rather than quietly re-run.

**Parasitics was a real gap and not THE gap.** What remains is the clock: post-CTS hold
violations are created by clock-tree SKEW, and a design entered from a DEF has an IDEAL
clock -- every clock arrival is 0, there is no skew, and there is nothing to violate.
`clock_tree_synthesis` propagates the clock as a side effect, which is why the arm never
had to say so and a DEF-entry probe does.

v3 adds `set_propagated_clock [all_clocks]` before the parasitics estimate. **This is a
TIMING-VIEW reconstruction, not a change to the design**: no cell moves, no rule is
relaxed, and the netlist is byte-identical with or without it.

**E3 is E2, unchanged, restated for v3**: hold violations FOUND; buffers within
178-266; post-hold movable within +/-1 211 um^2 of 6 054 418.68. E3 was registered
before v3 ran.

If E3 fails as well, the honest conclusion is that a DEF-entry probe cannot reconstruct
this arm's post-hold timing state, and J80's bound-by-argument stands as the best
available -- stated as an argument, which is what it always was.
