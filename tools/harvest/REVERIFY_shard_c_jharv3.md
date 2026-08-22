# Shard C re-verified, independently, by a second session

`jharv3` session 2 · host 8HD-6 (192.168.1.108) · 2026-08-22

The first `jharv3` session decided shard C and pushed it. It was then reaped. This
document is the *audit* of that work by a second session that did not do it, and it
exists because the first session's own account of itself is not evidence — the same
rule the brief applies to a merge that reports "nothing to land".

**Result: the 110 rows stand. No verdict changed. One row needed adjudication and
survives with a stronger reason than the one recorded.**

Re-runnable: `python3 tools/harvest/bin_jharv3/reverify_shard_c.py --repo <clone>`.
It needs a clone and a network, and none of the three hosts.

```
  rows                     110      freshness-ok           110
  main-side-verified        88      head-side-verified      88
  branch-live              264      containment-verified    85
  no-sha-pair               22      -> all checks passed
```

## What was checked, and what it would have caught

| | check | result |
|---|---|---|
| A | 110 rows, 1:1 join with the roster, vocabulary, no dupes, no empty evidence | pass |
| B | every row cites `81cd5321b` and that **is** current `origin/main` | 110/110 |
| C | the named file's sha256 really differs from main — **both sides** re-hashed | 88/88, 0 mismatches |
| D | every "preserved as" branch is live on origin **and contains** the commit | 264 live, 85/85 contain |

Check C is the one that would catch invented evidence, so it was run in both
directions: main's side re-hashed from `origin/main`, and the *judged commit's* side
re-hashed from the object itself. All 88 head-side commits were present locally after
fetching the rescue branches — which is itself a proof that the preservation worked.
Zero mismatches on either side.

The 22 rows without a sha pair are not unchecked: 17 `L0` LANDED, 2 `L2`
uncommitted-only, 2 `A4` duplicates, 1 corrected row. Each is handled below.

## The 30 local rows, re-measured from scratch

Host 108 is this host, so its 30 rows were re-measured independently rather than
re-read — a fresh script, own merge-base, own content comparison, not the first
session's ladder. **29 of 30 reproduced exactly.**

The one that did not is `/home/reyerchu/wt-j63x8c`, ABANDON, where a naive rule says
RECOVER because the worktree owns 9 files that differ from main. Adjudicated by hand:

- it and `/home/reyerchu/jf-63x8-work/base-mml` are the **same commit** `3ab7fc723`,
  same branch, same tree `a9f2edf43`;
- `wt-j63x8c` has **0** untracked and **0** modified files; the twin has 10 untracked.
  So the twin is a strict superset and nothing unique can be lost with it;
- `3ab7fc723` is the **live tip** of `refs/heads/jmatrix/63x8-main-reds` on origin,
  confirmed by `ls-remote`, so the committed work survives regardless.

ABANDON stands. Worth noting for whoever executes: the recorded evidence rests on
"the twin is kept", and the twin is in **no** shard roster — it was never triaged.
The live-tip fact above is the load-bearing reason and is the one to rely on.

## The row that was corrected, verified at the blob

`vibe-ic-wt-caravel-slew-drv3` arrived ABANDON ("byte-for-byte duplicate") and was
corrected to RECOVER. Tree identity cannot see untracked content, and both trees
carry an untracked `HANDOFF_TO_GATEKEEPER.md` that is **not** the same file. Both are
preserved on `harvest/rescue-112-untracked-caravel-handoffs`, and re-hashing the
blobs there confirms the correction exactly:

```
HANDOFF_TO_GATEKEEPER.drv2.md   bcf26247eabbb291   7455 bytes
HANDOFF_TO_GATEKEEPER.drv3.md   f05e08482acbcffc   9892 bytes
```

The correction was right. This is also the one failure mode a tree-hash sweep cannot
see, and it is worth assuming it recurs in shards A and B.

## The unrecoverable direction

A wrong LANDED or ABANDON destroys work, so those 19 rows were checked hardest.

All 17 LANDED show `nnovel=0` **and** a clean tree in the raw measurements — nothing
the branch owns differs from main, and nothing uncommitted is on disk. Both ABANDON
rows name their twin, and both are survivable: `wt-j63x8c` via the live branch tip
above, `_v1126` via `harvest/rescue-8HD-d-v1126`, which was confirmed live and
confirmed to contain `a7b1ed913e`.

