# Four LANDED rows in shards A and B are wrong, and the content is preserved

Found by **jharv3** on 2026-08-22 while re-verifying shard C. These rows are not
in my shard — `verdicts_shard_a.tsv` and `verdicts_shard_b.tsv` belong to
`jharvest-triage` and `jharv2`. **I have not edited either file.** This is the
measurement and the rescue; the correction is the owner's.

## Why I looked

Shard C had an ABANDON that rested on "identical HEAD tree, and both working
trees are clean". The tree half was true and the clean half was false, and the
untracked file it missed was the whole of the recoverable work. That is a defect
in the *test*, not in one row — so it should be expected wherever a
deletion-bound verdict leans on the tree alone.

There are 25 LANDED rows across shards A and B and 3 ABANDON rows in shard B.
LANDED and ABANDON are the two verdicts someone acts on by deleting, so all 28
were re-measured on the hosts that hold them.

## What holds

**All 3 shard-B ABANDON rows hold.** `_jlandpar/wtgates` and `_jlandpar/wttests`
share the *identical HEAD commit* `01f0086263e` with `_jlandpar/dev`, tree
`956e469a778…` on all three, and all three working trees are genuinely clean —
0 tracked, 0 untracked. `_jppa_p0/tree` is at its judged head `779e4eed514` and
is also clean. The blind spot did not bite here.

**20 of 25 LANDED rows hold** — clean trees, at their judged heads, on .105,
.114 and .120.

**One dirty LANDED row still holds**, and it is the row that shows the method is
not just flagging everything: `/home/reyerchu/_wt_1390pg` has one tracked edit,
`tools/phase1_engine/tests/test_typical_scaffolds_retired.py`. It differs from
main — but in the direction that means *stale*: main has 82 lines the disk copy
lacks and the disk copy adds none. Nothing there is absent from main. LANDED
stands.

## What does not

Four rows are marked LANDED — the verdict that says the content already reached
main and the directory is safe to delete — while holding uncommitted bytes that
are not on main. All four are on **.120**.

| path | shard | tracked edits | differ from main | absent from main | deleted on disk |
|---|---|---:|---:|---:|---:|
| `/home/reyerchu/_agentjob_i1015/wt` | A/B | 141 | 95 | **3** | 43 |
| `/home/reyerchu/_agent_scratch_whatif/wt_C` | A/B | 29 (+29 untracked) | 30 | **7** | 0 |
| `/home/reyerchu/_wt_1236` | A/B | 5 | 4 | **1** | 0 |
| `/home/reyerchu/_wt_1486` | A/B | 8 | 8 (all novel) | 0 | 0 |

"Absent from main" means `git cat-file -e origin/main:<path>` fails — main has
never held that path. Those are not stale copies of landed work; they are files
that exist in one place. Among them:

- `…/tests/test_flow_compliance_analog_trigger_is_content_not_existence.py`
- `…/tests/test_l5_analog_evidence_scoped_to_its_list_item.py`
- `…/tests/test_log_invocation_retires_superseded_declarations.py`
- `…/tests/test_sdc_gen_supersedes_its_own_stale_top_sdc.py`
- `…/tests/test_issue1115_not_applicable_is_not_a_pass.py`
- three `tools/vibeic-eda/upstream-assessments/2026-08-05-*.md`

`_wt_1486` has none absent, so it needed the sharper test: for each of its 8
files, does the disk side *add* lines main does not have? All 8 do. The clearest
is `test_signoff_medlow_backlog_gaps.py` — the disk copy adds 138 lines and main
has **zero** lines it lacks, so the on-disk file is strictly a superset of main's.

## Preserved

Uncommitted content is on no ref, so a wrong LANDED here was unrecoverable. It is
not any more:

| branch | commit |
|---|---|
| `harvest/rescue-120-falselanded-_agentjob_i1015-wt` | `d3f072f2377f0cce094cdae0457bfcd52b287b25` |
| `harvest/rescue-120-falselanded-_agent_scratch_whatif-wt_C` | `66f0222826572bfe7dc9b38c5b85ef6c150f072a` |
| `harvest/rescue-120-falselanded-_wt_1236` | `a2c981cb098459b3397d0e4678831698a2aade7a` |
| `harvest/rescue-120-falselanded-_wt_1486` | `544526531524ef82fb20909e59f56e386461d57e` |

Each is the working state laid over the HEAD its row was judged at, so the commit
and the loose bytes travel together. Recover with
`git fetch origin <branch> && git checkout FETCH_HEAD`.

**How they were made, because a rescue you cannot audit is not a rescue.** The
changed files were *read* off .120 over ssh; all 169 were re-hashed here and
matched the sha256 the host reported, 0 mismatches, before anything was
committed. The trees were assembled with plumbing against a temporary index — no
checkout — and the executable bit was carried across for the 4 files that had it.
Then one file was fetched back *through the pushed ref* rather than read out of
the local object store, and hashed again:
`test_l5_analog_evidence_scoped_to_its_list_item.py` →
`231b5f2ee6db8e3f3fb2bc4657e7ce16e4b6ff4790893ea4ea7ea8b4f1a67a6d`, the same
value .120 reported. The round trip is closed.

Nothing on .120 was written, moved or deleted — not a working tree, not an index,
not a HEAD. `git ls-remote --heads origin` confirms all four refs live.

## What the owners should do

Flip these four to RECOVER in `verdicts_shard_a.tsv` / `verdicts_shard_b.tsv`,
citing the rescue branch. The content is safe either way now; what is not safe is
a file that still says LANDED, because the next job reads the file, not this one.

## The rule this is really about

A verdict of LANDED or ABANDON is a claim about a **directory**, and a directory
is more than its HEAD commit. Tree identity, `merge-base`, reverse-apply and
per-file sha256 of *owned* files all describe committed history. None of them can
see an uncommitted edit or an untracked file, and those are precisely the content
that exists in exactly one place.

Any deletion-bound verdict needs the working tree measured beside the history,
and the check has to be `--untracked-files=normal`, not `no`.
