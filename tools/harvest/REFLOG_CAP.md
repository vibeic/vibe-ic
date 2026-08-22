# My own sweep had a cap, and it hid commits on no ref

`prior_sweep.sh` walked each repo's reflog with `head -12`; `landed_form.sh` used `head -8`. A
reflog is **not ordered by importance** — it is ordered by recency — so a cap silently drops
whatever is older, which is exactly where an abandoned experiment sits.

## Measured 2026-08-22

| | |
|---|---|
| repos on one host with a reflog | 67 |
| with **more than 12** distinct entries | 7 |
| commits sitting beyond the cap | 555 |
| of a 12-per-repo sample, on **no origin ref** | 44 |

Uncapped, across two hosts: **7942 distinct reflog commits, 6138 reachable from nothing origin
advertises.**

## Why they could not simply be fetched

The first rescue attempt fetched from each holding repo with `+refs/*:refs/remotes/_gather/*` and
moved **32 of 6328**. That is structural, not a bug: **a reflog entry is on no ref, so a refspec
fetch can never name it.** It has to be anchored where it lives and pushed from there.

Also, 2504 "source repos" collapse under `--git-common-dir` — worktrees share their parent's object
store, so most of that list was the same store counted many times. Deduping by common-dir is what
makes the sweep tractable.

## Status

`rescue-reflog-<host>-<n>` anchors are being pushed per object store, each carrying that store's
orphaned reflog commits as parents with `origin/main`'s tree, so they introduce no change. The
sweep runs across 2744 stores on .105 and a similar count on .102 and was **still in progress when
this was written** — the count of refs on origin at that moment is recorded in the commit message,
not asserted as final.

**The caps are removed.** That is the part that does not depend on the sweep finishing.
