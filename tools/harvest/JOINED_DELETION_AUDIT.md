# Auditing the file an executor actually reads, and being wrong twice on the way

`verdicts_joined.tsv` is what an executor consults. 48 of its 355 rows authorise deletion and they
span all four shards; I had only audited my own 192. This is that audit, including two errors I
made inside it.

## The crude test, and how it caught me twice

I built `predelete_guard.sh` comparing each owned file's blob to `origin/main`. It refused **all 29
of my ABANDON rows** and 44 of the 48 joined deletion-bound rows.

When every row fails, suspect the check. `differs from origin/main` is not `holds work not in main`.
This repo's landed heads are ancestors: a worktree whose own change is already in main still differs
from it on every file main has touched **since**, because it holds an older copy of what main
already has. `phase3_one_shot_runner.py` recurring across unrelated worktrees was the signature.

The correct test reverse-applies the branch's own diff (`merge-base..head`) onto a temp index of
main: applies cleanly → contained → ALLOW. Re-measured, all 29 read `change_contained_in_main`.

**My ALLOW arm could not have caught this.** Its fixture had an *empty* diff, so it never entered
the state every real worktree is in. The new arm builds a branch whose change main landed and then
moved past, and asserts the head blob genuinely differs from main's — otherwise the arm proves
nothing. Red under blob-compare, green under reverse-apply.

Then I used the same crude measure again, an hour after diagnosing it, and reached a wrong
conclusion about my own row. See below.

## A vacuous zero: 27 worktrees whose HEAD commit object is gone

`.112` has been gc'd. 27 of the swept worktrees have a HEAD ref pointing at a commit that no longer
exists in the object store. `rev-parse HEAD` still answers from the ref file; every ancestry query
then fails and each failure scores **0**, which is byte-identical to clean.

My `settle.sh` skips its whole loop when the merge-base is empty and reports
`committed_differing=0` → LANDED. On that basis I declared my own `_jd3` row wrong and said so to a
peer. The guard, which fails closed, said `no merge-base with origin/main` instead — the same state,
correctly labelled.

24 of the 27 are RECOVER in every file, so they are kept. Three are deletion-bound.

## The three, measured HEAD-independently — and my rows stand

| worktree | verdicts | my row | outcome |
|---|---|---|---|
| `_jd3` | joined=LANDED, mine=RECOVER | 3 of 3 **owned** files differ, sha256 pairs cited | **my RECOVER is right** |
| `_jppa_skills/tree` | LANDED in all three files | all 28 **owned** files byte-identical to main | **my LANDED is right** |
| `_v1126` | joined=RECOVER, mine=ABANDON | duplicate of `_i_solo_1126`, which is kept | **my ABANDON is right** |

I had "corrected" `_jppa_skills/tree` to RECOVER after a walk of all 5,256 files reported 118
differing. Those 118 are main moving on, not unlanded work — the exact error I had just fixed in the
guard. Ownership scoping is what the brief asks for and what my original row used.

Verified HEAD-independently: index ≡ preserved commit tree (md5 of the sorted blob+path list matches
for all three) and `diff-files` shows the working tree matches the index.

## What is genuinely wrong in `verdicts_joined.tsv`

Four deletion-bound rows would delete content that is **not** on main, by the reverse-apply test:

| row | joined says | measured |
|---|---|---|
| `_jintent/wt` | LANDED | NOT_CONTAINED, 6 owned files |
| `AI_IC_design/wt_jwire2` | LANDED | NOT_CONTAINED, 13 owned files |
| `_jd3` | LANDED | 3 of 3 owned files differ |
| `_a1456` | LANDED | 1 untracked file, a different version of a file main has |

## None of it is unrecoverable, and that is not luck

Every one is preserved on origin — checked with `ls-remote` as the authority, never `refs/remotes`:

    _jintent/wt         c5c2e228244  origin/agent/jintent-flow-gate-intent
    wt_jwire2           88b9399076a  advertised tip, refs/heads/fix/jwire2-hygiene-wiring
    _jd3                66e0806689e  advertised tip; also 3 harvest/rescue-* refs
    _jppa_skills/tree   39b985af57a  origin/harvest/rescue-8HD-d-stale-remote-vibe-ic
    _v1126              a7b1ed913e2  advertised tip; origin/harvest/rescue-8HD-d-v1126
    _a1456 untracked blob c91acbe9f578  reachable from 12 commits incl. preserve(pruned-8HD-9)

The verdicts are still false and should be corrected. But the rescue and preserve work is what turns
a wrong LANDED from an unrecoverable loss into a recoverable one, and `_a1456`'s untracked file —
which no commit in its own worktree holds — survives only because of the preserve pass.

## Duplicate-justified ABANDONs: the twin has to be checked, not assumed

Four of my ABANDON rows are justified as duplicates. That is safe only if the twin exists, still
matches, and is itself kept — two defensible arbitrations can otherwise close both members of a pair.
Verified by whole-index comparison, not just the owned files:

| abandoned | twin | index md5 | twin's verdict |
|---|---|---|---|
| `_v1126` | `_i_solo_1126` | identical, 21804 files | RECOVER in all 3 files |
| `_jcpath2/wt_new` | `_jcpath2/mut` | identical, 6408 files | RECOVER |
| `_jlandpar/wtgates` | `_jlandpar/dev` | identical, 5663 files | RECOVER |
| `_jlandpar/wttests` | `_jlandpar/dev` | identical, 5663 files | RECOVER |

Both sides clean in every case.