Every one of the 85 commits cited by a "recover with" line is reachable from a live
origin ref. **No row in shard C can be executed and lose work.**

## What this audit does not cover, stated plainly

Hosts 112 and 121 could not be reached from this session: direct `ssh` is
`Permission denied (publickey,password)`, and the jump route the first session used
was not available to it. So the 80 remote rows were re-verified from two things that
do not need those hosts — the recorded raw measurement transcripts (`n112.out`,
`n121.out`, both against current main, one fetch per clone, hostnames `8HD-d` and
`8hd-3`, 36 and 44 rows matching the roster exactly), and re-hashing their commits
from objects preserved on origin.

That covers content and survivability, which is what the verdicts turn on. It does
**not** re-observe the present state of those disks. Those hosts are live; the rows
carry the HEAD they were judged at, and an executor should re-measure before acting.
This is a limit of the audit, not a gap in the shard.

## Verdicts

`SHARD c COMPLETE 110 rows` — 91 RECOVER · 17 LANDED · 2 ABANDON · 0 UNREACHABLE.

0 UNREACHABLE is honest here: an earlier draft of the build script emitted
UNREACHABLE for all 80 remote rows, and that was correct *at the time* — the hosts
were later reached and measured.

## One defect found, and fixed additively

The file published as the audit trail for the 80 remote rows,
`raw_measurements_shard_c_112_121_jharv3.tsv`, is an **earlier run against the
now-stale main `a00f53f2094`** — not the current-main run the verdicts were actually
built from. It covers the right 80 paths, so nothing is missing, but it disagrees
with the verdicts it is supposed to support:

- **18 of 80** rows differ in `nadd` / `ndel` / `code_add`;
- of the 67 remote rows whose verdict names a sha256 pair, the evidence matches the
  current-main run **67/67** and the published stale file **62/67**.

So a reviewer cross-checking the verdicts against the published raw file would find
five rows whose sha256 evidence appears not to reproduce, and conclude the verdicts
were invented. They were not — they reproduce exactly against the run that produced
them, which is now published beside it as
`raw_measurements_shard_c_112_121_currentmain_jharv3.tsv`, with its main sha stated
in the header and in every row.

The stale file is **kept, not deleted**: it is a true record of what was measured
against the main of the time, and deleting is not this job's call. It now carries a
pointer to its successor.

Nothing was deleted. No working tree, index or HEAD was modified on any host. The
only writes this audit made were remote-tracking ref updates from its own fetches.

---

## Second round: the checker's own negative control was vacuous

Prompted by a note from the `.120` sweep, which had just found its first negative
control did nothing — a hash "corrupted" with `awk gsub(/[0-9a-f]{64}/…)`, where
mawk has no interval expressions, so nothing was corrupted and the checker "passed"
a file believed broken. I pointed the same question at this file and found two
defects in it. Both are fixed; the evidence and the 110 verdicts did not change.

**1. The control could not tell which check caught a fault.** `--self-test` asserted
only that *some* check went red. Deleting `check_survivability` **entirely** still
printed `D dead rescue ref — RED (detected)` and `all checks fire`, exit 0, because
check B happened to fire on the same synthetic row. Survivability is the check that
guarantees no row can be executed and lose work, and the harness would have
certified a blind one as working.

Each case now declares the check it targets and passes only if *that* check fires.
Verified by blinding each check in turn:

```
  blinding check_survivability -> self-test flags 2 blind case(s), exit=1
  blinding check_content       -> self-test flags 3 blind case(s), exit=1
  blinding check_freshness     -> self-test flags 2 blind case(s), exit=1
  blinding check_shape         -> self-test flags 7 blind case(s), exit=1
```

Before the fix each of those was exit=0.

**2. Unreadable claims were hiding in an honest-looking bucket.** The first version
knew two of this shard's evidence phrasings and filed everything else under
`no-sha-pair` — which read as "this rule makes no sha claim by design". Three rows
in that bucket *did* carry sha256 claims: `_v1123` (a full 64-char hash for a file
on disk), and both caravel rows (untracked-file claims, one of them the very row
this audit corrected). 88 verified, 22 "no claim" was really 88 verified, 19 no
claim, **3 unchecked**.

