# Guards that slice a fixed number of bytes of source — a census, and one proven casualty

agent `jred-ppa` · host 8HD-4 · 2026-08-22
subject **`a4caccefe`** (v1.11.69)

A recurring idiom in this test tree: find an anchor in a program's source, slice
a FIXED NUMBER OF BYTES from it, and assert something is inside that slice.

    start = SRC.index("<anchor>")
    window = SRC[start:start + 3000]
    assert "<thing>" in window

It reads as "check the region around the anchor". It is not. It is "check the
first N bytes", and the two diverge the moment the region grows — which is the
one thing a region under active development does.

**It fails SILENTLY-WRONG rather than loudly.** The slice does not report "I
could not see the whole region"; it answers about the part it saw. So the guard
either misses what moved past the cut, or — worse — reports a confident finding
about something else.

---

## 1. The proven casualty

`test_matrix_d6_skip_discipline::test_d6_every_tier_moving_hint_is_either_
accepted_or_excluded_by_name` sliced `src[start:start + 3000]` of
`flow_compliance_check`'s tier chain and asserted every dispatched hint prefix
is classified.

`_INCOMPLETE_HINT_PREFIX` is dispatched in that chain **at +3369 bytes** — 369
past the cut — and was classified NOWHERE. Measured on pristine `a4caccefe`
with nothing applied:

    old 3000-byte window   1 passed        (blind)
    whole enclosing region FAILS, naming _INCOMPLETE_HINT_PREFIX

**The leg written to guarantee "every tier-moving hint is accepted or excluded
by name" has been green on a tree carrying exactly that defect.**

It also produced a FALSE finding. Adding one branch to the chain pushed
`_NOT_APPLICABLE_HINT_PREFIX` and `_SUBSTANTIVE_HINT_PREFIX` out of the window;
`dispatched` shrank and the gate reported those two as STALE EXCLUSIONS. Both
are still dispatched. `test_issue599`'s 700-byte window reddened the same way
for the same reason.

Both are fixed on `next/tier-chain-guards-read-the-whole-region-not-a-byte-count`
by reading the region structurally — the enclosing function via `ast`, and the
list to its own closing bracket — each asserting the new region is at least as
long as the window it replaces, so it cannot quietly shrink back.

---

## 2. The census — EIGHT more sites, all currently green

Positive assertions over a fixed source window, excluding slices used only to
truncate an error message:

    test_issue563r3_spare_tieoff_measured_and_legalized.py:289    2500
    test_issue595_registration_grid_measurement.py:140            2600
    test_issue599_incomplete_and_substantive_tiers.py:181         1400
    test_issue599_tb_dir_resolution.py:112                        1800
    test_issue614_skip_is_not_a_mismatch.py:129                   2600
    test_issue614_skip_is_not_a_mismatch.py:141                   2600
    test_issue614_skip_is_not_a_mismatch.py:148                   2600
    test_min_area_patch_blockage_set_is_not_stale.py:130          4000

    all six files: 76 passed, 1 skipped

**NONE IS BROKEN TODAY and none was changed.** Fixing eight guards that pass, on
the strength of a pattern argument, is churn — the same call made about
`transition_fault_atpg_run.py:724` in the magicrc lane, and for the same reason:
a repair without a failing measurement behind it is a change nobody can check.

---

## 3. HEADROOM — measured, and none of the eight is close

The number that decides whether any of these matters is "how far into its window
does the asserted content actually sit". A site at 99% is one comment away from
the D6 failure; one at 20% is not.

A FIRST PROBE FOR THIS WAS WRONG and its numbers were withheld: it reported each
token's ABSOLUTE offset in the file rather than its offset relative to the
window's anchor, producing figures like 51059 for a 2600-byte window. Redone
per-site, resolving each anchor and each source module from the test itself, and
counting only POSITIVE assertions — a `not in` assertion cannot be broken by the
region growing, so including one would have inflated the risk.

    site                             win   furthest end   spare    used
    test_issue614:141               2600           1848     752   71.1%
    test_issue614:129               2600           1773     827   68.2%
    test_issue599_incomplete:181    1400            900     500   64.3%
    test_min_area_patch:130         4000           2013    1987   50.3%
    test_issue614:148               2600           1106    1494   42.5%
    test_issue595:140               2600            766    1834   29.5%
    test_issue563r3:289             2500            539    1961   21.6%

**NONE IS AT RISK.** Nothing exceeds 85%; the tightest has 500 bytes of
headroom, roughly ten lines. By contrast D6 failed because its asserted content
sat at **112%** of its window — outside it entirely.

So the census resolves: the idiom is systemic, ONE instance was demonstrably
blind, and the remaining eight have room. That is the answer to "do these need
repairing now" and it is NO. It is not an argument that the idiom is sound —
`test_issue614` at 71% is two moderate edits from the same failure, and it will
fail the way D6 did, silently and with a confident wrong finding.

---

## 4. The shape of a fix, when one is warranted

Not "make the window bigger" — that is the same defect with a larger constant.
Find the region by STRUCTURE:

  * the enclosing function or class, via `ast` (`end_lineno` gives the real span);
  * a bracketed literal read to its closing bracket;
  * an explicit end-anchor, asserted to exist.

And assert the region is at least as long as the constant it replaces, so the
change is provably a superset and a later edit cannot shrink it back silently.
