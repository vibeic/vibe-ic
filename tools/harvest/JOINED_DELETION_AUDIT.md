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

## The vacuous universal is not scattered — it is 100% deletion-bound

`verdicts_joined.tsv` has 20 rows whose evidence reads *"all **0** file(s) this tree changed
hash-match main byte for byte"*. A universal over an empty set is true and says nothing.

**All 20 are deletion-bound. Not 20 of 48 at random — every single vacuous row is a LANDED.**

That is causal, not coincidental: "every file matched" is exactly what produces LANDED, so a row
whose file-enumeration returned nothing lands in the delete bucket by construction. The vacuity does
not scatter across verdicts; it concentrates entirely on the one that destroys.

Nine of the 20 are shard A and had not been measured by anyone. Measured with the corrected guard:

| row | joined | measured |
|---|---|---|
| `_agentjob_i1015/wt` | LANDED | **98 uncommitted files differ from main** |
| `_agent_scratch_whatif/wt_C` | LANDED | **37 uncommitted files differ** (clone was stale; fetched forward first) |
| `_wt_1486` | LANDED | 8 uncommitted differ, incl. `flow/phase1_phase2_phase3.yaml` |
| `_wt_1236` | LANDED | 5 uncommitted differ |
| `_agentjob_jliar/wt` | LANDED | 2 files not contained in main |
| `_wt_1390pg` | LANDED | 1 uncommitted differs |
| `_agentjob_jeco/base`, `_jppa_prscope/base`, `_jsearch2/base` | LANDED | contained in main — correct, despite vacuous evidence |

Six of nine hold real content. Three are right by luck of what the empty set happened to hide.

## Nothing is unrecoverable — verified, not assumed

Uncommitted content is held by no commit, so rescue anchors do not cover it by construction. That
made these 149 files the only candidates for genuine loss in the whole audit. Checked properly:

    149 uncommitted blobs (112 + 37)
    present in the object store          149 / 149
    reachable from a ref                 149 / 149   (comm AND an awk set-intersection, never comm alone)
    reachable from an ORIGIN ref         149 / 149   (local refs die with the clone; origin is the authority)

Presence in an object store is not reachability, and reachability in one clone is not survival — this
repo warns of unreachable loose objects, and a blob a gc away from gone is not preserved. All three
questions had to be asked separately. All 149 pass all three.

**No unrecoverable loss exists in any deletion-bound row measured in this audit.** The verdicts are
still false and should be corrected: a row that says "all 0 files matched" while its tree holds 98
differing files is wrong regardless of whether the content survives elsewhere.

## 48 of 48, and the seven I had not asked about were on a host I never asked

The sweep resolved 41 of 48 and left 7 "unresolved on any host". All 7 name host **.108** in the
roster, and .108 answers directly from here. I had swept .105, .102, .112, .114, .120 and .121 and
simply never asked it — the same shape as the four rows I called GONE earlier. Asked, all 7 resolved.

**Final: 48/48 resolved. 34 ALLOW, 14 REFUSE.**

The 14 REFUSE break down as: 8 holding content by direct measurement, 3 twin-justified ABANDONs the
guard cannot see past, 2 whose HEAD commit object is gc'd (measured separately — my rows stand), and
1 whose clone was stale until fetched forward.

## `git diff-files` compares stat data, not content

`wt-j63x8c` is jharv3's ABANDON, justified as having an identical HEAD to `jf-63x8-work/base-mml`.
My twin check reported the twin as dirty in all 6368 files, which would have made that justification
unsafe. It was my check that was wrong:

| worktree | diff-files before refresh | after refresh | differing by CONTENT |
|---|---|---|---|
| `wt-j63x8c` | 4728 | 0 | 0 |
| `jf-63x8-work/base-mml` | 6368 | 1640 | 122 |

`diff-files` compares the index's **stat** data to the working tree, so after a copy or a checkout
that rewrites mtimes every entry reads dirty. `git status` refreshes first; `diff-files` does not.

The error is one-directional — it over-reports — so **a 0 from it is trustworthy and a non-zero
means nothing until content is checked**. That asymmetry is why my four twins reading `dirty=0`
stand unchanged, and why this one needed content measurement before I could say anything.

`wt-j63x8c` itself is clean, its HEAD equals the twin's, and that HEAD `3ab7fc723e4` is an advertised
origin tip on `origin/jmatrix/63x8-main-reds`. **jharv3's ABANDON is safe.** The 122 differing files
belong to `base-mml`, which is named in no verdict file and is therefore not scheduled for deletion —
but it holds unjudged uncommitted work, which is worth someone's attention.
