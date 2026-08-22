# A zero-denominator `ALL_PASS`, in a program the gate for that defect cannot see

_Measured 2026-08-22 on host `8hd-3` against `next/protected-tuple-drift-attribution`
at `f860235c6`. Repository tooling only: no design, PDK, vendor or part
identifier appears._

## The instance

    $ python3 programs/protocol_detector_no_misfire_matrix.py --benchmark-dir <EMPTY DIR>
    [no-misfire] blob=generated  detectors=86  benchmarks=0

    ALL_PASS
    rc=0

Zero benchmarks examined, and the verdict is `ALL_PASS`. Reproduced with a
genuinely empty directory, so it is not an artefact of unreadable input.

To its credit the program DISCLOSES the zero — `benchmarks=0` is printed. The
defect is not concealment, it is the verdict word: an empty population is NOT
OBSERVED, and `ALL_PASS` at rc 0 is indistinguishable to any caller from 86
detectors having been checked against real benchmarks and passing.

## The repository already forbids this

`programs/gate_zero_denominator_refuses_check.py` exists for exactly this shape.
Its own docstring: _"`analysed 0 files` is not a result"_. Run on this tree it
passes:

    569 gate(s) probed, each against its OWN fresh empty project;
    25 stated a zero population, of which 24 refused and 1 exited 0
    (1 exempted, 0 unrunnable)

## Why it does not catch this one

    population of gate_zero_denominator_refuses_check   570
    PROGRAM_INVENTORY.json, gate_programs_check_suffix  570
      definition: "Top-level programs whose filename ends in _check.py"

    protocol_detector_no_misfire_matrix.py in that population?   NO

The gate's population is FILENAME-SHAPED. `protocol_detector_no_misfire_matrix.py`
does not end in `_check.py`, so it is not probed — not exempted, not passed, not
seen. 691 of the 1261 top-level programs are outside that population.

## Why this document exists

The companion finding
[`the wiring audit population is filename-shaped`](2026-08-22-the-wiring-audit-population-is-filename-shaped.md)
argued that a name-shaped population makes programs invisible. That argument was
structural: it counted what could not be seen, without showing a defect that had
actually escaped through the gap.

This is that defect. The same naming convention hides a program from the gate
written to forbid the exact thing the program does. It was found by pointing a
hostile-input probe at programs OUTSIDE the audited population — which is only
possible if you first stop defining the population by name.

## What is NOT claimed

That `ALL_PASS` on zero benchmarks is wrong in every context. The program may
have a caller that supplies a non-empty directory always, and may be documented
elsewhere as requiring one. What is claimed, and measured, is narrower:

  * the shape is one this repository has written a gate to forbid, and
  * that gate cannot see this program, for a reason that has nothing to do with
    the program's behaviour and everything to do with its filename.

The remedy is the one the companion document already proposes: define these
populations by STRUCTURE, keeping the filename suffix as one contributor
asserted to be a subset. That is a landing owner's call. This document does not
change the program, the gate, or the gate's population.
