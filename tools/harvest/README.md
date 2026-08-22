# vibe-ic worktree harvest — what to read, in order

Three agents produced this directory: `jharvest-triage` (shard A), `jharv2` (shard B and the
extras), `jharv3` (shard C). A reader currently faces 26 TSVs, 28 markdown files and 72 scripts
with no entry point, and the oldest handoff predates the verdict files entirely. This is the index.

**Nothing here has been deleted. These files are decisions; acting on them is a separate step.**

## 1. To act: `verdicts_all.tsv`

| file | rows | what it is |
|---|---|---|
| `verdicts_all.tsv` | **1439** | every decided worktree. Union of the two files below, each row carrying a `source` column. Regenerate with `bin_jharv2/build_verdicts_all.py`. |
| `verdicts_joined.tsv` | 355 | the roster the three shards were split from. Written by more than one agent. |
| `verdicts_extras_joined.tsv` | 1084 | worktrees found on 8HD-9 and 8HD-7 that the roster never listed. Derived from the two `verdicts_extra_*` files; `bin_jharv2/derived_freshness_check.py` fails if it drifts from them. |

Verdicts in `verdicts_all.tsv`: RECOVER 1226, LANDED 184, ABANDON 29.

`RECOVER` = keep. `LANDED` and `ABANDON` **authorise deletion** — 213 rows do.

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

## 4b. Host 108 — 89 more decided worktrees, in a different vocabulary

`shard_c/108_verdicts.tsv` (jharv3, copied byte-for-byte from `harvest/shard-c-108-jharv3`) holds
**89 decided worktrees on host 108**, and **56 of those paths appear in no other verdict file here**.
They were invisible to anything reading the consumable.

They are deliberately **not** merged into `verdicts_all.tsv`: that file says RECOVER / LANDED /
ABANDON, this one says **KEEP (59) / DROP (30)**. `KEEP` maps to `RECOVER`; **`DROP` does not map** —
it is deletion-bound, but whether a row means "already on main" or "worthless" is a distinction the
file does not draw, and guessing would put a verdict in another agent's mouth in the one direction
that is unrecoverable. See `shard_c/108_PROVENANCE.md`.

**30 of them authorise deletion and none has been through `predelete_guard.sh`.**

## 5. Still open, and not mine to close

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
- Everything above was measured against `origin/main` **a4caccefeab**. Main fast-forwards, so staleness
  can turn RECOVER into LANDED but never the reverse; a force-push would invalidate that and the
  rows would need re-judging, not re-labelling.

## 6. Verifying all of it

    bash tools/harvest/bin_jharv2/check_all.sh

Nine gates. Seven need nothing but the checkout; `live_ref_citation_check.py` needs the network,
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
