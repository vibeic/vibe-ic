# main moved 673 commits under this branch, and the clean merge was broken

Every number reported on this branch before this point was measured against
`a4caccefe`. A routine re-poll before a push — the same one that had answered
"0 commits landed" eight times running — answered **673**.

    my base   a4caccefe
    main now  ae78abb28
    landed    673

## What that changed

* **`phase3.pad_ring` IS NOW ON MAIN.** Someone else landed the routing entry I
  added. My copy of it is redundant, and the merge resolution drops it in
  favour of main's. The measured claim "the flow declares the step and
  CAPTURE_ROUTING carries no entry" was TRUE when measured and is FALSE now;
  the red recorded in `RED_routing_entry.md` still describes what the state was
  and is labelled by base sha.
* **The F4 defect is still live**: main at `ae78abb28` still carries 6 `inert`
  identifiers in `pad_ring_gen.py`. The fix is still needed.
* **`jpadsite/pad-site` still has NOT landed** — so the NORTH and CORNER
  orientation fixes I independently confirmed are still absent from main.
* `upstream_contract_parity_check.py` is still absent from main — no collision.

## The merge, and the semantic conflict a clean merge missed

    CONFLICT: benchmark/CAPTURE_ROUTING.json
    CONFLICT: programs/tests/test_pad_ring.py
    (programs/_pad_ring.py auto-merged)

Both conflicts were ADDITIVE ON BOTH SIDES — main added new routing steps and
new tests, I added mine at the same places. Resolved by UNION, never by
choosing: main's 64 steps ∪ my `repo.upstream_parity` = 65; main's test file
plus my two grafted tests.

**And that resolution was wrong in a way the merge could not see.** Taking
main's `test_pad_ring.py` wholesale and grafting only my NEW tests silently
dropped my EDITS to two of its EXISTING tests — the renames and the body
changes from `rotation_vertical_inert` to `rotation_vertical_not_honoured`.
`pad_ring_gen.py` merged with my key rename; the test file merged without it:

    FAILED ...::test_the_default_vertical_rotation_proceeds_and_is_told_it_is_inert
    FAILED ...::test_the_inert_disclosure_is_in_every_report_including_the_skip
    2 failed, 206 passed

Textually clean, semantically broken — exactly the shape that makes "the merge
had no conflicts" worthless as evidence. Caught only by running the merged
tree. Re-applied the two edits; **208 passed, 16 skipped, rc 0**.

## Verified after the merge

    upstream_contract_parity_check.py     PASS, 3 entries, rc 0
    pytest (pad_ring + parity + 2 pins + routing + emit + hygiene)
                                          208 passed, 16 skipped, rc 0
    plugin_full_audit                     D1 PASS, D2 PASS

A backup tag `jcapsha-premerge-backup` marks the pre-merge tip (`0a0c1f71f`)
so nothing on this branch depends on my having resolved correctly.

## The lesson, at the size it deserves

I re-polled before a push because the discipline says to, not because I
suspected anything — the previous eight polls had all said 0. A branch that had
been "verified green" for its whole life was, for some unknown part of that
time, verified against a base that no longer existed. **A verification is only
as current as its last re-poll, and "it was 0 last time" is not a measurement.**

## The merge is NOT published, and the pre-push gate is why

Pushing the merge would have republished main's 673 commits on this ref, and
the hook refused it:

    pre-push: FAILED — no collateral revert within the push
      COLLATERAL REVERT: 25 finding(s) in 674 commit(s). 2be4c0b42 removes 52
      of the 68 line(s) 7027c15ce added to _jcapsha_notes/candidate_tests/… —
      and 7027c15ce is being published by THIS SAME push.

Checked before doing anything about it: **both flagged commits are already
ancestors of `origin/main`.** They are from an older lane of mine that someone
landed, and the revert is inside main's own published history. The gate is
correct about the shape and the shape is not mine — it only appears because a
merge-forward republishes main's history on this ref.

So the fix is not to argue with the gate and not to `--no-verify` it. **The
merge was a verification, and a verification does not need to be published.**
The branch is reset to its own 25 commits (`jcapsha-premerge-backup`,
`0a0c1f71f`); a lander merges onto current main themselves, which is the normal
shape and exactly what this file tells them to expect.

## What the merge changed on the branch, kept

* **`phase3.pad_ring` adopted VERBATIM from main.** Someone landed their own
  version — same `bucket_A_program`, different description and a different
  Bucket B skill. Mine is gone; main's is copied in byte-for-byte, so the entry
  merges as a no-op instead of a conflict, and the branch still routes its own
  records standalone. Two people writing the same routing entry independently
  is the entry having been missing, and only one of them needs to survive.
* `repo.upstream_parity` kept — still absent from main.
* The two test edits and the general guard are mine and unaffected.

MEASURED on the merged tree before the reset: 208 passed, 16 skipped, rc 0;
checker PASS 3/3; `plugin_full_audit` D1 PASS / D2 PASS at 1273 programs.
