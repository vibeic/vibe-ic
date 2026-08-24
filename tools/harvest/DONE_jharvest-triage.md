# `jharvest-triage` — one branch, what is on it, and what I consolidated

**My one branch is `next/jharvest-triage`.** Every commit I make from now goes on it
and I create no others.

## Branches I own, and what happened to each

| ref | disposition |
|---|---|
| `next/jharvest-triage` | **the one branch.** All six of my working commits, unchanged. |
| `next/batch72-freeze-membership-check` | **consolidated into the above — same six commits, identical tip.** Superseded; safe for the central cleanup to drop. Nothing on it is unique. |
| `harvest/worktree-triage-jharvest` | **frozen input to batch 72. Not consolidated, not deleted, not pushed to.** It carries `verdicts_shard_a.tsv`, which the acceptance ledger reads. It must stay. |

Consolidation was a ref rename in effect: `next/jharvest-triage` points at
`df59511eae`, the exact tip the old branch had, so no commit was copied, rewritten
or lost. Two refs exist for one line of work only until the central cleanup runs.

I emitted **two** refs across this whole job, not one per finding. The
`harvest/rescue-120-shard-a-*` branches carry my shard's name but are not mine —
their tips are another agent's commits, checked against the fifteen SHAs I pushed.

## What the branch carries

* `CORRECTION_shard_a_false_landed.tsv` — 4 rows LANDED -> RECOVER. They said "safe
  to delete" about worktrees holding uncommitted bytes on no commit.
* `CORRECTION_unreachable_resolved_false_landed.tsv` — 1 more, `.112 _a1456`.
* `rescue/rescue-2026-08-22.bundle` + `MANIFEST.sha1` + `README.md` — the 164 files
  those five worktrees hold, 10.8 MB, bundled to 3.0 MB. Verified before being
  relied on: bundle records a complete history, 164/164 matched by SHA against the
  live worktrees, 0 missing.
* `2026-08-22-shard-a-false-landed-root-cause.md` — the rule-ordering inversion that
  caused all five, and the sweep of every LANDED row it could have touched.
* `2026-08-22-shards-b-c-tip-equal.md` + `.tsv` — 11 rows in B and C now equal to
  main's tip, 5 of which must stay RECOVER anyway.
* `2026-08-22-batch72-freeze-membership-jharvest.md` — four tests saying the batch
  does not contain my branch, recorded while complying with the freeze regardless.
* `judge_shard.sh` — the fixed tool.

## Shard A, final

114 rows, and with the overlay applied: **89 RECOVER / 25 LANDED**, 0 ABANDON,
0 UNREACHABLE. Judged by content against main, never by ancestry.
