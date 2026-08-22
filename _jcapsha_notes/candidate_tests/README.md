# Candidate test — the red F3d ships with

`test_f3d_opposite_side_is_a_mirror.py` lives here and **not** in
`programs/tests/` on purpose: it fails on `main` today, and landing a red test
would block every push on the repo. It is the artefact the fix ships with, and
it should move into `programs/tests/` in the same commit that fixes the defect.

## The red, in full — MEASURED 2026-08-22, load 94.84 on 32 cores

Both files, run together. The load belongs beside the numbers; these are
0.43s AST reads with no subprocess and no timeout, so the load does not reach
them, and saying so is cheaper than leaving a reader to wonder.

```
FAIL test_f3c_side_to_variable_mapping.py::
       test_each_rotation_variable_drives_the_sides_upstream_says_it_does
     each rotation variable must drive the sides its upstream defines it for:
       PAD_ROTATION_HORIZONTAL: ours drives ['N','S'], upstream defines it for ['E','W']
       PAD_ROTATION_VERTICAL:   ours drives ['E','W'], upstream defines it for ['N','S']

FAIL test_f3d_opposite_side_is_a_mirror.py::
       test_the_opposite_side_is_derived_by_MIRRORING_as_upstream_does
     the opposite side must be derived by upstream's MIRROR, not a half turn:
       side N: derived with ['rotate_cw'] (a ROTATION)
       side E: derived with ['rotate_cw'] (a ROTATION)

PASS test_f3d_opposite_side_is_a_mirror.py::
       test_the_footprint_assertion_cannot_see_the_defect

2 failed, 1 passed
```

THIS TRANSCRIPT REPLACES A STALE ONE, and the staleness is worth naming because
this capture is *about* that failure mode. The previous version of this file
printed an eight-line orientation table under two test names that no longer
exist: the rewrite recorded three lines below — the one that made the F3d test
satisfiable — renamed its test and changed its predicate from an orientation
table to a call-site read, and this README was not re-run against it. A reader
following it would have grepped for a test that is not there. Re-measured, not
edited to match.

## The first test in the file is a demonstration, not coverage

`test_the_footprint_assertion_cannot_see_the_defect` **passes on the broken
tree, and that is its purpose.** It writes out the obvious test — assert on the
footprint — and shows it agreeing under both a mirror and a half turn, because
a rectangular master occupies the same bounding box either way. It is there so
the next author does not write that assertion, watch it pass, and believe the
question is covered.

RESTORED 2026-08-22, having been dropped by the rewrite while this README went
on describing it. So for a while the file's stated protection did not exist —
the exact shape it was written to prevent. GRADED, so it is not vacuously true:

```
ours = rotate_cw('S',2) = N   footprint (75000, 350000)
upstream = flipX('S')  = FN   footprint (75000, 350000)  equal -> blind
a ROTATED 'W'                 footprint (350000, 75000)  differs -> has teeth
```

It also asserts `ours != upstream` first, so if a fix ever makes the two
derivations agree the demonstration fails as STALE rather than passing on for
a reason that has gone away.

## The three states, measured

```
current tree                RED    side N and side E derived with rotate_cw (a rotation)
same test, fix applied to    GREEN  side N -> flip_x, side E -> flip_y
a scratch copy                      (the repo tree was never modified)
```

The green half is not decoration. A test that goes red proves it detects
something; only the green proves it detects the RIGHT thing and that a correct
fix can satisfy it.

## The version of this test that could never go green

The first version asserted `rotate_cw(o, 2) == flipX(o)` — that the ROTATION
helper should behave like a mirror. It was red on the broken tree, which looked
like success. But `rotate_cw` is correctly named and correctly implemented, and
a correct fix does not touch it: it adds a mirror and changes the CALL SITE. So
that test would have stayed red after the bug was fixed — **unsatisfiable**.

An unsatisfiable test gets muted, and muting it is indistinguishable from the
defect being fixed. It was rewritten to look at the call site, which is what
actually has to change. Recorded because the red looked exactly as convincing
either way.

## An error this file caught in its own author

The first version of the flip table had the `E` and `W` entries exchanged. The
oracle was wrong, and a test with a wrong oracle reports divergences that belong
to the test. Writing the table out against the tool's own orientation algebra —
R0↔MX, R90↔MXR90, R180↔MY, R270↔MYR90 — caught it. The comment stays in the
file so the correction is visible rather than silently absorbed.

---

# The second red — `test_f3c_side_to_variable_mapping.py`

Pins which SIDES each rotation variable drives, against the tool's documented
contract. It reads our mapping out of the source rather than restating it.

```
origin/main                RED   HORIZONTAL -> [N,S] (should be [E,W])
                                 VERTICAL   -> [E,W] (should be [N,S])
origin/jpadsite/pad-site   RED   HORIZONTAL -> [N,S] (should be [E,W])
                                 VERTICAL   -> (nothing)
```

The second block is the finding: **the un-landed fix does not resolve this and
removes the variable's effect instead of routing it**, because it was built on
the conclusion that the variable is inert. It is not inert — it is misrouted by
us, and in the tool it drives the two sides the fix left to the other variable.
