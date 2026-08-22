# What +214 commits of main did to 1103 RECOVER rows

`origin/main` moved from `81cd5321b08` (the main my last verification used) to `a4caccefeab`, and
`81cd5321b08` is an ancestor of it — so the drift direction argument holds: staleness can turn
RECOVER into LANDED, never the reverse.

Re-verified every RECOVER row's named-file claim against live main:

| | |
|---|---|
| RECOVER rows | 1103 |
| claim still holds | **1101** |
| genuinely landed since | **2** |
| UNDETERMINED by design | 4 |
| unrecognised evidence | **0** |

## Three regexes, three undercounts, one lesson

My first pass reported 237 rows with "no parseable sha claim", then 90 "unrecognised". Both were my
parser, not the evidence — the third time this session that a narrow reader of my own output
produced a confident wrong number about it.

The evidence uses several phrasings: `X here, Y on main`, `X here, (origin/main has no file at
this path) on main`, `N of M files it owns hold bytes main does not have`, plus the pruned-checkout
form. Enumerating phrasings loses every time. **The generic reader extracts only `sha256(P) = H`
and then looks up what main has at P live** — the content question does not depend on the sentence.
Unrecognised went 237 → 90 → 0.

## "The named file landed" is not "the worktree landed"

Six rows' named exemplar file now matches main. That is not six landed worktrees — a row citing one
exemplar may own dozens more. Measured individually with reverse-apply against live main:

    _jd3                  ALLOW   contained          -> genuinely landed
    /var/tmp/jmg2/vibe-ic ALLOW   contained          -> genuinely landed
    _jland67              REFUSE  6 files uncontained
    _meas_head            REFUSE  9 files uncontained
    _meas_head_hyg        REFUSE  9 files uncontained
    _meas_head_tests      REFUSE  9 files uncontained

Four of the six still hold. Their exemplar landed while the rest of their work did not.

Four of those clones were still at `81cd5321b08` and had to be fetched **forward** first — a stale
`origin/main` manufactures a false LANDED, and the guard refuses rather than measuring against it.

## Why the two rows are not flipped here

Both are safe to delete on today's measurement. I am recording them rather than re-verdicting them:
a RECOVER that has landed is **over-conservative — wasteful, not dangerous** — while flipping a row
to a deletion-authorising verdict on the strength of one measurement is the action the brief reserves
for the owner. The rows remain correct as of the main they were judged against; this file states
what changed, against which main, so the decision is available without my taking it.


## Re-measured at main `ae78abb2856` — 673 commits further on

| | first check (`a4caccefeab`) | now (`ae78abb2856`) |
|---|---|---|
| RECOVER rows | 1103 | 1103 |
| claim still holds | 1101 | **1097** |
| has since landed | 2 | **2 — the same two** |
| resolved / by-design | — | 4 |

The two are still `_jd3` and `/var/tmp/jmg2/vibe-ic`, already recorded above. **No new drift across
673 additional commits.** The four-row difference in "still holds" is the resolved-UNDETERMINED rows
being counted in their own bucket now, not verdicts changing.

Every main any row was judged against — `a00f53f2094` (+917), `81cd5321b08` (+887),
`a4caccefeab` (+673) — is still an ancestor of live main, so the direction argument holds: staleness
can turn RECOVER into LANDED and never the reverse.

Three of the twelve corrections read UNMEASURED on this pass, all of them *"clone origin/main is
stale"*. Fetching those clones **forward** restored 12/12 SUPPORTED. That is the guard refusing to
measure against a moved reference rather than reporting a false LANDED — the failure it exists for,
happening routinely rather than exceptionally.
