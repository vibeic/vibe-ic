# Candidate test — the red F3d ships with

`test_f3d_opposite_side_is_a_mirror.py` lives here and **not** in
`programs/tests/` on purpose: it fails on `main` today, and landing a red test
would block every push on the repo. It is the artefact the fix ships with, and
it should move into `programs/tests/` in the same commit that fixes the defect.

## The red, in full

```
PASS  test_the_extent_assertion_cannot_see_the_defect
FAIL  test_the_opposite_side_is_the_upstream_MIRROR_not_a_half_turn
      the opposite side must be upstream's MIRROR, not a half turn:
        from N: ours=S  upstream(flipX)=FS      from FN: ours=FS upstream=S
        from S: ours=N  upstream(flipX)=FN      from FS: ours=FN upstream=N
        from E: ours=W  upstream(flipX)=FE      from FE: ours=FW upstream=E
        from W: ours=E  upstream(flipX)=FW      from FW: ours=FE upstream=W
```

All eight orientations diverge. The first line — `from N: ours=S,
upstream=FS` — is the case that was MEASURED end to end: our step records the
north side as `S` while the tool places the north pad at `MX`, which is `FS`.

## The first test in the file is a demonstration, not coverage

`test_the_extent_assertion_cannot_see_the_defect` **passes on the broken tree,
and that is its purpose.** It writes out the obvious test — assert on the
footprint — and shows it agreeing under both a mirror and a half turn, because
a rectangular master occupies the same bounding box either way. It is there so
the next author does not write that assertion, watch it pass, and believe the
question is covered.

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
