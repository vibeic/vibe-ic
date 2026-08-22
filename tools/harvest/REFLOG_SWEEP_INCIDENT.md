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


## Redone correctly, scoped to vibe-ic

| host | vibe-ic object stores | with an orphaned reflog commit |
|---|---|---|
| .105 | 38 | 0 |
| .102 | 75 | 1 |

`.105` reports zero because the 11 real orphans it held are already anchored on origin — the sweep
is idempotent, and a second run finding nothing is the correct answer, not a broken one.

`.102`'s single orphan, `56b89246120 fix(rtl-gen): OTP_MEM sent ASIC synthesis down the Quartus
path`, could not push from its own repo: the **pre-push hook aborted** because it could not run
`git rev-parse --show-toplevel` from a bare `.git` path, and it refused rather than skipping the
gates it could not execute. Fetched over ssh and pushed from a clone whose hook can run — the same
route used for hook-blocked pushes throughout, never `--no-verify`.

**Total preserved by this sweep: 13 commits that exist nowhere else on origin.**


## All seven hosts, scoped correctly

| host | vibe-ic object stores | stores with an orphan | orphan commits |
|---|---|---|---|
| .105 | 38 | 0 (already anchored — the sweep is idempotent) | — |
| .102 | 75 | 1 | 1 |
| .108 | 4 | 1 | 6 |
| .112 | 17 | 3 | 8 |
| .114 | 20 | 4 | 12 |
| .120 | 19 | 3 | 17 |
| .121 | 28 | 4 | 6 |

Four stores' pushes were refused by their own repo's pre-push hook or lacked a git identity;
each was anchored in place with the identity supplied via **environment** rather than written into a
config I only came to read, then pushed from its own host.

**Push targets were grouped by origin URL.** Two of those stores are `benchmark-data` clones, and
their commits went to `vibeic/benchmark-data` — pushing them to vibe-ic would have repeated the
scope error this document exists to record.

## And benchmark-data is now clean

It had accumulated 9 `harvest/*` refs from the buggy run. Five were parentless. The other four held
commits that were **all already reachable from benchmark-data's own branches** — so every one was
redundant. All nine removed; that repository carries **0** harvest refs.
