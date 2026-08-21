# The hosts are live. Every unrecoverable verdict, re-derived.

jharv3 pointed out that these hosts are in use while we judge them — it watched a DROP become
a KEEP and back. A verdict is a photograph, so the ones that cannot be taken back were taken
twice.

**Only one direction is re-checked, and it is re-checked in full rather than sampled.** A
RECOVER that has since become LANDED costs a kept directory. A LANDED or ABANDON that has
since become RECOVER loses work.

| file | rows | LANDED + ABANDON re-derived | drift |
|---|---|---|---|
| `verdicts_shard_b.tsv` | 131 | 17 | **0** |
| `verdicts_shard_c_80_recovered.tsv` | 80 | 11 | **0** |
| `verdicts_extra_8hd9.tsv` | 451 | 75 | **0** |
| `verdicts_extra_8hd7.tsv` | 633 | 131 | **0** |
| | **1295** | **234** | **0** |

Spread over roughly two hours, across five hosts, nothing moved.

## The re-check was wrong four times before it was right

The first probe asked the obvious question — *do this worktree's files still differ from
main?* — and reported **7 apparent drifts**. Every one was the probe, not the world:

- **5 were `ABANDON` as superseded intermediate.** Those differ from main *by definition*: the
  branch's change is contained in main and main moved further on the same file. A probe that
  only compares bytes flags all of them by construction.
- **2 were `LANDED` reported as "now dirty".** One had a single untracked path; the other had
  **21951** `git status` lines — all of them staged *deletions*. A dirty count is not a content
  difference. Hashed, neither held one byte main lacks.

Later, on two more hosts, **3 more apparent drifts** — all `ABANDON` as duplicate, which differ
from main exactly as much as the twin being kept.

> **A "does it differ from main" probe cannot re-check an ABANDON at all.** Both ABANDON classes
> are *expected* to differ from main. Asking that question of them manufactures a finding every
> single time.

The right question is class-specific, and it is the one each verdict actually claimed:

| verdict | what re-checking it actually means |
|---|---|
| LANDED (owns files) | every owned file's sha256 still equals main's, and no uncommitted file holds bytes main lacks |
| LANDED (owns nothing) | its tree OID is still one `origin/main` publishes |
| LANDED (landed elsewhere) | its files are still byte-identical in the repository that owns the path — re-fetched, not remembered |
| ABANDON (superseded) | its own change still reverse-applies cleanly onto main |
| ABANDON (duplicate) | the named twin is still present, still clean, and still byte-identical file for file |

Had the first probe's output been reported as written, this file would have claimed 10 drifts
that never happened — a manufactured finding, which is worse than the silence it replaced.

## What was re-run, concretely

- 122 registered rows on .102 and 4 on .105 through the full probe: reverse-apply restored, and
  uncommitted files **hashed** rather than counted.
- 9 pruned rows on .102 and 34 on .105 re-judged from scratch against their manifest base.
- The `benchmark-data` LANDED re-checked against a **fresh fetch** of `vibeic/benchmark-data`
  (`bcf2f94c745`), not against the earlier answer: both files still byte-identical, still the
  whole change-set.
- Every duplicate ABANDON re-derived from the twin's side: 19/19 files and 2/2 files, zero
  differing `(path, sha256)` lines, all four trees clean.

Nothing deleted.
