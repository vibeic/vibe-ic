# The reflog sweep, and the three bugs in it

Removing a `head -12` cap from my own preservation sweep was correct. What I built to act on the
uncapped result had three defects, and two of them reached other people's repositories.

## 1. The sweep took every `.git`, not every vibe-ic checkout

`find /home/reyerchu -name .git` returns **every git repository on the machine**. Of 2747 object
stores it found, **49 were vibe-ic or benchmark-data and 40 were unrelated projects** — cal.com,
documenso, a Papermark fork, ibex, nvm, several benchmark suites.

It pushed `harvest/rescue-reflog-*` refs to **three of them**: `reyerchu/documenso`,
`reyerchu/lex`, `rwanexus/doc`. A fourth push was refused by GitHub's push protection because
cal.com's history contains a Google OAuth Client ID — **a secret-scanning rule caught my scope
error before I did.**

All three refs were checked and removed: `documenso` and `doc` each anchored one commit that was
**already reachable from another branch on that repo**, and `lex`'s anchor was empty. Removing them
restored those repositories exactly as they were. Verified gone.

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
