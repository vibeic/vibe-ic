# Shard C, seventh session: the deletion-bound rows re-measured on live hosts, and one flip

**One-line result: 36 deletion-bound rows re-checked, 35 unchanged, 1 flips ABANDON -> RECOVER
because the directory moved off the head it was judged at and now holds 7 commits on no origin ref.**

Shard C was complete and correct when it was written. It is a decision about *directories on
live machines*, and one of those directories changed under it. That is the failure mode every row
warns about in its own text ("re-measure before acting; these hosts are live"), and this session is
that re-measurement for the 36 rows where being wrong is unrecoverable.

## What was checked, and what was not

Deletion-bound rows are LANDED and ABANDON: those are the verdicts that authorise deleting a
directory. RECOVER rows were not re-probed for drift -- a RECOVER that drifts still says "keep",
so drift there cannot destroy anything.

| check | result |
|---|---|
| `origin/main` still the sha all 110 rows were judged against | yes, `a4caccefeab577a5337f1854c9c857e4d7a2bd42` -- no row is stale |
| shard path set == verdict path set | 110 == 110, no gaps, no extras |
| file shape | 111 lines, every line exactly 3 tab-separated fields |
| verdict vocabulary | RECOVER / LANDED / ABANDON only, all inside the contract |
| 103 distinct judged HEADs contained by a live origin ref | 103/103, ancestors of `harvest/worktree-triage-jharvest` @ `6ff4a5a20` (tip read by `ls-remote`) |
| 36 deletion-bound directories: exist, HEAD unmoved, clean under `-uall` | 35 clean and unmoved, **1 moved** |

The 26 rows on .112 and .121 were probed through the `.102` nested-ssh hop with the far hosts kept
strictly read-only: the probe was piped in on stdin, wrote nothing, fetched nothing, and touched no
ref. Raw per-row measurement: `raw_drift_deletionbound_s7_jharv3.tsv`.

## The one that moved: `/home/reyerchu/wt-j63x8c`

Judged at `3ab7fc723e49` and marked ABANDON as a byte-identical duplicate of
`jf-63x8-work/base-mml`, with the old content preserved on the deliverable branch. That reasoning
was sound and is untouched. The directory is simply no longer at that commit:

- HEAD today is `bc60e88484c16485fee083bc690f6573f9ca36ab` on `jmatrix/63x8-main-reds`, and
  `3ab7fc723e49` is **not an ancestor of it** -- rebased onto current main, 7 new commits, all
  stamped 2026-08-22 15:53 +0800.
- Those 7 commits are on **no live origin ref**. Tested one at a time against all 1536
  locally-resolvable shas of the 1571 origin advertises (146 heads plus `refs/pull/*`), read with
  `git ls-remote` -- not from `refs/remotes`, which is a cache that outlives deleted branches.
- Judged by content, not ancestry: 9 files differ from main's tip **and** main's history has never
  held those bytes at those paths (`landed_by_history.py`, self-test green: 6504 tracked files,
  `differs_from_tip=9`, `held_at_path=0`, `novel_bytes=9`).

So an ABANDON was standing over a directory whose deletion would have destroyed seven commits of
single-copy work. **Nothing was deleted and nothing was at risk from this sweep** -- the verdict is
a recommendation a later job executes -- but the recommendation was wrong for what is on disk.

**Preserved before the row was rewritten**, because the row is worth less than the content:
pushed as `harvest/rescue-108-wt-j63x8c-drifted`, read back with `ls-remote`
(advertises `bc60e88484c...`), all 7 commits verified contained by walking that advertised tip.

What the work is: `matrix_mutation_ledger.py` lowers `LEDGER_AS_MEASURED` from `(69,8,522)` to
`(69,8,516)` and **names each of the six dimension-3 cells** that moved `ENFORCED -> NOT_MEASURED`
under the owner's 2026-08-21 ruling, instead of leaving a lowered count unexplained; plus a
671-line `RESULT.md` absent from main entirely, and 326 added test lines across the
`matrix_63x8` / `matrix_d3` suites. 9 files, 1074 insertions, 57 deletions.

## Shard C now

**110 rows: 75 RECOVER, 34 LANDED, 1 ABANDON.** One verdict changed; the other 109 were re-tested
and stand.

## What this does not claim

- 35 of the 1571 refs origin advertises could not be resolved in this clone, so containment was
  tested against 1536 of them. A commit reachable *only* from one of those 35 would be reported as
  orphaned here. That direction is safe -- it over-preserves -- but it is stated rather than hidden.
- The 74 RECOVER rows were checked for recovery-instruction resolution and citation, not re-probed
  for on-disk drift. A drifted RECOVER still says keep.
- This is a decision, not an action. Nothing on any host was deleted, moved, or fetched.
