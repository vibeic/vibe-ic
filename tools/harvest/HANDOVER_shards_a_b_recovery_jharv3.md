# Handover to shards A and B — recovery paths, measured, no verdict attached

`jharv3`, 2026-08-22, from the `.108` clone. **I did not edit `verdicts_shard_a.tsv` or
`verdicts_shard_b.tsv`.** Those rows and their corrections belong to their owners. This is the
measurement, the tool that produced it, and one exposure I closed because closing it destroys
nothing and leaving it open could.

## Shard B — green, and my first run of it was wrong

131 rows, every one carrying a survivability citation. **0 rows lack an instruction that
resolves today.**

My first run reported 18 defects. All 18 cited `refs/pull/N/head`, and my gate walked citations
through the branch namespace it had fetched, which does not mirror PR refs — so it reported
"no named ref both lives and contains this head" for refs that were alive and did contain it.
That was my tool's blind spot, not shard B's defect, and it is why those 18 are named here as a
correction rather than as findings. The gate now resolves a PR head to its live sha from
`ls-remote`, fetches the object if this clone lacks it, and walks it. Shard B is green.

## Shard A — two things its owner should see

**1. Every row is judged against a main that is 244 commits old.** All 114 rows cite
`a00f53f20948` (plugin v1.11.66); `origin/main` is `a4caccefeab57`. That old main IS an ancestor
of the current one, which bounds the damage precisely:

- its **12 LANDED** rows are not endangered — content that was on main then is still in main's
  history now, and landing does not un-land;
- its **102 RECOVER** rows may contain work that landed in those 244 commits. That costs a
  person a redo, not a loss — but it is the exact staleness the shard split was created to
  correct, and shard C's own prior verdicts were discarded for it.

**2. No shard-A row says where its commit lives.** `reachable from`, `git fetch origin` and
`SURVIVABILITY` appear **0 times in all 114 rows**, so my gate refuses on that file as vacuous
rather than reporting a pass. A RECOVER row with no anchor tells a reader nothing about whether
deleting the directory loses the work.

Placement of its 114 heads, measured from this clone against `git ls-remote` (never from
`refs/remotes`, which caches refs origin has deleted):

| where the head lives | count |
|---|---:|
| a live origin branch | 70 |
| a live PR head (`refs/pull/N/head`, cached ref confirmed to still match origin) | 22 |
| **no live ref at all** | **1** |
| object not in this clone — **UNDETERMINED from here** | 21 |

The 21 are listed in `shard_a_heads_undetermined_from_108_jharv3.tsv`. They are not a finding:
their objects live in a clone on shard A's own host, and only that host can place them. An
honest UNDETERMINED with the missing input named beats a guess either way.

## The one exposure closed, and why

`/home/reyerchu/_agentjob_jf63x8g/dr2`, head `5fdfe020212f`, a shard-A **RECOVER** row, was on
no live ref. By content it holds 8 files differing from **both** `origin/main a4caccefe` and its
merge-base `69ce9260dfd4` — the matrix_63x8 tests, `flowref.py`, `tapeout_docs_gen.py`, the
phase1_phase2_phase3 flow — and its snapshot is not among the 2944 tree hashes on main. Its only
copies were that directory and one object store.

Folded into this branch as a second parent, changing no tree and no verdict, and read back
through the pushed ref to confirm it arrived:

```
git fetch origin harvest/worktree-triage-jharvest && git checkout 5fdfe020212f
```

Its row also reports **1 tracked file uncommitted in that directory and nowhere in git**. That
one I cannot close from here — it is on shard A's host and needs its owner.

## The tool

`bin_jharv3_s5/recovery_resolves.py <verdicts.tsv> [repo]`, `--self-test` for its guarantees.
It parses all three citation forms in use across the three shards, requires a named ref to be
live **and still contain** the row's head, reports UNDETERMINED separately from a defect, and
**exits 2 rather than reporting a pass when it parses no citation at all** — the failure that
let a clean report cover 86 broken rows in shard C. Self-test: 7 cases, 4 of them driven to RED.
