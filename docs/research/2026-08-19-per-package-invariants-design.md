# W7 — per-package invariants: the shape, before the code

Status: DESIGN ONLY. Nothing is enforced yet.

## Why the obvious port does not fit

deepseek-harness @ 99f6f02fe: 54 top-level packages, 226 leaf packages, 219
`invariant.ts`. Their locality is load-bearing because a package is a
publishable unit with its own manifest and build; `scripts/verify-package-invariants.ts`
checks that wiring.

Measured in this tree, directories that directly hold source:

    programs/tests   2635 files
    programs         1184 files
    tools              61
    tools/ci           40
    mcp-eda/test       32
    ... then a tail of 4-15 file directories

Directory-as-package therefore buys nothing where it is needed most: the 1184
flat `programs/` files would be ONE package with ONE file. That is the
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
    owns:    ["*.sh", "*.py"]
    invariants:
      - id:         <globally unique>
        rule:       <prose the contributor reads>
        applies_to: <globs, subset of owns>
        require: / forbid: <regex>

## Who reads it

`programs/package_invariants_check.py`, wired into
`tools/ci/repo_hygiene_gates.sh` — the ONE list both CI workflows and
`gatekeeper_review` invoke. A violation is a red landing gate, not advice.

## What fails

  1. an applicable file violates a declared invariant -> FAIL, attributed
     `<package>: <id>`
  2. an invariant applies to ZERO files -> FAIL (vacuous rule; the repo's own
     "an unmeasured thing reads as a measured zero")
  3. two packages own one file -> FAIL
  4. `package:` disagrees with the file's location -> FAIL
  5. duplicate `id` across packages -> FAIL
  6. a package recorded in the ledger has NO invariant file -> FAIL.
     This is the whole point: a missing invariant must not read as
     "no constraints". The ledger lives OUTSIDE the package
     (`tools/ci/package_invariants_ledger.json`) precisely so deleting the
     package's own file cannot delete the record that it owes one.
  7. discovery finds zero packages -> rc 2 NOT CHECKED, never PASS. This is
     the defect measured in theirs (`scripts/package-invariants.ts:38`, empty
     root -> 0 owners -> exit 0).

## Open, not yet decided

Candidate rules must HOLD on day one or the gate is red on arrival. Two
measured so far that do NOT hold, and are therefore rejected as written:
`set -euo pipefail` in `tools/ci/*.sh` (1 of 11 files) and a module docstring
in `tools/ci/*.py` (7 of 29 missing). Rule selection continues.
