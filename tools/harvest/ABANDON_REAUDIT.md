# The untracked-directory collapse survived in the one script that authorises deletion

I found the collapse defect in `judge.sh`, fixed it there and in `untracked_all.sh`, re-judged 43
rows on .102, and reported it closed. It was not closed. `abandon_audit.sh` -- whose entire job is
to certify that an ABANDON row is safe to delete -- still read `--untracked-files=normal` with the
same `[ -f ]` filter underneath it. Fourth occurrence this session of *fixed in one place, not all
places*. Grepping my own tooling for the flag would have found it; I grepped for `-uno` instead,
which was the wrong string, and reported zero.

## The finding is not "wrong flag"

`abandon_audit.sh` computes two numbers:

| number | how counted | can it reach 0 while files exist? |
|---|---|---|
| `status_lines` (`n`) | every porcelain entry | **No.** A collapsed directory still yields one entry. |
| `new` | counted *after* `[ -f "$wt/$f" ]` | **Yes.** The `dir/` entry is not a file, so it is dropped. |

The verdict reads `new`. Measured on a real worktree with one planted untracked directory:

    OLD (-unormal): CLEAN   status_lines=1  modified=0  new=0
    NEW (-uall):    DIRTY   status_lines=1  modified=0  new=1  NEW:__ctl_probe/deep/probe.txt

The safe signal was present, already computed, and non-zero. The script used the derived one that
`[ -f ]` can zero. jharv3's rule -- *a gate that asks "is anything untracked here?" is safe under
both forms* -- is exactly right, and this gate was not asking that question.

Pinned as `test_abandon_audit_untracked_collapse.sh`, including the two-number distinction, so the
flag cannot be simplified back without a red. Red without the fix: `new=0 verdict=CLEAN`.

## Re-audit of every ABANDON row I own: 29/29 safe

All 29 re-measured under `--untracked-files=all`. A zero under `-uall` cannot be a collapsed
anything, so these are true zeros and the verdicts stand.

| file | ABANDON rows | re-audited |
|---|---|---|
| verdicts_shard_b.tsv | 4 | 4 clean |
| verdicts_shard_c_80_recovered.tsv | 1 | 1 clean |
| verdicts_extra_8hd9.tsv | 5 | 5 clean |
| verdicts_extra_8hd7.tsv | 19 | 19 clean |

No verdict moved. The defect was real and the exposure on these rows was nil -- which is luck about
which worktrees had scratch directories, not a property of the method.

## Four rows read GONE, and GONE was wrong

Audited from .105 and .102, four ABANDON worktrees reported `GONE`. They are not gone. They are on
hosts I had not asked:

    _v1126               -> .112   status_lines=0
    _jcpath2/wt_new      -> .114   status_lines=0
    _jlandpar/wtgates    -> .114   status_lines=0
    _jlandpar/wttests    -> .114   status_lines=0

Had I stopped at the .102 result I would have written "4 GONE" as a measurement. A path absent from
the two hosts you happened to ask is an unasked question, not a deleted directory -- the same shape
as the collapsed directory and the mawk interval: **a confident, well-formed, wrong number.**

## Drift direction, now measured rather than assumed

The claim that staleness can only turn RECOVER into LANDED, never the reverse, rests on main
fast-forwarding. Checked, not assumed -- every main any of my rows was judged against is an
ancestor of live `origin/main` 81cd5321b08:

    a00f53f2094  ancestor, 30 commits since
    81cd5321b08  ancestor, 0
    f6db3e921e6  ancestor, 1310

So the direction argument holds for every row I shipped. Under a force-push it would not, and the
rows would need re-judging rather than re-labelling.
