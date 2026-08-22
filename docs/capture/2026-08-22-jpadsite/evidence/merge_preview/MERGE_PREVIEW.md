# Merge preview — re-run against main AFTER it moved

WHY THIS FILE WAS REWRITTEN AGAIN: main advanced 81cd5321b -> a4caccefe
(v1.11.69, 214 commits) while this report was being written, and 3 of those
commits are THIS BRANCH'S OWN WORK landed by another route. Every figure in the
previous version described a tree that no longer exists. Re-run, not carried.

SUBJECT
  branch head ....... 41e6562d2  (jpadsite/pad-site)
  base main ......... a4caccefe  (v1.11.69)
  merged head ....... local preview, NOT pushed

WHAT MAIN ALREADY HAS, MEASURED PER FILE RATHER THAN INFERRED FROM THE LOG
  sha256 of each of the four files, main vs this branch at b95dd8a9f:
      _pad_ring.py         IDENTICAL      pad_ring_gen.py    IDENTICAL
      pad_ring_check.py    IDENTICAL      test_pad_ring.py   IDENTICAL
  HOW, traced: `abf030d08` merged origin/jpadsite/pad-site at 495350370 into
  land/batch70-assembled, so eight of this branch's commits are ancestors of
  main WITH THEIR ORIGINAL HASHES -- not re-hashed, which is what an earlier
  draft of this file guessed from reading the log. `fed57f213` ("take the three
  open PRs at their CURRENT tips, checked by file content") then brought
  b95dd8a9f's content forward BY CONTENT: its patch-id does not match
  b95dd8a9f, which is why main carries the LEF-wins test while b95dd8a9f is not
  an ancestor. ANCESTRY AND CONTENT ARE DIFFERENT QUESTIONS and here they give
  different answers. PR #1765 is OPEN and was NOT the vehicle.

WHAT IS ACTUALLY PENDING
  merge onto a4caccefe:  rc=0, conflicts=0, 2 files, +68 / -10
  one commit: 41e6562d2, the header-count fix and its two tests.
  GitHub shows +1012/-47 because that is against the PR's ORIGINAL base
  a00f53f20. It overstates the live remainder by roughly 15x.

RED ON MAIN, GREEN MERGED -- a control against main AS IT STANDS TODAY, which is
stronger than the original control against the old merge base:
  the two tests, run against a4caccefe with only the test file taken from
  41e6562d2:
      2 failed
        the header's own numbers do not close: it says it names 11 and omits
        8, which is 19, not 20
        header claims 11 named; the modules name 12: [...PAD_FAKE_SITES...]
  the same two on the merged tree:
      2 passed
  the whole pad-ring suite on the merged tree, mount READ-ONLY:
      103 passed

GATES on the merged tree, with the denominator each ruled over
  source_chip_agnostic_check ......... rc=0  1553 files scanned
  silent_decline_audit ............... rc=0  1240 files, 15 known declines
  prose_polarity_consulted_check ..... rc=0  prose extractors, none newly blind
  gate_zero_denominator_refuses_check  rc=0  569 gates probed

NOT REBASED, AND THE REASON. Rebasing onto a4caccefe would make GitHub's diff
show the true 68 lines. Declined, deliberately:
  * the MERGE already produces exactly +68/-10 with 0 conflicts, so the landed
    result is identical either way -- only the DISPLAY differs, and vibe-ic
    lands by merge, not squash;
  * rebasing re-hashes 41e6562d2, and this report and its MANIFEST cite that sha
    throughout, including in commands published for a reader to re-run;
  * the discrepancy is disclosed in the first lines of the PR body, where a
    lander reads it, rather than left for them to discover.
A cosmetic gain is not worth invalidating every citation in the record.
