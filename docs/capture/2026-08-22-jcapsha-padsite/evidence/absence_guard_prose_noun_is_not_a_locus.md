# The absence-verdict guard passes a verdict that names no place

Measured against `jcapsha/capture-sha256-recovery` @ `0c1a7b4c8`, in a detached
worktree, `PYTHONDONTWRITEBYTECODE=1`, tree verified clean before and after.

## Baseline — the guard is clean and its denominator is real

    absence_verdict_names_its_search_space_check     rc 0
      files parsed : 1278   absence verdicts : 31   naming a locus : 31
    upstream_mirror_is_pinned_check                  rc 0
      files parsed : 1278   declared mirrors : 3    undeclared candidates : 0

Its own tests: 31 passed, 7 skipped.

## The in-situ mutation that SHOULD have gone red, and did not

`erc_density_check.py:194` ships this refusal, and the guard counts it among
the 31 that name a locus:

    "No density artefact (reports/density.json or reports/density.rpt) "
    "found — the Step-31 density sub-check cannot verify substance"

Both path literals were removed — the whole of what tells a reader where it
looked — leaving:

    "No density artefact was "
    "found — the Step-31 density sub-check cannot verify substance"

Re-run on the mutated tree (`absence_guard_mutation_stayed_green.txt`):

    MUTATED-TREE RC=0
      files parsed : 1278   absence verdicts : 31   naming a locus : 31
      PASS: every absence verdict names where it looked.

Still 31 of 31. The mutation was then reversed and `git status` re-verified clean.

## Why — reproduced in isolation, one word apart

Two synthetic verdicts, identical in structure, differing only in the noun:

    "No density artefact was found - the sub-check cannot verify substance"   PASS
    "No widget was found - the sub-check cannot verify substance"             FAIL

The guard's positive control therefore works: it does fire on a locus-free
verdict. What it accepts as a locus is the mechanism:

    programs/absence_verdict_names_its_search_space_check.py:165-169
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            ...
            # A literal that spells a locus word ("no LEF view was opened").
            if _LOCUS_NAME.search(n.value):
                return True

and `--explain` lists `artefact` and `artifact` among the locus words.

## The distinction the vocabulary does not draw

The guard's own standard is that a reader must be able to tell "I looked in the
two places this is declared and it is in neither" from "I looked in one of
them". `No density artefact was found` fails that standard completely — it
names the missing THING, not any place — and passes anyway.

The vocabulary mixes two kinds of word:

  PLACE words, which do disclose where — `path`, `dir`, `directory`, `root`,
  `glob`, `tree`, `where`, `searched`, `scanned`, `looked`, `corpus`,
  `location`, `view`, `section`. The code comment's own example, "no LEF view
  was opened", is one of these and is correctly accepted.

  THING words, which are simply the noun a verdict about absence is about —
  `artefact`, `artifact`, `file`, `files`, `document`, `manifest`, `report`,
  `config`, `name`, `candidates`. In prose these carry no locus at all, and an
  absence message can hardly avoid containing one.

This is not the generosity the docstring discloses. That disclosure covers
saying it IMPRECISELY; this passes a verdict that says NOTHING, which is the
state the guard exists to refuse.

## Scope, stated

This is a FALSE NEGATIVE in a guard, not a defect in a shipped verdict. Every
one of the 31 real verdicts may well carry a genuine locus — the point is that
the guard would not notice if one stopped. The mutation above is the proof.

NOT PROPOSED BLIND: splitting the vocabulary so only PLACE words satisfy the
prose-literal branch (THING words still counting when they are identifier names
or accompany a path literal) must be MEASURED against the 31 before it ships. A
guard that fires on the state we just shipped is a bug, not a guard. This lane
did not make that change — the guard belongs to the lane that wrote it.
