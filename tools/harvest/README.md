# vibe-ic worktree harvest — what to read, in order

Three agents produced this directory: `jharvest-triage` (shard A), `jharv2` (shard B and the
extras), `jharv3` (shard C). A reader currently faces 26 TSVs, 21 markdown files and 68 scripts
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

Nine of the twelve carried evidence of the form *"all **0** file(s) matched main"* — a universal over
an empty set. **All 20 such rows in `verdicts_joined.tsv` are deletion-bound**, which is causal
rather than coincidental: "every file matched" is exactly what produces LANDED.

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

## 5. Still open, and not mine to close

- The 12 corrections are **not applied**. `verdicts_joined.tsv`, `verdicts_shard_a.tsv` and
  `verdicts_unreachable_resolved.tsv` still carry the rows they contradict.
- `bin_jharv2/extras_coverage.py` stays RED against `verdicts_joined.tsv`, correctly: those 1083
  rows are genuinely not in it. Pointing that gate at `verdicts_all.tsv` would be circular, since
  the same generator writes both.
- Everything above was measured against `origin/main` **a4caccefeab**. Main fast-forwards, so staleness
  can turn RECOVER into LANDED but never the reverse; a force-push would invalidate that and the
  rows would need re-judging, not re-labelling.

Counts in this file are checked by `bin_jharv2/readme_numbers_check.py`.
