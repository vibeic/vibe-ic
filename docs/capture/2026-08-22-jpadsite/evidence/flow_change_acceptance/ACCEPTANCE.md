# flow-change-acceptance — the six criteria, run as programs

This change touches `programs/` — a step producer (`pad_ring_gen`) and its gate
(`pad_ring_check`) — so the doctrine is mandatory. Every line below was RUN.

SCOPE OF EVERY RUN BELOW: the pad assignment used is a BALANCED 20/19/19/19
split, which this agent chose. The design DECLARES 40/33/2/2 (L3 "Physical Pad
Placement", L9 9.2.1) and that grouping does NOT fit the die used here — it is
PAD_RING_DOES_NOT_FIT at 2.262 mm and needs 3.762 mm on gf180mcuD or 3.612 mm on
sky130A, both measured. See ../declared_grouping/MEASURED.txt. Nothing below is
wrong; every figure is the measurement actually taken. What is scoped is the
INPUT it was taken with, which none of these files stated until now.

READ EVERY FIGURE BELOW AS **AS-MEASURED AT THE POINT THAT CRITERION WAS RUN**,
not as current state. This file grew by three appends over one session and the
suite, the tree and main all moved underneath it. Where a number here differs
from the current one, the current one is:

    branch head          b95dd8a9f (9 commits), main 81cd5321b (v1.11.68)
    test_pad_ring.py     101 passed in the container;
                         96 passed + 4 skipped on a host with no PDK
    source_chip_agnostic 1550 files scanned (was 1544 before main grew)
    zero_denominator     569 gates probed (was 565)
    corpus sweep verdict now carries its denominator — see ADDENDUM 2

Every stale figure this note covers was left in place rather than rewritten,
because each one is the measurement that was actually taken at that step.

## 1. Bidirectional negative control, GRADED not asserted

    pre-fix (clean a00f53f20 + only the test file), host:
        7 failed, 78 passed, 1 skipped
    pre-fix, in the container where the real PDKs are:
        9 failed, 80 passed
    post-fix, in the container:
        89 passed

    control_substance_check --junit control_prefix_with_real_pdks.xml
        6 of 9 reported failures observed a VALUE
        (c) observed value : 6   <- the substantive control
        (b) presence-only  : 2
        (a) did not collect: 0
        rc = 0

The load-bearing control states the defect in the real PDKs' own numbers:

    AssertionError: a real PDK ships an IO cell library and this step resolved
    no PAD-class site for it: ['gf180mcuD: 15 IO LEF(s), 0 LEF SITE record(s),
    0 tech-view declaration(s)', 'sky130A: 2 IO LEF(s), 0 LEF SITE record(s),
    0 tech-view declaration(s)']

No `*_clears` assertion is offered as a standalone control. Failure NAME SETS
were compared, not counts; no `--maxfail` was used anywhere.

## 2. Corpus sweep — 0 false positives

`corpus_sweep.py` over EVERY PDK tree the pinned image ships (7):

    asap7            0 IO LEFs   — no IO library
    ciel             0 IO LEFs   — no IO library
    nangate45        0 IO LEFs   — no IO library
    ihp-sg13cmos5l   2 IO LEFs   2 LEF SITE records, 0 tech-view  -> LEF path
    ihp-sg13g2       2 IO LEFs   2 LEF SITE records, 0 tech-view  -> LEF path
    gf180mcuD       15 IO LEFs   0 LEF SITE records, 2 tech-view  -> new path
    sky130A          2 IO LEFs   0 LEF SITE records, 1 tech-view  -> new path

    SWEEP VERDICT: CLEAN — 0 false positives

    ^ THE PRE-FIX VERDICT LINE, quoted as it read when this criterion ran.
      ADDENDUM 2 below records that it would have said exactly this after
      scanning NOTHING, and the fix. It now reads: "CLEAN — 0 false positives
      over 7 tree(s), 4 of which ship an IO cell library and could have fired."

This also validates the LEF-first precedence: of the four trees carrying an IO
library, two resolve entirely through the OLD path and are untouched, two
resolve through the new one. No tree needs both and no tree conflicts, so the
one refusal this change ADDS (PAD_SITE_DECLARATION_AMBIGUOUS) fires on none of
them. `corpus_sweep.txt` is the artefact, not a claim in a message.

## 3. Prove-by-run that the gate blocks

Step 15.5ic's gate is `program_exit_zero: pad_ring_check`. Run verbatim on the
real gf180mcuD PDK with the real 77-pad ring, same project both times:

    PRE-FIX   pad_ring_gen rc=1  PAD_SITE_NOT_FOUND: PAD_SITE_NAME='GF_IO_Site'
              pad_ring_check rc=1   -> the step is REFUSED
    POST-FIX  pad_ring_gen rc=0  PASS, 77 pads + 4 corners
              pad_ring_check rc=0   -> the clause PASSES

Not inferred from reading the code. `../gate_ab_PRE_fix_padring.json`.

## 4. No design / PDK / vendor literals

    source_chip_agnostic_check  PASS (1544 files scanned)

The discovery names no flow directory and no library: it scans every directory
under `libs.tech` and keeps only files that declare upstream's own variable.
The synthetic fixtures name no process, foundry or library.

REAL-ARTEFACT BACKING, and why the advisory still reads 0/77.
`real_artefact_test_backing_check` counts tests driven by a CHECKED-IN artefact.
No in-repo artefact declares a pad site — the PDK is not in the repo — so that
count is honestly zero and cannot be made non-zero without inventing a fixture
PDK, which would be the very thing criterion 4 forbids. The real-artefact
backing for this change is the INSTALLED PDK, and it is exercised by three
tests that iterate whatever trees the host has (`_REAL_PDK_ROOTS` +
`$VIBEIC_PDK_ROOT`, the house convention from
`test_extraction_input_blocked_verdict.py`) and skip honestly where there are
none.

MUTATION RUN, which is what actually proves they bite — the fix's load-bearing
branch removed (`resolve_site` never consults a declared site):

    6 failed, 83 passed
    among the dead: test_every_real_pdk_site_resolves_with_a_class_and_a_size
        AssertionError: gf180mcuD: GF_COR_Site listed but unresolvable

A REAL-artefact test is among the dead, which is what the doctrine asks for.

## 5. BLOCKING or ADVISORY declared

Both programs already carry an ENFORCEMENT paragraph in their first 4 kB and
this change does not alter either, nor add a gate.

    flow_gate_enforcement_audit, pre-fix vs post-fix, NAME SETS compared:
        pre : undeclared::area_total_vs_budget_check, undeclared::tapeout_docs_gen
        post: undeclared::area_total_vs_budget_check, undeclared::tapeout_docs_gen
    IDENTICAL — both inherited on main, neither a pad-ring program. This change
    introduces no new enforcement contradiction.

## 6. Degrade loudly, never silently

    silent_decline_audit  [PASS] no NEW silent remedy decline (15 recorded)

Every decline path in the change emits a named record: an unresolvable site is
`PAD_SITE_NOT_FOUND` naming both views and their counts; conflicting
declarations are `PAD_SITE_DECLARATION_AMBIGUOUS` naming every site and file;
discovery that finds nothing returns an empty list which the caller reports as
NOT RESOLVED rather than as an empty table. The report records
`config.site_source` — which view each site came from, and which file — so a
resolved site is never silently indistinguishable from a declared one.

## Compliance gate

    pytest skills/flow-change-acceptance/tests/test_compliance.py
        2 passed, 1 skipped

---

# ADDENDUM — the flow-owner ruling on the extent / rotation defect

Three changes: the along-the-row extent is the master's WIDTH on all four
sides; `PAD_ROTATION_VERTICAL` degrades loudly; the DEF carries the placer's
measured orientation. Re-run of the criteria:

## 1. Control, graded

Targeted at the ruling's own tests, pre-fix in the container:

    10 failed, 1 passed
    control_substance_check --junit control_ruling_targeted.xml
        9 of 10 reported failures observed a VALUE
        (b) presence-only : 1
        (a) did not collect : 0
        (a) collected, body never ran : 0
        rc = 0

The whole-module control is also recorded (`control_ruling.xml`): 21 failed,
44 passed, 34 errors — 17 substantive. The 34 errors are the shared `placed`
fixture failing to place a ring at all on the pre-fix tree once the fixture
carries librelane's DEFAULT rotation, which is real signal but grades as
"collected, body never ran". The targeted control above is the clean one, and
both are kept rather than only the flattering one.

## 2. Corpus sweep — unchanged, still 0 false positives

The ruling changes placement arithmetic, not discovery; the sweep result
stands. The vertical-orientation constants are not PDK-derived and cannot
vary by tree.

## 3. Prove-by-run, at the value a real run actually gets

    DEFAULT_ROTATION_RERUN: PASS pads=77 die=2.262 mm rc=0

sha256 on real gf180mcuD with PAD_ROTATION_VERTICAL at librelane's default R0
— the PDK sets no PAD_ROTATION_* at all, so this is what a user sees:

    pad_ring_gen   rc=0  PASS   77 pads + 4 corners, abuts, 77/77 BTerms
    pad_ring_check rc=0         the flow's own gate clause

Vertical orientations emitted `FW` / `W` — the placer's measured MXR90 / R90.
The spacing VALUES are identical to the earlier non-default run, which is the
check that the geometry no longer depends on the declared rotation. NOT
reproducible today: that earlier run was produced by PRE-RULING code, and under
the ruling R90 returns rc 2, so it cannot be re-run for comparison.

The earlier PASS was taken at a non-default value and does not count; under the
ruling that value is now refused outright (rc 2 NOT DETERMINED).

## 4. No literals — source_chip_agnostic_check PASS (1544 files)

## 5. BLOCKING / ADVISORY — unchanged; no gate added

## 6. Degrade loudly — this is the criterion the ruling turns on

    silent_decline_audit  [PASS] no NEW silent remedy decline

`PAD_ROTATION_VERTICAL` was measurably inert and was being silently honoured.
It now degrades loudly in both directions: at the default it PROCEEDS and the
report carries `rotation_vertical_inert` with the measurement, in EVERY report
including the skips; declared non-default it REFUSES rc 2 NOT DETERMINED,
naming the variable. Tested in both directions, and the disclosure is asserted
present on the skip path too — a disclosure only on the happy path is not one.

Suite: 99 passed in the container, 95 passed + 4 skipped on the host.
prose_polarity_consulted PASS at unchanged baseline.

---

# ADDENDUM 2 — the sweep could have gone green on an empty scan

Prompted by a finding from the publishing agent on a DIFFERENT gate: a hygiene
gate that "passes" because it scanned nothing is green as a property of the
HOST, not of the tree. That is a third state — NOT OBSERVED — distinct from
both PASS and FAIL, and I had the same shape in this directory.

`corpus_sweep.py` printed "SWEEP VERDICT: CLEAN — 0 false positives" whenever
`problems` was empty. A sweep that examined no PDK also has no false positives,
so on any host without the PDKs the artefact would have claimed CLEAN from
looking at nothing. A missing root crashed loudly (fine), but an EXISTING root
with no IO libraries did not.

Fixed: the denominator is now part of the verdict, and an uninformative sweep
refuses to claim CLEAN. Both directions negative-controlled:

    existing root, no PDK tree at all
      -> "NOT OBSERVED — no PDK tree under <root>. Nothing was scanned, so
          nothing was established."
    trees present, none carrying an IO cell library
      -> "NOT OBSERVED — 1 tree(s) under <root>, 0 of them ship an IO cell
          library. There was nothing this check could have fired on, so a green
          here means only that it looked."
    the real run, unchanged conclusion, now with its denominator
      -> "CLEAN — 0 false positives over 7 tree(s), 4 of which ship an IO cell
          library and could have fired."

The SHIPPED CODE was checked for the same shape and does not have it: an
unresolvable site is PAD_SITE_NOT_FOUND naming both views and their counts, and
an unresolved IO library takes the SKIP branch naming `libs.ref` — absence
produces a refusal, never a pass. Only this evidence script was affected.

---

# ADDENDUM 3 — mutation sweep over every load-bearing behaviour

Criterion 1 asks for a control that fails without the fix. That answers "does the
change do something". It does NOT answer "is every behaviour in the change
guarded" — and those differ. Asked the second question by mutating each
behaviour in turn and seeing which the suite still passes. `mutation_sweep.py`.

    declared site class PAD -> CORE                 killed
    conflict detection disabled                     killed
    discovery keeps files with NO declaration       killed
    vertical orient W <-> E swapped                 killed
    along-row extent back to HEIGHT                 killed
    non-default rotation no longer refused          killed
    resolve_site precedence inverted                SURVIVED  <-- was unguarded

SIX OF SEVEN WERE GUARDED. The seventh — the documented rule that the LEF view
wins over the tech-view declaration — could be INVERTED with the suite unchanged
at `96 passed, 4 skipped`. Two reasons it had no coverage, both measured:

  * NO PDK IN THE IMAGE SHIPS BOTH VIEWS. Overlap is empty on all four trees
    carrying an IO library (gf180mcuD lef=0/tech=2, sky130A lef=0/tech=2,
    ihp-sg13g2 lef=2/tech=0, ihp-sg13cmos5l lef=2/tech=0), so no real-PDK test
    can reach the branch;
  * the only existing SITE_SOURCE_LEF assertion used a LEF-ONLY fixture, which
    tests "declaration absent", not "LEF wins".

Fixed by a fixture declaring the same site in BOTH views at different widths,
with the premise asserted first so it cannot pass vacuously. Red against the
mutant, green here (101 in the container).

SECOND SWEEP, BECAUSE THE FIRST DENOMINATOR WAS CHOSEN, NOT MEASURED. Those
seven were behaviours I listed; the diff has more. `mutation_sweep_2.py` covers
the rest:

    _pdk_trees: named tree falls back to ALL         killed
    pad_class_site_names drops the declared half     killed
    site_source provenance never recorded            killed
    rotation_vertical_inert dropped from reports     killed
    gate stops reading the tech view                 killed
    parser accepts a comma-less form                 killed

THIRD SWEEP — THE GUARDS MY CHANGE MADE NEWLY REACHABLE. Sweeps 1 and 2 covered
code the change ADDS. They missed a third category: pre-existing guards that the
change gives a NEW ROUTE to. Before this change only a LEF could supply a
degenerate site; now a tech-view declaration can, and the parser accepts
"0.0, 355" (only a negative width is rejected by the regex).

    zero-width site guard removed                    killed
    site with no SIZE accepted                       killed

Both guarded. And run end-to-end against a PDK declaring a zero-width site, the
program REFUSES rather than crashing on the division in
`between = (space_for_fill // (n + 1) // site_w) * site_w`:

    PAD_SITE_NOT_FOUND: PAD_SITE_NAME='io_site' has width 0, and the spacing
    arithmetic rounds to it        rc 1

COMBINED: 15 behaviours mutated, 14 guarded on the first pass, 15/15 now. That is
a MEASURED claim about coverage rather than a chosen sample — the distinction
this whole record keeps turning on.

The one I most expected to survive was `_pdk_trees`: a behaviour-preserving
refactor of pre-existing code, where a broken refactor would silently restore the
"then scan every tree" fallback that `_pad_ring`'s own header records as having
produced a 130-master table drawn from six unrelated processes. It is guarded.

THE LESSON, and it is why this addendum exists: a passing bidirectional control
tells you the change WORKS. It tells you nothing about which PARTS of it are
protected. The parts with no real-world instance are exactly the parts no
real-artefact test can reach, and they are the ones that need a fixture most.
