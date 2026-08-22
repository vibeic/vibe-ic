# vibe-ic worktree harvest — what to read, in order

Three agents produced this directory: `jharvest-triage` (shard A), `jharv2` (shard B and the
extras), `jharv3` (shard C). A reader currently faces 26 TSVs, 39 markdown files and 98 scripts
with no entry point, and the oldest handoff predates the verdict files entirely. This is the index.

**Nothing here has been deleted. These files are decisions; acting on them is a separate step.**

## 1. To act: `verdicts_all.tsv`

| file | rows | what it is |
|---|---|---|
| `verdicts_all.tsv` | **1439** | every decided worktree. Union of the two files below, each row carrying a `source` column. Regenerate with `bin_jharv2/build_verdicts_all.py`. |
| `verdicts_joined.tsv` | 355 | the roster the three shards were split from. Written by more than one agent. |
| `verdicts_extras_joined.tsv` | 1084 | worktrees found on 8HD-9 and 8HD-7 that the roster never listed. Derived from the two `verdicts_extra_*` files; `bin_jharv2/derived_freshness_check.py` fails if it drifts from them. |

Verdicts in `verdicts_all.tsv`: RECOVER 1226, LANDED 184, ABANDON 29.

`RECOVER` = keep. `LANDED` and `ABANDON` **authorise deletion** — 230 rows do.

## 2. Before deleting anything: `bin_jharv2/predelete_guard.sh`

Re-measures a worktree's content on the machine holding it and **fails closed**. It refuses when the
path is absent, has no HEAD, has no merge-base, or sits in a clone whose `origin/main` is not the
ref you are judging against — because an unmeasured worktree and a clean one are byte-identical in
any output that does not distinguish them.

Committed content is judged by **reverse-applying the branch's own diff onto main**, not by comparing
blobs. This repo's landed heads are ancestors, so a worktree whose change is already in main still
differs from it on every file main has touched since. A blob comparison refused all 29 ABANDON rows,
every one wrongly.

## 3. Known-wrong rows: `verdicts_joined_corrections.tsv`

| file | rows | what it is |
|---|---|---|
| `verdicts_joined_corrections.tsv` | 12 | deletion-bound rows contradicted by measurement, keyed by **(target_file, path)** because the same wrong row appears in more than one file. Verify with `bin_jharv2/corrections_check.sh`. |
| `corrections_withdrawn.tsv` | 4 | corrections that no longer hold — their content landed as main advanced. Withdrawn, not deleted. |
| `RECOVER_DRIFT.tsv` | 2 | RECOVER rows whose content has since landed. Over-conservative, not dangerous. |

All twelve carry evidence of the form *"all **0** file(s) matched main"* — a universal over
an empty set. **Every such row still in `verdicts_joined.tsv` is deletion-bound — 9 of 9**, and it was 20 of 20
when first audited, before jharv3 corrected eleven of them. That is causal rather than coincidental:
"every file matched" is exactly what produces LANDED, so a row whose file enumeration returned
nothing lands in the delete bucket by construction.

## 4. Per-shard sources

| file | rows | agent |
|---|---|---|
| `verdicts_shard_a.tsv` | 114 | jharvest-triage |
| `verdicts_shard_b.tsv` | 131 | jharv2 — the shard B contract |
| `verdicts_shard_c.tsv` | 110 | jharv3 |
| `verdicts_shard_c_80_recovered.tsv` | 80 | jharv2 — shard C rows that were UNREACHABLE from jharv3's host |
| `verdicts_extra_8hd9.tsv` | 451 | jharv2 |
| `verdicts_extra_8hd7.tsv` | 633 | jharv2 |
| `verdicts_unreachable_resolved.tsv` | 80 | earlier resolution pass |

## 5. Host 108 — 89 more decided worktrees, in a different vocabulary

`shard_c/108_verdicts.tsv` (jharv3, copied byte-for-byte from `harvest/shard-c-108-jharv3`) holds
**89 decided worktrees on host 108**, and **56 of those paths appear in no other verdict file here**.
They were invisible to anything reading the consumable.

They are deliberately **not** merged into `verdicts_all.tsv`: that file says RECOVER / LANDED /
ABANDON, this one says **KEEP (59) / DROP (30)**. `KEEP` maps to `RECOVER`; **`DROP` does not map** —
it is deletion-bound, but whether a row means "already on main" or "worthless" is a distinction the
file does not draw, and guessing would put a verdict in another agent's mouth in the one direction
that is unrecoverable. See `shard_c/108_PROVENANCE.md`.

