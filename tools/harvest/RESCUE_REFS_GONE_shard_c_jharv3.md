# Every rescue ref shard C names is gone from origin

`jharv3`, 2026-08-22, third session. Re-audit of the shipped 110 rows against
`origin/main` `a4caccefeab577a5337f1854c9c857e4d7a2bd42`.

## The 110 verdicts stand. Nothing here changes a verdict.

They were re-derived from scratch rather than re-read. For every row the judged
HEAD was compared to main by CONTENT: `owned` = the files the branch changed
against its own merge-base with main, then each owned file's blob at HEAD against
main's blob at the same path. Ancestry was not used to decide anything.

| shipped | independent derivation | rows |
|---|---|---:|
| LANDED | every owned file matches main | 18 |
| ABANDON | content not on main (ABANDON is not a landing claim) | 2 |
| RECOVER | at least one owned file differs from main | 87 |
| RECOVER | no owned committed content; verdict rests on uncommitted/untracked work | 3 |

**18 of 18 LANDED confirmed. Zero false LANDED.** The three RECOVER rows with no
owned committed content (`_v1123`, `_a1456`, `wt_jwire2`) are correct for the
reason their evidence already gives: uncommitted edits, or a HEAD that moved.

Both ABANDONs re-checked, because ABANDON authorises deletion of content that is
**not** on main:

- `wt-j63x8c` — HEAD `3ab7fc723e49` is contained by `origin/jmatrix/63x8-main-reds`,
  confirmed by `ls-remote` against origin, not from a tracking ref. Holds.
- `_v1126` — HEAD tree `f5f659f2a22a236f` is byte-identical to
  `/home/reyerchu/_i_solo_1126`'s tree. That path really does carry RECOVER in
  `verdicts_shard_c.tsv`, so "which is kept" is true here. Holds — **but see below.**

## What is new, and it is not small

**All 24 `harvest/rescue-*` refs cited in `verdicts_shard_c.tsv` have been deleted
from origin.** Origin currently has 86 heads and **zero** `harvest/rescue-*`.

Every "`Preserved as harvest/rescue-…`" and every "`recover with git fetch origin
harvest/rescue-…`" in the shipped evidence is now an instruction that fails. The
rows were true when written; the refs did not survive the night.

This clone still holds **530 stale `refs/remotes/origin/harvest/rescue-*` tracking
refs, and all 530 objects are present.** `refs/remotes` is a cache of origin and
outlives what origin deleted — which is exactly why those rescued commits are still
readable here and nowhere else that has been found.

> **Do not `git fetch --prune`, `git remote prune`, or `git gc` `/home/reyerchu/vibe-ic`
> on .108.** A dry-run prune deletes 530 refs. Those pointers are what keep the
> rescued commits reachable; dropping them exposes the objects to collection.
> This clone is currently the only consolidated copy of that rescued work.

## Consequence for the shard, measured

`survivability_now_shard_c_jharv3.tsv` — one row per worktree: judged HEAD, whether
that HEAD is reachable from any **live** origin ref today, the rescue refs its
evidence names, and the independent content derivation.

| verdict | HEAD on live origin | HEAD on no live origin |
|---|---:|---:|
| RECOVER | 31 | **59** |
| LANDED | 16 | 2 |
| ABANDON | 1 | 1 |

- **The 18 LANDED are unaffected.** LANDED means the content is on main; whether the
  commit is reachable does not change what deletion costs, which is nothing.
- **`_v1126` (ABANDON) is unaffected as a verdict but its stated recovery route is
  dead.** `harvest/rescue-8HD-d-v1126` is gone and the HEAD is on no live origin ref.
  It is still safe to drop *only* because its tree is byte-identical to
  `_i_solo_1126`, which is RECOVER. **That row is now load-bearing: if `_i_solo_1126`
  is ever dropped, this content is destroyed.** `_i_solo_1126`'s own HEAD is also on
  no live origin ref.
- **59 RECOVER rows are single-copy.** Their work exists on one live host's disk and
  in this clone's object store, and on no origin ref. RECOVER was already the right
  call; this says it is more urgent than the evidence implied, not less.

## What this session could preserve, and what it could NOT

The 529 rescued commits were consolidated into **one** anchor commit rather than
re-pushing 530 branches. The anchor exists **locally in the .108 clone only**:

```
ea622b9882936a3a275bfd0eb96c8e4d63e29ae7
```

Its parents are all 529 rescued commits, so one ref would preserve the whole set.
The mapping from original ref name to sha is
`rescue_consolidated_manifest_jharv3.tsv`, which is committed here and is complete
whether or not the anchor is ever pushed.

> **The push of that anchor to origin was DENIED by this session's permission
> classifier. It is NOT on origin.** Preservation of those 529 commits therefore
> still rests entirely on the `/home/reyerchu/vibe-ic` clone on .108 and on its
> stale tracking refs. This is an open exposure, named rather than papered over.
>
> To close it, someone with push rights should run, from .108:
>
> ```bash
> git push origin ea622b9882936a3a275bfd0eb96c8e4d63e29ae7:refs/heads/harvest/rescue-consolidated-8hd6-jharv3
> ```
>
> The anchor commit is already built and needs no recomputation. If it has been
> garbage-collected by then, rebuild it from the manifest.

## How to re-run this

```bash
git ls-remote --heads origin 'harvest/rescue-*'    # expect zero
git fetch --prune --dry-run origin | grep -c deleted   # expect 530 — do NOT run without --dry-run
```
