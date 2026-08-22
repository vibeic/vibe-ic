# The F1 guard does not catch F1 — measured, not inferred

Guard: `absence_verdict_names_its_search_space_check.py` from
`origin/jcapsha/capture-sha256-recovery`. Probe module written for this
control; `PYTHONDONTWRITEBYTECODE=1`.

## The control

Four absence verdicts, run through the guard:

| verdict | message | guard |
|---|---|---|
| `PAD_SITE_NOT_FOUND` | the ACTUAL pre-fix message: `...is not a SITE in the IO cell library this run resolved (0 site(s) from 1 LEF(s); PAD-class: [])` | **PASSES** |
| `WIDGET_NOT_FOUND` | `f"{name} is not available"` | **PASSES** |
| `GADGET_NOT_FOUND` | `f"{thing} is not available"` | FAILS |
| `SPROCKET_ABSENT` | `"it is not there"` | FAILS |

    absence verdicts : 4
    naming a locus   : 2
    FAIL: 2 ... probe_prefix.py:21 GADGET_NOT_FOUND
                 probe_prefix.py:25 SPROCKET_ABSENT

## Row 1 is the finding

**The refusal that blocked one design's whole verdict PASSES this guard.** It
passes because it says `LEF(s)`, and `lef` is in `_LOCUS_WORDS`. The message
names a view; the defect was that it named ONE view and there were TWO.

The guard's docstring concedes this in advance — "what it CAN do is refuse an
absence verdict that names no search space AT ALL, which is the state the
pre-fix message would have been in HAD IT NOT CARRIED ITS ONE-VIEW COUNT". That
is an honest disclosure and it is easy to read past. Measured, it means: the
guard written out of F1 does not fire on F1.

So the guard is named `absence_verdict_names_its_search_space` and the property
it decides is `absence_verdict_mentions_a_locus_word`. Those are different
predicates, and the distance between them is exactly the defect:

    a locus word is a place that EXISTS.
    a search space is the set of places that were OPENED.
    "0 site(s) from 1 LEF(s)" names both a count and a view and is still
    a search space of ONE where the PDK declares in TWO.

## Row 2, and the claim I nearly made and did not

`f"{name} is not available"` says nothing whatever about where anything was
looked for. It passes because the interpolated variable is called `name`, and
bare `name` is the last entry in `_LOCUS_WORDS` — a word that denotes the thing
SOUGHT, not the place SEARCHED.

I was about to report that as a hole big enough to drive most refusals through,
because `name` is the commonest variable in a refusal message. **The corpus
says otherwise.** Control: bare `name` dropped from `_LOCUS_WORDS`, guard
re-run over main's 1279 program files:

    with    `name`:  31 absence verdicts, 29 naming a locus, 2 FAIL
    without `name`:  31 absence verdicts, 29 naming a locus, 2 FAIL

Identical. The hole is REAL and demonstrable on a constructed input, and it
accounts for ZERO of main's 29 passes. It is latent, not active. Recorded at
the size the measurement supports and not at the size the mechanism suggested.

## What this does to F1's ladder record

The RULE is unchanged and still Bucket A. What changes is the honest status of
the implementation: it is not "green except for two false positives", it is a
guard that decides a WEAKER property than its name, is blind to the case it was
written for, and reports 2 false positives on top. It is not shippable, and
narrowing the word list would not make it shippable, because the word list is
not the part that is wrong.

## The rule that IS decidable, stated for whoever writes it

Not "does the refusal mention a locus word" and not "is the search space
complete" — the guard's docstring is right that completeness is a property of
the DISTRIBUTION and cannot be decided from our source. The decidable middle:

    an absence verdict must interpolate THE COLLECTION IT ITERATED —
    the actual list of things opened — not a count of it and not a
    word that sounds like a place.

The pre-fix message carried `0 site(s) from 1 LEF(s)`: two counts, no list. A
reader handed the LIST would have seen one path where the PDK declares in two
directories, which is the whole finding. A program can check that the refusal
carries the collection variable that the enclosing scope iterated; it cannot
check that the collection was the right one. That boundary is where Bucket A
ends, and it is further along than the shipped implementation reaches.
