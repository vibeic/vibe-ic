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
