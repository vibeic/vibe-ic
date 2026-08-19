# W7 — per-package invariants: the shape, and what shipped

Status: SHIPPED and ENFORCED. `programs/package_invariants_check.py`, wired into
`tools/ci/repo_hygiene_gates.sh`. This file was written as DESIGN ONLY before
the code; the sections below now record what was built and where the design
changed under measurement.

## Why the obvious port does not fit

deepseek-harness @ 99f6f02fe: 54 top-level packages, 226 leaf packages, 219
`invariant.ts`. Their locality is load-bearing because a package is a
publishable unit with its own manifest and build;
`scripts/verify-package-invariants.ts` checks that wiring.

Measured in this tree, directories that directly hold source:

    programs/tests   2636 files
    programs         1211 files
    tools              62
    tools/ci           45
    mcp-eda/test       32
    ... then a tail of 4-15 file directories

Directory-as-package therefore buys nothing where it is needed most: the flat
`programs/` files would be ONE package with ONE file. That is the
mechanism-transplant failure the source study already argued against.

## The unit

A package is a scope declared by exactly one invariant file, and **the file's
own path determines what it may own**:

  * `<dir>/INVARIANTS.yaml`            owns `<dir>/**` (nested tree)
  * `<dir>/<prefix>.INVARIANTS.yaml`   owns `<dir>/<prefix>*` (flat namespace)

Exclusive ownership falls out of the path rule: a package cannot reach outside
its own directory, and two packages claiming one file is a refusal (their
`invariants/src/index.ts:140-142`, ported).

## What a package declares

    package: tools/ci
    invariants:
      - id:             <globally unique>
        rule:           <prose the contributor reads>
        applies_to:     <globs, package-relative>
        excludes:       <globs, optional>
        require: / forbid: <regex>
        counterexample: <text this rule MUST reject>

CHANGED FROM THE DESIGN. Two things:

* `owns:` was dropped. It restated what `applies_to` already says, and two
  places stating one scope is a place for them to disagree.
* `counterexample:` was ADDED, and is mandatory. Every `forbid` rule here is
  expected to match zero files — that is the healthy state for a prohibition,
  and it is also exactly what a typo in the regex looks like. The checker
  verifies on every run that the counterexample is rejected by the rule that
  ships it; one that is not is TOOTHLESS and refused. This also makes the
  test suite's mutation arm self-extending: it plants each rule's own
  counterexample in a real file that rule applies to, so a rule added later is
  proved to discriminate with no test edited.

## Who reads it

The contributor, because it is in the directory they are already in.
`programs/package_invariants_check.py`, wired into
`tools/ci/repo_hygiene_gates.sh` — the ONE list both CI workflows and
`gatekeeper_review` invoke. A violation is a red landing gate, not advice.

That wiring is a PROTECTED landing-authority path, and it is not optional:
`checker_execution_wiring_audit`, itself a blocking gate in the same list,
FAILS a checker that only its own test runs. The suite alone would also have
been too weak — `ci_targeted_test_select` reports the declaration files as
UNMAPPED, so a patch-cadence PR violating a declared invariant would run
nothing that could see it.

## What fails

  1. an applicable file violates a declared invariant -> FAIL, attributed
     `<package>: <id>`
  2. an invariant applies to ZERO files -> FAIL (vacuous rule; the repo's own
     "an unmeasured thing reads as a measured zero")
  3. an invariant's counterexample does NOT violate it -> FAIL (TOOTHLESS)
  4. two packages own one file -> FAIL
  5. `package:` disagrees with the file's location -> FAIL
  6. duplicate `id` across packages -> FAIL
  7. a package recorded in the ledger has NO invariant file -> FAIL.
     This is the whole point: a missing invariant must not read as
     "no constraints". The ledger lives OUTSIDE the package it records
     (`programs/package_invariants_ledger.json`, beside the checker and inside
     no package) precisely so deleting the package's own file cannot delete the
     record that it owes one. The comparison is exact-set equality both ways,
     so an unledgered declaration is a refusal too.
  8. discovery finds zero packages -> rc 2 NOT CHECKED, never PASS. This is
     the defect measured in theirs (`scripts/package-invariants.ts:38`, empty
     root -> 0 owners -> exit 0).

The residual, stated rather than implied: deleting BOTH the declaration and its
ledger row passes the checker. Nothing makes a register unforgeable against an
author willing to edit every copy of it. The membership is pinned a third time
in `test_package_invariants_check.LEDGERED_PACKAGES`, so the deletion costs
three visible edits instead of one, and the last of them is in a test.

## Rule selection

Candidate rules must HOLD on day one or the gate is red on arrival. Two
measured candidates that do NOT hold were rejected as written: `set -euo
pipefail` in `tools/ci/*.sh` (3 of 11 files carry it) and a module docstring in
`tools/ci/*.py` (7 of 29 missing). What shipped is six packages and nine rules,
each measured to hold over its whole applicable population before it was
written down, and each reverted afterwards to confirm it fires.

One rule is worth naming for the trap it encodes. `l9-program-names-the-layer-
it-owns` uses `(?<![A-Za-z0-9])L9(?![0-9])` rather than `\bL9\b`, because `\b`
does not match between a letter and an underscore: measured over the 58
`l<N>_*` programs, the naive boundary reports `l21_doc_supply_rail_synth.py` as
silent when its only mention is `L21_POWER_INTENT`. The `_`-aware boundary
gives 58 of 58. It is the same trap `gate_discloses_denominator_check`
documents for this repo's SKIP/VACUOUS vocabulary.
