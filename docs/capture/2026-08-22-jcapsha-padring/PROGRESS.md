# jcapsha — RETIRED WORKING NOTE. Read `RESULT.md` instead.

This file was the running note taken while the capture was still open. It is
kept only so that a reader who finds a link to it is not left guessing, and its
original body is REMOVED rather than left in place, because two of its three
findings were later overturned by this same lane and a reader arriving here
first would take the overturned versions as current.

WHAT IT SAID, AND WHAT REPLACED IT:

1. It claimed F1's stated generalisation ("say WHICH views you read") does not
   hold, because the pre-fix refusal already enumerated the view it read. That
   observation is CORRECT and survives — see `RESULT.md`, F1. The rule the note
   proposed in its place did NOT survive: it was refuted by its own corpus
   sweep, and the shipped record is
   `refusal_on_absence_falsified_by_the_declaration_grammar`.

2. Its F2 reading of upstream's `pad_cfg.tcl` stands unchanged.

3. It stated that the F3 ladder call turns on "two arguments crossed, inside
   OpenROAD's `make_io_sites`", and said the second arm was being measured
   before the bucket was assigned. THAT SECOND ARM WAS RUN AND THE CONCLUSION
   IS WITHDRAWN. The measurements were right; the inference from them was not.
   The tool's documented contract defines "horizontal" as the horizontally-
   ORIENTED pads, which sit on the east and west rows, and under that
   convention every number measured is documented behaviour. The tool is
   correct. The defect is ours — our side-to-variable mapping is INVERTED with
   respect to that contract — and it ships as the Bucket-A records
   `upstream_convention_not_inverted` and
   `opposite_side_transform_matches_upstream`.
   Full account: `evidence/f3_bucket_T_WITHDRAWN.txt`.

A working note that outlives the work is a register of things that were true
once, and this one had a live Bucket-T accusation against a forked tool at the
top of it. Retired 2026-08-22, in the same lane that overturned it.
