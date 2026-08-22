# The reflog sweep, and the three bugs in it

Removing a `head -12` cap from my own preservation sweep was correct. What I built to act on the
uncapped result had three defects, and two of them reached other people's repositories.

## 1. The sweep took every `.git`, not every vibe-ic checkout

`find /home/reyerchu -name .git` returns **every git repository on the machine**. Of 2747 object
stores it found, **49 were vibe-ic or benchmark-data and 40 were unrelated projects** — cal.com,
documenso, a Papermark fork, ibex, nvm, several benchmark suites.

It pushed `harvest/rescue-reflog-*` refs to **15 repositories outside this brief**, across both
hosts — the first check found 3 on .105 and stopped there; sweeping .102's store list too found 12
more. A further push was refused by GitHub's push protection because cal.com's history contains a
Google OAuth Client ID — **a secret-scanning rule caught my scope error before I did.**

| repository | ref | held |
|---|---|---|
| `reyerchu/documenso` | `rescue-reflog-105-14` | 1 commit, already on another branch there |
| `rwanexus/doc` | `rescue-reflog-105-13` | 1 commit, already on another branch there |
| `reyerchu/lex` | `rescue-reflog-105-27` | nothing (parentless) |
| `reyerchu/EMJ` | `rescue-reflog-102-14` | 1 commit, already on that repo |
| `reyerchu/AI_IC_design`, `hackrail`, `hermes-agent`, `my_hermes` | `102-7/17/18/19` | nothing |
| `vibeic/ALIGN-pdk-sky130`, `awesome-open-ic`, `benchmark-external`, `IP`, `open_pdks`, `yosys` | various | nothing |
| `vibeic/vibeic-eda` | `102-77`, `102-95` | nothing |

**All 16 refs removed, every one verified first to hold nothing that repository did not already
have.** A ref whose parents were reachable only from it would have been kept — none was. Re-swept
all 40 non-vibe-ic origins afterwards: **0 stray refs remain.**

The first blast-radius check was itself too narrow: it used .105's store list only, because that is
the host I was standing on.

## 2. Orphan detection read local refs and called the result "on no ref"

`git rev-list --all` walks **local** refs. A commit sitting on a remote branch the clone never
fetched reads as unreferenced. That is why `documenso`'s commit looked orphaned when it was on a
branch all along — the same `refs/remotes`-is-a-cache mistake as this morning, in the opposite
direction. Earlier it over-claimed preservation; here it invented orphans that were never orphans.

## 3. An empty result counted as one

    orph=""      printf '%s\n' "$orph" | grep -c ''   ->  1
                 printf '%s\n' "$orph" | grep -c .    ->  0

`grep -c ''` counts the empty line. Stores with **zero** orphans passed a `-gt 0` test, built an
empty parent array, and produced a **parentless anchor claiming "1 commits on no ref"**. 56 such
refs went up on origin before this was noticed. All 56 removed.

## What actually survives

**5 anchors, 12 commits, 11 of which exist nowhere else on origin** — eight `probe …` commits, a
`fix(area gate)` and two merges of `fix/jland67-hygiene-subset-honoured`. Folded into this branch.

## The pattern

Every one of the three was a **count or a set that answered a narrower question than the one asked**
— every `.git` for every vibe-ic checkout, local refs for all refs, an empty line for a result. The
same shape as `refs/remotes` for `ls-remote`, existence for containment, a sample for the whole, and
a depth limit for the filesystem. It is the most reliable way I have found to be confidently wrong.
