# Every load-bearing number, re-measured against the base that actually exists

The previous file records that main moved 673 commits under this branch. That
makes a claim, not a conclusion: it says the numbers MIGHT have drifted, and
leaving it there would be exactly the "it was 0 last time" reasoning that file
was written to name. So each load-bearing figure was re-measured.

    measured at   a4caccefe   (my base, dead)
    re-measured   ae78abb28   (origin/main, v1.11.70)
    method        detached worktree at origin/main, PYTHONDONTWRITEBYTECODE=1

## F1 — the guard's population and its two false positives

|  | a4caccefe | ae78abb28 |
|---|---|---|
| files parsed | 1280 | **1309** |
| absence verdicts | 31 | **31** |
| naming a locus | 29 | **29** |
| FAIL | 2 | **2** |
| the two loci | `_pad_ring.py`:778, `openroad.py`:740 | `_pad_ring.py`:**783**, `openroad.py`:740 |

29 more files parsed and the verdict is unchanged. The `_pad_ring.py` line
moved 778 -> 783 because that file changed on main; it is the same refusal.
**The F1 conclusion stands on the live base.**

## F1 attempt 3 — the guarding-condition predicate

|  | a4caccefe | ae78abb28 |
|---|---|---|
| absence verdicts | 25 | **25** |
| names its guard subject | 13 | **13** |
| WOULD BE REFUSED | 11 | **11** |
| no guarding `if` | 1 | **1** |

Identical. The finding that this predicate refuses the exemplar stands.

## The two vacuous F2 candidates

    upstream_reimplementation_pin_check   POPULATION: 0 pin(s)      (was 0)
    upstream_mirror_is_pinned_check       declared mirrors: 0       (was 0)

Still green over nothing. The consolidation verdict — keep the third, drop
these two — stands.

## The blind predicate, still load-bearing

Main's `_pad_ring.py`:495 still consumes the variable through a pattern:

    r"^[^\S\n]*dict\s+set\s+::env\(\s*PAD_FAKE_SITES\s*\)\s+"

    bare quoted literal "PAD_FAKE_SITES" : False   <- what the OLD predicate asks for
    inside SOME string literal            : True    <- what the NEW predicate sees

So the `_mentions` widening is not a fix for a state that has since gone away.
It is still the difference between seeing the implementation and not.

## And what DID change

Only what the previous file already records: `phase3.pad_ring` landed from
someone else (adopted verbatim), and main still carries the six `inert`
identifiers and still lacks `jpadsite/pad-site`.

## Why this file exists at all

Because the previous one ends with "a verification is only as current as its
last re-poll", and a branch that says that while leaving its own figures
unverified against the live base would be doing the thing it named. Every
number quoted in `RESULT.md` now has a measurement against `ae78abb28` behind
it, not only against the base it was born on.
