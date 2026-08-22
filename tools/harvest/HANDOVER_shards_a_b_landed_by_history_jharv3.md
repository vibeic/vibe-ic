# Handover to shards A and B — 27 rows carry RECOVER over work that already landed

`jharv3`, 2026-08-22, measured from the `.108` clone with disk state read on `.120`, `.105` and
`.114` through the `.102` hop. **I did not edit `verdicts_shard_a.tsv` or `verdicts_shard_b.tsv`.**
The measurement, the tool, and the blockers are here; the verdicts are their owners' to change.

## The defect is in the rule, not in anyone's care

Shard C used rule R2: a worktree is unlanded when one of its files differs from
`git show origin/main:<path>`. That is main's **tip**. The brief warns that a squash-landed
branch still shows as *ahead*; the half nobody wrote down is that it also still shows as
**different**, because main keeps moving past work it has already taken. R2 cannot separate
landed from unlanded, and in shard C it mislabelled **16 of 90 RECOVER rows** — those are now
LANDED, each with a named main commit holding the very file the row cited as proof of divergence.

Shards A and B were judged with the same rule. They have the same defect.

## What was measured here

The question that separates the two cases: **did main's history ever hold these bytes at this
path?** Asked for every tracked file of every shard-A and shard-B row whose head this clone
holds — blob identity first, then a `--full-history` walk of the path for anything the index
cannot vouch for.

- **Shard A: 15 of 114 rows** carry RECOVER over content main's history already holds.
- **Shard B: 23 of 131 rows** likewise.
- The 21 shard-A heads this clone does not hold **are now judged too** — see the section below.
  They were UNDETERMINED only because the objects live on `.120`; that host answers, so the
  missing input was fetched rather than written off.

Every one of those 38 was then read on its own host: HEAD, `--untracked-files=all`, tracked
modifications, and gitignored entries.

**27 are ready to move to LANDED today** (12 in shard A, 15 in shard B) — clean on disk, HEAD
where it was judged or re-judged there, no ignored entry outside the classes main's `.gitignore`
declares generated. **11 are blocked, each for a stated reason**, in
`shard_a_b_landed_by_history_jharv3.tsv`.

## The blockers, and the two that matter most

| blocker | rows |
|---|---:|
| uncommitted content on disk, held by no commit — **the value is those files, RECOVER is right** | 7 |
| **holds work main never had, at the head on disk** | 2 |
| the directory no longer exists on its host | 1 |
| head object not in this clone — UNDETERMINED | 1 |

The two that matter: `_jrows/rows` and `_agentjob_jeco/wt` are landed **at the head they were
judged at** and hold **15 and 29 paths main has never held at the head on disk**. Their HEADs
moved after judging. A sweep that trusted the judged head — mine included, until I re-read the
disk — would have handed someone a LANDED verdict over 44 files of live work. **Re-judge at the
head on disk, or do not flip.** `_wt_spm_ihp_atpg` is a third instance of the same lesson in a
harsher form: its directory is simply gone.

## How to check this without taking my word

```bash
tools/harvest/bin_jharv3_s5/landed_by_history.py <head> [repo] [main]
tools/harvest/bin_jharv3_s5/landed_by_history.py --self-test
```

The self-test drives five guarantees, two of which are traps this measurement fell into first:

1. `git rev-list --objects <main>` names each blob under **one** path, so a `(path, blob)` index
   built from it misses **109 of main's own tip files** and cannot prove absence. Build the
   path-keyed index from `git log --raw` instead — that one covers main's tip completely.
2. `git rev-list <main> -- <path>` **simplifies history**: for one file it returned 7 commits and
   hid the one holding the content, where `--full-history` returned 14 and found it at
   `bf85ef43adb2`. My first proof run reported NOWHERE for content that was plainly there.

Also: main's own tip must classify as reached over >1000 files, a known-unlanded head must
classify as holding work, and a head tracking zero files must be **REFUSED**, never passed.

## The 21 that were UNDETERMINED are now decided

They were unreadable from `.108` because their objects only exist in `.120`'s clone. `.120`
answers through the `.102` hop, so their trees were read there (read-only, no fetch in their
clone, 43 MB of `path<TAB>blob` lines) and judged here against main's history. Blob hashes
compare across machines without moving a byte of content.

**All 21 decided, 0 left UNDETERMINED, and no head among them has drifted from what its row
cites:**

| result | rows |
|---|---:|
| **holds content main never had — RECOVER is CORRECT** | **15** |
| content already on main, clean on disk → **ready for LANDED** | 2 |
| content already on main, but dirty on disk → RECOVER is right, the value is the uncommitted files | 3 |
| already carries LANDED, and content confirms it | 1 |

The 15 are the reassuring half: `_wt_c2` and `_wt_c3` hold 22 and 23 paths main has never held,
`advA` 5, `advC` 6, `_agentjob_i1424/reb` 8, and so on — real work, correctly kept.

The two that can move are `_wt_v1610` and `vibe-ic-wt-caravel-final` — clean, no drift, ignored
entries only in classes main declares generated (7 and 1 entries).

**Shard A therefore has 20 RECOVER rows whose content main's history already holds, 14 of them
ready to move today.** Per-row detail: `shard_a_undetermined_now_judged_jharv3.tsv`.

## Data

- `shard_a_b_landed_by_history_jharv3.tsv` — per row: shard, path, host, judged head, paths main
  never held, disk state, an example main commit holding its content, ready-for-LANDED, blocker.
- `shard_a_b_disk_state_jharv3.tsv` — the raw host reads behind the disk column.
- `shard_a_undetermined_now_judged_jharv3.tsv` — the 21 former UNDETERMINEDs, now decided, with
  disk state and the paths main never held.