**30 of them authorise deletion; all 30 have now been through `predelete_guard.sh` and measured SAFE** — see `shard_c/108_DROP_guard_results.tsv`.

## 6. Every deletion-bound row now has a recorded guard result

**230 of 230** — 229 measured, 1 honestly UNVERIFIABLE (its directory is gone from all seven hosts). An executor selecting `LANDED`/`ABANDON` from `verdicts_all.tsv` can look up each one:

| file | rows | covers |
|---|---|---|
| `JOINED_DELETION_GUARD_RESULTS.tsv` | 49 | the roster's deletion-bound rows |
| `EXTRAS_DELETION_GUARD_RESULTS.tsv` | 178 | the extras' — all SAFE |
| `shard_c/108_DROP_guard_results.tsv` | 30 | host 108's DROP rows |

A peer later re-verdicted 12 rows RECOVER → LANDED on `.120`, and `verdicts_all is reproducible`
caught it: deletion-bound went 213 → 225. All 12 verified by the method their evidence names —
every file differing from main's **tip** has its exact blob in main's **history** at the same path.

The extras needed three methods. 37 answered directly; 81 first refused as *stale clone* and were
fetched **forward** before they could be judged at all; and 43 are pruned checkouts with no git dir,
compared file-by-file to the main commit their manifest identifies, then **every differing file
checked against main's history** — 39 files differed, all 39 found on main.

That last step is why they read SAFE rather than alarming. Compared to *current* main a pruned
checkout looks catastrophic: ~446 files differ because main moved, and ~17,192 read absent because
`benchmark-data/` was split out of this repo entirely. Neither is unlanded work.

## 7. What this does NOT cover

`verdicts_all.tsv` is 1439 decided worktrees, not every vibe-ic checkout on the fleet. A full-depth
census of all seven reachable hosts found **at least 14,196 checkouts, of which 1,453 carry a verdict — about 10%**. One host's figure is a depth-4 lower bound; see `SCOPE.md`. See
`SCOPE.md`. The job was defined by a 477-worktree roster; the other 1084 rows are beyond it. An
unjudged checkout is untouched — a wrong verdict is what deletes.

## 8. What went wrong, written down

| document | what it records |
|---|---|
| `RESCUE_REANCHOR.md` | every `harvest/rescue-*` ref was **deleted from origin** mid-session; 2945 commits re-anchored, nine worktrees' commits were briefly the only copy in existence |
| `REFLOG_SWEEP_INCIDENT.md` | **I pushed refs to 15 repositories outside this brief.** All 16 removed, each verified first to hold nothing that repo already had. A GitHub secret-scanning rule caught the scope error before I did. Also the three bugs behind it. |
| `SCOPE.md` | 1439 verdicts is not ~14,196 checkouts — and the untracked-file sweep, the one category no rescue anchor can reach |
| `RECOVER_DRIFT.md` | what +214 commits of main did to 1103 RECOVER rows (answer: 2) |

These are in the index deliberately. A reader deciding whether to trust the verdicts should be able
to find the places the method failed without going looking for them.

## 9. Still open, and not mine to close

- **All 49 deletion-bound rows in `verdicts_joined.tsv` have now been measured** —
  `JOINED_DELETION_GUARD_RESULTS.tsv`: **41 SAFE, 3 safe-by-twin, 5 HOLD CONTENT** against live main.

  Only **five** hold content that is on no commit in their own worktree, and all five are
  uncommitted —
  `_agentjob_i1015/wt` (98 files), `_agent_scratch_whatif/wt_C` (37), `_wt_1486` (8, incl. the
  canonical `phase1_phase2_phase3.yaml`), `_wt_1236` (5), `_wt_1390pg` (1). All five are already in
  the corrections file. **Their 149 uncommitted blobs were separately checked and every one is
  reachable from an origin ref**, so deleting those directories is recoverable — uncommitted
  content is held by no commit in its own worktree, which is exactly why that had to be asked as a
  second question rather than inferred from the verdict.

  A first pass reported **eleven**. Three of those — including `vibe-ic-wt-jxlayer` and its alarming
  "678 files not contained" — were a false alarm: their change is CONTAINED against
  `a00f53f2094`, the main they were judged against, and main has since modified those files
  further, so the reverse hunk no longer applies. **Reverse-apply is the right test only against the
  right reference.** Three more are genuinely uncontained but duplicate-justified, with the twin
  verified identical and kept.
