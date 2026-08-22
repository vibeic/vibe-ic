# Four rows in my frozen shard-A file say "safe to delete" about work held by no commit

`jharvest-triage`, 2026-08-22. `jharv3` found these while re-verifying shard C and
correctly left the file to its owner. I verified independently and this is the
correction plus the root cause, which is mine.

## The breakage

`verdicts_shard_a.tsv` is frozen in batch 72 at `fa25040091`. Four of its rows are
marked **LANDED** — the verdict a later job acts on by deleting the directory —
while the directory holds uncommitted bytes that are on no commit and no remote.

| path | tracked mods | untracked | modified paths main has NEVER held |
|---|---:|---:|---:|
| `_agentjob_i1015/wt` | 98 | 0 | **3** (incl. `INDEX.md`) |
| `_agent_scratch_whatif/wt_C` | 1 | **29** | 0 |
| `_wt_1236` | 4 | 0 | **1** — `test_issue1115_not_applicable_is_not_a_pass.py` |
| `_wt_1486` | 2 | 0 | 0 (all 8 disk files are strict supersets of main's) |

Measured 2026-08-22 against main `a4caccef`, on `.120`, which holds all four.
`git cat-file -e origin/main:<path>` failing is the test for "main never held it".
My counts differ from jharv3's (98 vs 141 tracked on the first row) because the
trees kept moving between the two measurements — which is itself the reason a
verdict must carry the head and date it was taken at.

## The root cause is a rule-ordering inversion in my own tool

`HARVEST_RULE.md` line 134 says:

> `L2` | RECOVER | ≥1 tracked uncommitted EDIT — exists on one disk only, **outranks everything**

`judge_shard.sh`, the script that actually produced the file, tested the two LANDED
conditions FIRST and only reached `trk > 0` in the RECOVER branch:

    if [ "$nfiles" -eq 0 ] || [ "$differ" -eq 0 ]; then ... LANDED
    if [ "${nadd:-0}" -eq 0 ];                     then ... LANDED
    ...
    if [ "$trk" -gt 0 ];                           then ... RECOVER   <-- never reached

So a tree whose COMMITTED content is entirely in main exits as LANDED before
anything looks at the disk. `verdict_final.py`, my other implementation, has the
check first and is correct — the two disagreed and the shard file came from the
wrong one. A rule that is only in the prose is not a rule.

Fixed in `judge_shard.sh` here: the L2 test moved above both LANDED branches and
widened to count untracked files too, which is what caught `wt_C`'s 29.

## What to apply

`CORRECTION_shard_a_false_landed.tsv` — four rows, LANDED -> RECOVER, with evidence.
It is an overlay, not an edit: the frozen file is untouched.

Shard A after applying: **89 RECOVER / 25 LANDED**, still 114 rows.

## Swept all 29 LANDED rows with the corrected rule — the overlay is exactly right

Not just the four jharv3 named. Every LANDED row in shard A, re-measured on `.120`
against `a4caccef`:

    29 LANDED rows:  23 clean (0 tracked, 0 untracked) | 1 directory already gone
                      5 carrying uncommitted tracked edits

Of those five, the crude test "a tracked file is modified" is not the question. The
question is whether the disk side holds bytes nothing else has:

| row | files | lines it ADDS vs main | untracked | verdict |
|---|---:|---:|---:|---|
| `_agentjob_i1015/wt` | 98 | **1576** | 0 | RECOVER |
| `_agent_scratch_whatif/wt_C` | 29 | **1119** | **29** | RECOVER |
| `_wt_1236` | 5 | **576** (`liar_census.py` +224) | 0 | RECOVER |
| `_wt_1486` | 2 | **5** | 0 | RECOVER |
| `_wt_1390pg` | 1 | **0** (and lacks 82 main has) | 0 | **LANDED stands** |

`_wt_1390pg` is the row that proves the method discriminates rather than flagging
everything dirty. Its one uncommitted edit is a STALE copy — it adds nothing and is
82 lines behind. Deleting it loses no bytes. jharv3 reached the same conclusion
independently and their negative result holds.

So the overlay is four rows, not five, and my first fix to `judge_shard.sh` — plain
`trk > 0` — was over-cautious and would have flagged `_wt_1390pg`. Refined here to
test whether the uncommitted side ADDS lines main lacks, or carries untracked files.
Accepted residual: an uncommitted pure DELETION loses the intent to delete, never
any bytes, because main still holds them.

## The same bug reached two more of my files, and one more row was wrong

`judge_shard.sh` produced more than `verdicts_shard_a.tsv`. It also produced the 80
re-judged rows in `verdicts_unreachable_resolved.tsv` and the single row in
`verdicts_maxdepth_gap_120.tsv` — **13 LANDED rows that had never been guarded**,
because I swept only the shard file. Checking the rows the sampling named rather
than every row the broken tool touched is how the second defect survives the first.

All 13 re-measured on their own hosts against `a4caccef`:

    12 clean (0 uncommitted adds, 0 untracked)      1 defect

`.112 /home/reyerchu/_a1456` — LANDED, while holding one uncommitted tracked file
that **adds 61 lines main does not have**.

### It contradicted my own other output, and the safe answer was already written down

| file | says |
|---|---|
| `verdicts_unreachable_resolved.tsv` (mine) | **LANDED** |
| `verdicts_shard_c.tsv` | RECOVER |
| `verdicts_joined.tsv` (mine) | RECOVER |
| my own tip-equal finding, same day | "KEEP RECOVER — 1 tracked file modified" |

Three of four had it right. A reader who opened the standalone file — the natural
thing to do, since it is the one that says "resolved" — would have deleted work
that exists in one place, while the joined index two directories away said keep it.

**A per-file verdict that disagrees with the joined index is a hazard in itself.**
Whoever executes should read `verdicts_joined.tsv`, which is host-qualified and
carries the safe answer, and treat the per-file outputs as inputs to it rather than
as instructions.
