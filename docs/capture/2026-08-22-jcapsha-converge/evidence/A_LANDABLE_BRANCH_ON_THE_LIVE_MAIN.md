# A second branch: the same delta, on the main that exists

## Why

`jcapsha/converge-capture-distill` is based on `a4caccefe`; main is at
`ae78abb28`, 673 commits later. A lander merging it hits the same two conflicts
I hit, and — measured — the obvious resolution of one of them is semantically
broken in a way the merge cannot show. Leaving that for someone else to
rediscover is leaving a trap.

Merging main INTO my branch was refused by the pre-push gate, correctly: it
republishes main's 673 commits on the ref and trips collateral-revert on a pair
of commits already in main's own history. **The gate names its own remedy:**

    A land that replaces a file wholesale from a stale branch does this;
    applying the branch's OWN delta (`git diff <merge-base>..<branch>`) does
    not.

So that is what this is.

## What it is

    branch   jcapsha/land-on-current-main
    base     ae78abb28  (origin/main, v1.11.70)
    content  git diff a4caccefe..jcapsha/converge-capture-distill, applied
             with `git apply --3way`, conflicts resolved, ONE commit
    pushed   clean — the collateral-revert gate passes, which is the
             confirmation that the remedy it names actually works

## The two conflicts, resolved by union, never by choosing

* **`CAPTURE_ROUTING.json`** — main's 64 steps ∪ `repo.upstream_parity` = 65.
  `phase3.pad_ring` landed on main independently while this work was in
  flight; this branch takes **main's entry verbatim** and drops its own. Two
  people writing the same routing entry is the entry having been missing, and
  only one of them needs to survive.

* **`tests/test_pad_ring.py`** — main's file, plus my two NEW tests, **plus the
  two edits to its EXISTING tests that a wholesale take silently drops**. That
  omission is the whole lesson from the first attempt: `pad_ring_gen.py` merged
  WITH the key rename and the test file merged WITHOUT it, giving

      FAILED ...::test_the_default_vertical_rotation_proceeds_and_is_told_it_is_inert
      FAILED ...::test_the_inert_disclosure_is_in_every_report_including_the_skip
      2 failed, 206 passed

  Textually clean, semantically broken. Nine separate edits re-applied here,
  each verified present.

## Measured on the landable tree

    upstream_contract_parity_check.py   PASS, 3 entries, rc 0
    pytest (pad_ring + parity + both upstream pins + routing + emit + hygiene)
                                        208 passed, 16 skipped, rc 0
                                        suite_write_guard: wrote nothing
    plugin_full_audit                   D1 PASS, D2 PASS (1273 programs)

## Which branch is which

| branch | base | what it is |
|---|---|---|
| `jcapsha/converge-capture-distill` | a4caccefe | the work and its full record — 28 commits, every measurement, every retraction, every self-correction |
| `jcapsha/land-on-current-main` | ae78abb28 | the same change as ONE commit on the live main, verified green, directly landable |

The record branch is the one to READ. The landable branch is the one to MERGE.
They carry identical content; only the base and the commit granularity differ.
