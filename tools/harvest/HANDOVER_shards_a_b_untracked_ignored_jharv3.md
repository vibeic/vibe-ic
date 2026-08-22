# Measured for shards A and B, not judged: the same blind spot, and five rows that fail it

`jharv3`, 2026-08-22, from host .108. **This file contains no verdicts.** Shards A
and B belong to their agents; this is the measurement they were missing, taken while
the route to the hosts was open, so nobody has to find it again.

## Why it exists

Shard C's deletion-bound rows rested on `git status --porcelain -uno`, which cannot
see untracked files, and then on `-uall`, which cannot see ignored ones. Both were
closed for shard C. The same two blind spots apply to every deletion-bound row in
shards A and B, and `ignored_accounted.py` was scoped to what had been measured
rather than passing them quietly. This measures them.

`.105` answers a direct ssh from `.108`; `.114` and `.120` do not, but
`ssh .102 "ssh .1xx ..."` reaches both. Read-only probes piped in on stdin; nothing
written on any host.

**29 deletion-bound rows** (12 shard A on .120, 17 shard B on .105 and .114), plus
the two twins shard B's ABANDONs name, `_jcpath2/mut` and `_jlandpar/dev`.

## Shard B: clean, 17 of 17

    $ ignored_accounted.py --verdicts verdicts_shard_b.tsv \
        --raw raw_ignored_entries_shards_a_b_jharv3.tsv \
        --measured raw_untracked_ignored_shards_a_b_jharv3.tsv
    ignored entries examined: 210  accounted: 210  unaccounted: 0
    deletion-bound rows: 17  measured: 17
    IGNORED ACCOUNTED OK

Both named twins measured too: `_jcpath2/mut` and `_jlandpar/dev` are 0 untracked,
0 modified, so the duplicate justifications survive contact with the disk.

One measurement worth passing on rather than acting on: `_jppa_p0/tree` (ABANDON)
owns 5 files and **1 differs** from current main —
`programs/phase3_one_shot_runner.py`. That is the file your own audit identified as
the signature of *main moving on*, and a blob compare over-reports exactly there.
Your reverse-apply test read `change_contained_in_main` for all 29 of your ABANDONs.
I am recording the blob difference, not contradicting your test.

## Shard A: five of twelve deletion-bound rows are dirty on disk

    DIRTY /home/reyerchu/_agent_scratch_whatif/wt_C   untracked=29  modified=29
    DIRTY /home/reyerchu/_agentjob_i1015/wt           untracked=0   modified=141
    DIRTY /home/reyerchu/_wt_1486                     untracked=0   modified=8
    DIRTY /home/reyerchu/_wt_1236                     untracked=0   modified=5
    DIRTY /home/reyerchu/_wt_1390pg                   untracked=0   modified=1

Four of the five are the rows `rescue_contradiction.py` has been red on; the fifth,
`_wt_1390pg`, is one of `vacuous_universal.py`'s UNTRACKED-SILENT rows. Both gates
were arguing from the verdict file. This is the same finding from the disk.

Two details the counts hide:

- `_agent_scratch_whatif/wt_C`'s 29 untracked files are authored work, not output:
  a 29 KB `phase1_planned_consumer_starved_check.py`, twenty-two new tests, four
  ORGANIC backlog YAMLs, three upstream assessments. Untracked content is on no
  commit; a LANDED verdict over it is the exact shape of the one wrong verdict in
  shard C.
- `_wt_1486` is mid-merge: four of its eight entries are `UU` (both-modified
  conflicts), including a 305 KB `flow/phase1_phase2_phase3.yaml`. Deleting that
  directory discards a conflict resolution in progress.

## Nothing is at risk of being lost — checked, not assumed

Every dirty file's **git blob id** was read on `.120` and looked up in the rescue
refs. 170 of 170 are on origin:

| row | dirty files | covered by |
|---|---:|---|
| `_agentjob_i1015/wt` | 98 | `harvest/rescue-120-falselanded-_agentjob_i1015-wt` |
| `_agent_scratch_whatif/wt_C` | 58 | `harvest/rescue-120-falselanded-_agent_scratch_whatif-wt_C` |
| `_wt_1486` | 8 | `harvest/rescue-120-falselanded-_wt_1486` |
| `_wt_1236` | 5 | `harvest/rescue-120-falselanded-_wt_1236` |
| `_wt_1390pg` | 1 | **not** in `harvest/rescue-120-preserve-201-_wt_1390pg` |

The last one is the interesting one and it is why this was worth doing by blob
rather than by ref name. `_wt_1390pg`'s single uncommitted edit —
`tools/phase1_engine/tests/test_typical_scaffolds_retired.py`, blob
`5875535c65a7e29275eff21aa640a7e948f4447a`, 17700 bytes — is **not** in the preserve
ref that carries its name. It is on origin all the same, at
`harvest/preserved-pruned-8HD-9` (`114fc14e715`), under
`preserved/tmp_claude-1000_…_w20/tools/phase1_engine/tests/…` — a different ref
under a different path. Confirmed by walking that commit's tree for the blob, not by
reading a ref name.

So: **the five verdicts are wrong as written, and none of them is unrecoverable.**
Those are two separate statements and both are needed. Fixing the verdicts is shard
A's owner's call; this file does not touch `verdicts_shard_a.tsv`.

## Ignored content: 210 entries, all accounted

Across all 31 measured directories: 210 ignored entries, 210 attributed by
`git check-ignore` to a rule `origin/main`'s own `.gitignore` declares generated or
scratch. Same six classes as shard C — `__pycache__/`, `.pytest_cache/`,
`synthetic_benchmark_phase1/`, `plugins/vibe-ic/reports/`, `docs/reports/`,
`scratch_geom_signoff_tests/`. Nothing unclassified on either shard.

## Files

    raw_untracked_ignored_shards_a_b_jharv3.tsv   31 rows, one per directory
    raw_ignored_entries_shards_a_b_jharv3.tsv     210 ignored entries
    bin_jharv3/ignored_accounted.py               --verdicts / --raw / --measured
    bin_jharv3/probe{1,2,3}_*.sh                  the read-only probes and the route