An unread claim is now a **failure**, not a pass, and the two categories are counted
apart. A hash *literal* is what makes a claim — `_jppa_skills/tree` says "sha256 on
both sides of all 28 files", which is prose about method and correctly counts as no
claim.

Three further parser bugs surfaced while fixing this, each of which had been
silently producing a wrong "cannot read" or "not found":

- the on-disk form (`is on disk here and ABSENT FROM origin/main`) was unknown;
- rows name their rescue branch in more phrasings than the strict claim-bearing
  forms (`pushed it as X` as well as `Preserved as X`), so a blob lookup had
  nowhere to look. Widening where to *search* cannot manufacture a pass — the
  sha256 still has to match;
- `the file of the same name in <dir>` names a **directory**; reading it as a
  filename made the lookup search for a stem no file has. The filename is inherited
  from the row's primary claim.

**Result — every sha256 literal in all 110 rows is now read and checked:**

```
  rows 110   freshness-ok 110   fully-read 90   no-claim-by-design 20
  main-side-verified 90   head-side-verified 88   on-disk-verified 1
  untracked-verified-from-preserved-blob 3
  branch-live 264   containment-verified 85
  0 unreadable   0 undetermined   -> all checks passed
```

Untracked bytes are on no commit, so they are only checkable if somebody preserved
them. All three untracked claims — including both sides of the caravel correction —
now verify against blobs on the rescue branches those rows name, which is the same
thing this audit had done by hand, done by the checker instead.

No verdict changed in this round either. What changed is that the file can no longer
report a green it has not earned.

---

## Third round: a check over nothing passes, and 20 rows of the consumable rest on one

jharv2 applied the blinding standard to `evidence_contract.py` and found its
absent-file branch had **no case at all** — nothing in its red→green→red proof ever
exercised it, so it could have been `ok = True` throughout. I turned the same
question on the file a downstream executor actually reads.

`verdicts_joined.tsv` carries this as the sole basis for LANDED — the verdict that
means "already on main, safe to delete":

```
all 0 file(s) this tree changed hash-match main a00f53f20 byte for byte
```

**A universal over an empty set is true of everything.** It reads like a measurement
and is a tautology. For two rows it is not merely vacuous but **false**, measured
against current main:

| path | joined view says | actually owns |
|---|---|---|
| `/home/reyerchu/_jd3` | all 0 files changed → LANDED | **3 files, all 3 differ, +212 lines** |
| `/home/reyerchu/AI_IC_design/wt_jwire2` | all 0 files changed → LANDED | **9 files, all 9 differ, +1683 lines** |
| `/home/reyerchu/_a1456` | all 0 files changed → LANDED | 0 committed, **1 uncommitted edit on no ref** |

All three are RECOVER in `verdicts_shard_c.tsv` with sha256 evidence that re-hashes
correctly against current main — `_jd3`'s named file hashes to `ac6c915e9083e606` on
main, exactly as its evidence states. The third is the subtler one: its committed
tree really is empty, so "0 files changed" is true of the *wrong question*, and the
bytes that matter are uncommitted and on no ref anywhere.

`bin_jharv3/vacuous_universal.py` gates the class. Over the joined view and all
three shard files, 96 deletion-bound rows examined:

```
  vacuous universals: 29     (joined 20, shard a 9)
  stale main cites  : 55     (joined 44, shard a 11)
  shard b: 0 and 0           shard c: 0 and 0
```

**Every one of the joined view's 44 deletion-bound rows cites `a00f53f20`**, which is
not current main. Judging deletion against a main that has moved is the exact mistake
the re-judgement was ordered to correct, and it survived into the consumable.

Its self-test holds each guarantee to both arms — unblinded catches, blinded misses,
and it stays quiet on a clean row:

```
  vacuous   unblinded=1 blinded=0 clean=0   LOAD-BEARING
  stale     unblinded=1 blinded=0 clean=0   LOAD-BEARING
```

The same shape has now appeared four times in this job: the A4 duplicate rule that
would make every worktree collide on an empty owned-set, jharv2's negative control
that corrupted nothing, my survivability check that could be deleted without the
harness noticing, and these 29 rows. A check over nothing passes.

**Nothing here changes a shard-C verdict.** Shard C is clean on both guarantees. What
this says is that an executor reading `verdicts_joined.tsv` would delete three
directories this shard verified as holding work that is not on main.