- **49 deletion-bound rows in `verdicts_joined.tsv` carry no preservation citation** — nor do the
  12 in `verdicts_shard_a.tsv`, 20 in `verdicts_shard_c.tsv` or 12 in
  `verdicts_unreachable_resolved.tsv`. Their verdicts may be perfectly correct; the point is that
  deleting on them rests on no statement that the content survives the directory. Only my rows make
  that claim in a checkable form, and on 2026-08-22 every ref mine cited had been deleted from
  origin — see `RESCUE_REANCHOR.md`. Run `bin_jharv2/predelete_guard.sh` on any of them first.
- The 12 corrections are **not applied**. `verdicts_joined.tsv`, `verdicts_shard_a.tsv` and
  `verdicts_unreachable_resolved.tsv` still carry the rows they contradict.
- `bin_jharv2/extras_coverage.py` stays RED against `verdicts_joined.tsv`, correctly: those 1083
  rows are genuinely not in it. Pointing that gate at `verdicts_all.tsv` would be circular, since
  the same generator writes both.
- **A branch was force-pushed today and orphaned 11 commits.** `fix/jwire2-hygiene-wiring` moved
  from `88b9399076a` to `4b1285a1865` — rewritten, not advanced — leaving the old head on no origin
  ref and no local ref, alive only in `.121`'s object store. My own survivability row still said
  *ON_REMOTE via origin/fix/jwire2-hygiene-wiring*, which was true when written. Rescued to
  `harvest/rescue-121-jwire2-forcepush-orphan` and folded in. **The record that vouches for a commit
  outlives the ref it names**, so `bin_jharv2/live_ref_citation_check.py` is what keeps that honest.
- Everything above was measured against `origin/main` **a4caccefeab**. Main fast-forwards, so staleness
  can turn RECOVER into LANDED but never the reverse; a force-push would invalidate that and the
  rows would need re-judging, not re-labelling.

## 10. Verifying all of it

    bash tools/harvest/bin_jharv2/check_all.sh

Twelve gates. Seven need nothing but the checkout; `live_ref_citation_check.py` needs the network,
because a survivability citation can only be verified against `git ls-remote` — the authority — and
offline it REFUSES rather than passing. On 2026-08-22 every `harvest/rescue-*` ref had been deleted
from origin while this clone's `refs/remotes` still listed 529 of them; see `RESCUE_REANCHOR.md`. One of them, `branch_preserves_rescued_check.py`, asserts that the 2950 commits in
`rescued_commits.txt` AND the three whole trees in `preserved_tips.tsv` — 4929 files of
pruned-checkout and stash content that is on no commit anywhere else — are reachable from this
branch. They are reachable because the branch carries
the rescue anchors as extra parents: a rebase, squash or amend that dropped them would un-preserve
all 2950 while every file in the tree stayed byte-identical, so no diff would show it.

Each declares the exit code it
is **expected** to produce — `extras_coverage.py` is expected to FAIL, because those 1083 rows really
are absent from `verdicts_joined.tsv`. A stub that makes it pass is reported as a failure, so a
known-open item cannot be quietly closed. The runner asserts its own denominator: fewer gates run
than declared is itself a failure, because a loop that stops early reports no failures.

Counts in this file are checked by `bin_jharv2/readme_numbers_check.py`, which is one of the seven.

### If a ref is lost: recovering, and the one way to get it wrong

Three refs carry this — the branch, `harvest/worktree-triage-jharvest-mirror`, and the tag
`harvest-jharv2-final`. **Drilled, not assumed:**

    git clone --branch harvest/worktree-triage-jharvest-mirror <url>     # 12/12 gates, 3039/3039 commits

**Recover with a FULL clone or fetch. Never `--depth 1`.** A shallow fetch of the tag produces a
directory that looks entirely correct — README, all verdict files, 131 rows in
`verdicts_shard_b.tsv` — and carries **0 of the 3039 preserved commits**. The files are the index;
the commits are the content, and shallow keeps the first and drops the second.

    shallow: 1 commit reachable,      rescued 0/3039     -> `branch preserves the rescued set` FAILS
    full:    14365 commits reachable, rescued 3039/3039  -> 12/12 green

That gate is what distinguishes the two. Someone recovering in a hurry reaches for `--depth 1`
precisely because it is faster, and every file they look at afterwards would tell them it worked.
