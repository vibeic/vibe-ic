# Shard C re-judged against CURRENT origin/main — session 8 (jharv3, .108 / 8HD-6)

## Why this run exists

Shard C's 110 verdicts were all decided against `origin/main` **a4caccefe** (v1.11.66).
That sha is no longer main. Main is now **ae78abb285630636b2f305f2ed4aef13f92201ed**
(v1.11.70), **673 commits later**, and `a4caccefe` is a strict ancestor of it
(`git merge-base --is-ancestor` — measured, not assumed).

The brief's own instruction is `git fetch` FIRST and judge against CURRENT main; the
355 prior verdicts it was correcting were stale for exactly this reason. A shard that
was correct at 07:00 and is re-read at 19:00 against a main that took 673 commits in
between is in the same position. The failure mode is specific and one-directional:

* A **RECOVER** decided against a stale main can be work that **has since landed**.
  Acting on it sends somebody to redo finished work, and keeps a directory alive that
  no longer holds anything.
* A **LANDED** cannot go stale while main only grows — but that is an assumption, so
  G2 below measures it instead of asserting it.

## Method — content, never ancestry

`vibe-ic` squash-lands, so `merge-base --is-ancestor`, `branch --merged`,
`rev-list origin/main..HEAD` and `git status` all report landed work as unlanded. The
test is the one session 5 established, re-run at the new main:

> Build the set of every `(path, blob)` pair `origin/main`'s **history** has ever held
> (`git log --raw -m`, both pre- and post-image blobs, so a blob main later deleted
> still counts as content main held at that path). A worktree's judged HEAD tree is
> fully landed iff every `(path, blob)` pair in it is in that set.

Judging against main's **tip** instead of its history cannot separate landed from
unlanded work. G3 below shows exactly that red.

All 109 judged HEADs in shard C (103 distinct) resolve in the `.108` object store —
verified with `git cat-file -e` — so this sweep reads trees, not live directories, and
touched no fleet host.

Script: `bin_jharv3_s8/rejudge_vs_current_main.sh` (with `--self-test`).
Raw: `raw_rejudge_current_main_s8_jharv3.tsv`.

## The self-test, and the red it shows

    $ bash bin_jharv3_s8/rejudge_vs_current_main.sh --self-test <old_map> <new_map>
    G1 GREEN: all 6667 of main's tip (path,blob) pairs are in the map
    G2 GREEN: old map is a subset of new (38994 -> 40565 pairs, 0 lost)
    G3 GREEN: tip-comparison calls this landed row unlanded on 2034 paths; history says 0 unproven
    G4 GREEN: negative control reports 3 unproven pairs -- the sweep is not vacuous
    G5 GREEN: degenerate-map refusal fires

* **G1** is the non-vacuity guarantee: main's own 6667 tip pairs must all be explained
  by the history map. A truncated map, or the mawk `{40}`-interval trap that made an
  earlier sweep report 0 unproven over an empty set, goes RED here.
* **G2** is what licenses "the 34 LANDED rows cannot have regressed": every pair known
  at `a4caccefe` is still known at `ae78abb285`. 0 lost, 1571 gained.
* **G3 is the red this method exists to avoid.** `/home/reyerchu/_dens_priv/wt-jdrc1177`
  is LANDED in the deliverable. Against main's **tip** it differs on **2034 paths** and
  reads as unlanded; against main's **history** it has **0** unproven pairs. Without the
  history map this row, and roughly 300 others across the three shards, get sent back
  for work that is already on main.
* **G4** is a live negative control: `/home/reyerchu/_cpath_priv/tree` must still report
  unproven pairs. If it reported 0 the `comm` would be passing over an empty set.

## Result — 673 commits of main moved exactly one row

| | |
|---|---|
| rows swept | 110 |
| rows whose unproven count changed | **1** |
| LANDED rows still fully in main's history | **34 / 34** |
| ABANDON row | still holds content main never held |
| RECOVER rows with content main never held | 70 |
| RECOVER rows with no judged head (value is an untracked file) | 1 |

### The one row main moved: `/home/reyerchu/AI_IC_design/wt_jwire2` (host .121)

Judged HEAD `4c77f7f0ae43915d5f550e4b096b0e9ef8144710`, 6504 tracked files.

* against main `a4caccefe`: **13** `(path,blob)` pairs main's history never held
* against main `ae78abb285`: **0**

Main took that work in this window — `f26a5ccd9 Merge remote-tracking branch
'origin/fix/jwire2-hygiene-wiring' into land/one-assembled`. The row's citation,
`.github/PULL_REQUEST_TEMPLATE.md` at sha256 `860199c9d2cd6e17`, is now content main
has held at that path.

**The verdict is NOT flipped on this evidence alone.** This row's own history records
its HEAD moving three times (`ba95320314e` -> `a65d80b34ec` -> `4c77f7f0ae4` ->
`4b1285a1865e`), and a tree measurement decides only what the *judged* head held. The
directory on disk is the thing a deletion would destroy. Re-probing `.121` is the
remaining input and is tracked below.

### Three RECOVER rows whose committed content was already landed before this run

`/home/reyerchu/_v1123`, `/home/reyerchu/_a1456`, `/home/reyerchu/_ld/wt` report 0
unproven pairs under **both** mains, so main advancing changed nothing for them. They
are correctly RECOVER and the deliverable already says why, in each row's own evidence:

* `_v1123` — value is **384 uncommitted working-tree changes**, on no commit; preserved
  as `harvest/rescue-108-v1123-staged`.
* `_a1456` — value is **one uncommitted edit**, on no commit; preserved as
  `harvest/rescue-112-a1456-staged`.
* `_ld/wt` — committed content qualifies as LANDED and was **deliberately not flipped**:
  14 gitignored entries under `benchmark-data/ic/*/clean_run_*/` were never examined,
  and a verdict that authorises deleting unexamined bytes is a manufactured pass. That
  named missing input is what session 8 goes after next.

Nothing was deleted. Nothing was written on any other host.
