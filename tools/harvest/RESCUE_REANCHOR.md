# The rescue anchors were deleted from origin, and I found out by accident

## What happened

Sweeping whether the 1439 rows in `verdicts_all.tsv` still point at directories that exist, 14 were
gone. **All 14 were RECOVER rows** — content someone had been told to keep.

Ten were mine, and every one recorded `ON_REMOTE`, *"reachable from
`origin/harvest/rescue-114-localonly-vibe-ic-repo`"*. I verified them against `refs/remotes` and all
ten passed. Then I ran `ls-remote` and it returned **nothing**:

    origin advertises      : 46 heads, 8 of them harvest/*, ZERO harvest/rescue-*
    this clone's cache says: 529 harvest/rescue-* refs

**`refs/remotes` is a cache, not the authority.** I have written that sentence before, in this
directory, about this repository. I still verified against the cache first, because the cache
answered instantly and agreed with me.

Nine of the ten commits were reachable from nothing origin advertised. Their worktrees were deleted
and their anchors were gone. This clone was the only remaining copy.

## Scale

Walking the cached anchors' parents: **3291** rescued commits, of which **2945 were on no origin
ref**. Controlled before acting, because a number that large is exactly when to suspect the
measurement:

    positive control   3 known-on-origin commits found in the reachable set     ok
    negative control   a freshly-made, never-pushed commit correctly absent     ok
    spot checks        3 of the 2945, each with 0 origin refs containing it     ok

## What was done

Re-anchored, all verified from `ls-remote` rather than from push output:

| ref | parents |
|---|---|
| `harvest/rescue-114-deleted-worktrees` | 9 — the deleted worktrees, pushed first |
| `harvest/rescue-reanchor-1` … `-12` | 2945 |
| `harvest/rescue-reanchor-heads` | 5 further worktree heads on no origin ref |

**Re-measured after: of the 2945, 0 remain off origin.**

An anchor's tree is `origin/main`'s, so it introduces no change; it exists only to keep its parents
reachable. Nothing was deleted, here or anywhere.

## The citations were wrong too

541 of 790 rows cited a ref origin no longer had. Re-derived every one:

- **369** now cite the re-anchor that actually contains their commit
- **167** cite `refs/pull/N/head` — those commits were preserved by a **pull-request head**, which
  `ls-remote --heads` does not list. My first pass called 160 of them unpreserved for that reason
  alone, and I nearly anchored commits that were never at risk.
- **30** were citing `harvest/rescue-reanchor-0`, **a ref that was never pushed**: the anchors were
  numbered by a shell loop from 1 while the map was built by parsing `split` suffixes from `00`.
  Two numbering schemes for one set of objects. Fixed by rebuilding the map from
  `git rev-list --parents` on each anchor — **ask the objects, not the filenames**.

**Final sweep: 623 rows cite an origin ref, 0 of them dead.**

## What this cost, and what it is worth

The nine deleted worktrees would have been unrecoverable. The verdict rows said `RECOVER` and
`ON_REMOTE`, both of which were true when written and false by the time anyone could act. Preserved
work is not preserved because you preserved it once; a ref someone else can delete is not a
guarantee, and the record of it is not the thing itself.

The only reason this was recoverable at all is that the objects were still in a local clone that had
not been garbage-collected. That is luck, and it ran out for nothing this time.
