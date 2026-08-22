# F1's rule turned on my own checker — its PASS did not say what it compared

## How this surfaced

I went looking for whether my two pin tests SKIP in CI, because a pin that
never runs where the gate matters is decorative. That question is still open
(there is no `.github/workflows/`, and skipping on a missing environment has
precedent here — `test_pad_ring.py`:851 skips with "no `PDK_ROOT` on this
host"). But the search turned up something worse, in code I shipped on this
branch.

## The defect

`upstream_contract_parity_check.py` re-reads the upstream file and compares it
against the register's snapshot ONLY when `--distribution-root` is supplied.
Without one, the register's recorded snapshot IS the denominator. The verdict
said nothing about which:

    PASS: 3 registered re-implementation(s); every upstream name and every
          registered computation is accounted for.

Byte-identical output in both modes. So a reader could not tell

    "our re-implementations agree with UPSTREAM"

from

    "our re-implementations agree with OUR OWN RECORD of upstream"

and only one of those is a statement about upstream. **That is F1's class
exactly** — "not found" versus "not looked for", one level up, in the program
written to enforce the lesson. The register's whole premise is that a claim
about an upstream file must be a claim a machine can lose; its own verdict was
not saying which claim it had checked.

## The fix

A BASIS line, printed at EVERY verdict beside the denominator — the file
already holds that discipline for counts and did not hold it for provenance.

    $ upstream_contract_parity_check.py
      BASIS: the register's RECORDED SNAPSHOTS for all 3 entry/entries.
             Upstream was NOT re-read on this run — pass --distribution-root to
             compare against a live distribution. This verdict is about our
             code against our own record.
      PASS: 3 registered re-implementation(s); ...

    $ ... --distribution-root /usr/local/lib/python3.12/dist-packages   (in the image)
      BASIS: upstream re-read under /usr/local/lib/python3.12/dist-packages
             for 3 of 3 entry/entries.
      PASS: 3 registered re-implementation(s); ...

## A result that falls out of it

The second run is the first time all three entries have been re-verified
against a live distribution in one pass: **3 of 3, PASS, inside
`ghcr.io/vibeic/vibeic-eda:0.3.24`**. Every recorded sha256 in the register is
byte-current with the shipped image.

## The reds

Three tests, one of them asserting the disclosure appears at a FAILING verdict
too — a disclosure only on the happy path is not one.

Mutation: the `_basis_line` CALL removed, the helper deliberately LEFT in the
source so the mutation cannot pass by deleting the string the tests grep for:

    MUTATION APPLIED: call removed, helper left in place
    FAILED ...::test_a_pass_without_a_distribution_says_it_compared_against_its_own_record
    FAILED ...::test_a_pass_with_a_distribution_says_how_many_entries_it_re_read
    FAILED ...::test_the_basis_is_printed_at_a_failing_verdict_too
    3 failed, 22 passed

    restored -> 25 passed, checker byte-identical

## Why this one matters more than its size

Every other instance of this class on this branch was in code someone else
wrote. This one is mine, shipped on this branch, in the program whose entire
purpose is to stop a claim about upstream from going unchecked. The rule found
its author.
