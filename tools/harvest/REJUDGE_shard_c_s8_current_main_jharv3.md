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

It was not flipped on that evidence alone — this row's HEAD has moved four times now,
and a tree measurement decides only what the *judged* head held, while the directory on
disk is what a deletion destroys. So `.121` was re-read, read-only through the `.102`
hop:

* HEAD has moved **again**, `4b1285a1865e` -> **`c190bf024bc21567aeeea2d3ed7fbc0d3cc5c716`**
* its **tree is unchanged** at `f8b97313740e04d9adac9776194cd5f3cd609cc5`, so the
  snapshot this row is about is the one session 5 measured — the commit was rebased,
  the content was not touched
* that tree's **6504 files are 6504 pairs main's history holds**; 0 it never held
* **6510 files on disk against 6504 tracked**: the 6 extra are 5 `.pytest_cache/`
  entries (main's own `.gitignore:7`) and the `.git` worktree-pointer file
* `git status --porcelain -uall` reports **0** entries; 0 symlinks; 0 tracked paths
  missing from disk

**Verdict flipped RECOVER -> LANDED.** The 13 files that landed are named in the row,
each attributed to the main commit that took it. One of those commits is
`4b1285a1865e` — the head session 5 found on this disk is now a commit on main.

The independent gate agrees: `bin_jharv3/contract_check.py` reports, against the
pre-flip file, `line 80 (/home/reyerchu/AI_IC_design/wt_jwire2):
.github/PULL_REQUEST_TEMPLATE.md is IDENTICAL to main — RECOVER unsupported`. It found
the same defect from the row's own citation, without the history map.

### A trap this run hit: path-limited `git log` prunes history the full walk shows

12 of the 13 landed blobs attributed immediately. The thirteenth,
`benchmark/CAPTURE_ROUTING.json` blob `44575d4a2a1a`, is **in** the history map yet
`git log -m --raw ae78abb285 -- <path>` shows it nowhere. The blob entered main through
`f26a5ccd9`, a **merge**, and path-limited `git log` without `--full-history` prunes
exactly that. The map is built with no pathspec at all, which is why it has the pair.
A sweep that attributed landings with a path-limited log would report this file as
never landed. It is the same family as the four failure modes in the script header.

### Three RECOVER rows whose committed content was already landed before this run

`/home/reyerchu/_v1123`, `/home/reyerchu/_a1456`, `/home/reyerchu/_ld/wt` report 0
unproven pairs under **both** mains, so main advancing changed nothing for them. They
are correctly RECOVER and the deliverable already says why, in each row's own evidence:

* `_v1123` — value is **384 uncommitted working-tree changes**, on no commit; preserved
  as `harvest/rescue-108-v1123-staged`.
* `_a1456` — value is **one uncommitted edit**, on no commit; preserved as
  `harvest/rescue-112-a1456-staged`.
* `_ld/wt` — committed content qualified as LANDED but was **deliberately not flipped**
  by session 5: gitignored entries under `benchmark-data/ic/*/clean_run_*/` had never
  been examined, and a verdict that authorises deleting unexamined bytes is a
  manufactured pass. **Session 8 supplied that named missing input — see below.**

## Closing the named missing input on `/home/reyerchu/_ld/wt` (host .121)

The hold was specific, so the answer had to be specific: read the bytes.

Measured on `.121` today, read-only: **22061 files on disk, 21786 tracked**, so **405
files exist that no commit holds**. 391 are `__pycache__/` and `.pytest_cache/` (main's
own `.gitignore`, lines 2 and 7), one is the `.git` worktree-pointer file, and **13 are
content**. All 13 were copied off the host and read; each one's `sha256` read back
byte-identical to the `sha256` measured on the host, so the examination is of the bytes
that are actually there.

| file (×2 run dirs unless noted) | what it is |
|---|---|
| `lessons.md` | git blob `b94a8a1847…`, which main's history holds at **8 committed paths** — byte-identical, not similar |
| `ic_expert_db.md` | five design-class lessons, **verbatim** in committed `agents/ic_expert_db/ic_expert_db.json` (checked with `git grep -F` on three distinct sentences; each hits that file and only that file) |
| `ic_expert_agent_handoff.json` | the prompt pack committed `programs/phase1_expert_parse_track.py` assembles from that DB |
| `expert_parse_track.json` | the two runs differ in **4 hunks, every one an embedded absolute run-directory path**; verdict `VACUOUS_PASS`, 0 examined expectations |
| `phase1_planned_consumer_starved_check.json` | the two runs differ in **1 hunk**, the `"project"` path string |
| `cross_layer_reference_check.json` | byte-identical across both runs; `VACUOUS_PASS`, `elements_examined` 0, `findings` `[]` |
| `docs/reports/wave76_skill_md_audit.json` (1 copy) | `skills_with_hits` `[]`, all four totals 0, `files_modified` `[]`, `allowlisted` `[]` |

Not one of the 13 holds a finding, a measurement, or authored prose that is not either
byte-identical to committed content, verbatim-derived from committed content by a
committed program, or empty.

**A count I got wrong mid-run, corrected before it was published.** `find` reports 646
files under those `clean_run_*` directories, and for a while I read that as 646
unexamined files against the 13 `git status` listed — a 50× undercount by the earlier
session. It is not. **712 files under those paths are tracked**: git's ignore rules do
not apply to files already in the index, so almost all of that content is in the tree
and was already covered by the content sweep. Only 12 of them sit outside the index.
The gap between `git status --ignored` (404 entries), `--ignored=matching` (17) and
`find` (646) is that arithmetic, not missing evidence.

The committed side, re-judged against **current** main rather than the stale one: HEAD
unmoved at `31fb2c1efe49`, 21782 files, **0** pairs main never held under either main.
Clean on disk — `git status --porcelain -uall` reports 0 entries, and the 130 index
entries that are not regular files resolve to **126 symlinks and 4 gitlinks, 0 truly
missing**.

**Verdict flipped RECOVER -> LANDED.**

## Closing the provenance gap on the other 108 rows

`contract_check.py` reported, correctly, `110 row(s) do not cite current main
ae78abb28 — a provenance gap, not a wrong verdict`. Every row had in fact been
re-swept, but a reader of **one** row could not see that: the row cited `a4caccefe`
and nothing in it said whether that was stale.

So each row now carries its **own** measurement — file count, pairs main's history
never held under the current main, and the same figure under the old one — rather
than one blanket sentence repeated 108 times. A stamp that says the same thing on
every row proves nothing about any of them.

### A gate I made green by writing text, and then went and earned

One row, `/home/reyerchu/vibe-ic-wt-caravel-slew-drv3`, has **no judged HEAD**: its
value is an untracked file, which lives in no tree, so the sweep could not judge it.
Its first stamp said exactly that — and `contract_check.py` went green on it anyway,
because its staleness check is `if MAIN[:9] not in ev`, a **substring test**. A note
saying "this row was NOT re-judged against ae78abb285" contains the string
`ae78abb28` and therefore satisfies the check.

That is a gate passed by text rather than by measurement, so the note was not left
standing. The row was re-judged the only way an untracked file can be:

* the preserved copy read back through live `harvest/worktree-triage-jharvest`
  (`git show 33d256659929:HANDOFF_TO_GATEKEEPER.drv3.md`) is 9892 bytes at sha256
  `f05e08482acbcffc…`, **the exact value the row cites**
* its git blob `c89f7bcad647` appears at **0** of the 40565 `(path,blob)` pairs main's
  history holds, and main has **never** held a file named `HANDOFF_TO_GATEKEEPER` at
  any path — so the 673 commits took none of it
* re-read on `.112` today: HEAD unmoved at `27523121a3af`, `git status -uall` reports
  exactly one entry, `?? HANDOFF_TO_GATEKEEPER.md`, 9892 bytes, same sha256 — the
  preserved snapshot still matches the disk
* the sibling `…-drv2` still carries a **different** copy (7455 bytes, sha256
  `bcf26247eabbb291…`), so the duplicate claim the original ABANDON rested on is
  still false

**The weakness is worth writing down for whoever runs that gate next:** its freshness
check cannot distinguish a row that was measured against current main from a row that
merely mentions it. It is reported here, not patched — the gate belongs to a peer, and
a substring test is a real check that happens to be satisfiable by prose.

`contract_check.py` now reports `CONTRACT OK` with **no** provenance note and
`landed_since_judging: 0`.

## The two checks a re-judgement does not cover: drift and survivability

A content re-judgement decides what the *judged tree* held. Two things it cannot see
decide whether the verdicts are safe to act on today, and both were measured.

### Drift — all 110 rows re-read on their hosts

`bin_jharv3_s8/drift_probe_s8.sh`, read-only, piped in on stdin, no fetch, nothing
written: 30 rows on `.108` locally, 36 on `.112` and 44 on `.121` through the `.102`
nested-ssh hop. Raw: `raw_drift_all_s8_jharv3.tsv`.

**107 rows unmoved, 3 moved, and all 3 are accounted for:**

| path | verdict | judged | now | |
|---|---|---|---|---|
| `AI_IC_design/wt_jwire2` | LANDED | `4c77f7f0ae43` | `c190bf024bc2` | same tree; re-judged at the live head today |
| `wt-j63x8c` | RECOVER | `3ab7fc723e49` | `bc60e88484c1` | session 7's own drift finding; `bc60e88484c1` is the tip of live `harvest/rescue-108-wt-j63x8c-drifted` |
| `_gf180_priv/wt` | RECOVER | `5240ead2c7ee` | `c130f26f853a` | **new drift**; `c130f26f853a` is the tip of live `refs/heads/next/general-precheck-tells-the-density-gate-the-pdk` |

**Every one of the 36 LANDED rows is clean on disk today** — `mod=0 untracked=0` under
`--untracked-files=all` — and 35 of the 36 are also unmoved. That matters more than the
rest of this document: LANDED is the verdict that authorises a deletion, and a LANDED
directory that has since acquired uncommitted work would be an unrecoverable mistake.
None has.

### Survivability — 110 of 110 judged heads are held by a live origin ref

Recovery instructions rot. This fleet deleted origin branches from 86 heads to 60 in an
hour while shard C was being written, and every `git fetch origin harvest/rescue-…`
line in the file stopped resolving. So containment is re-tested, against what
`git ls-remote` advertises **now** and never against `refs/remotes`, which is a cache
of origin and outlives branches origin has deleted.

`bin_jharv3_s8/containment_live_s8.sh`. Origin advertised **1613 refs**, 1576 of whose
shas are present locally and therefore testable; the set of commits reachable from them
is built once (16603 commits) and membership is a lookup, rather than 173k per-ref
walks. Raw: `raw_containment_s8_jharv3.tsv`.

    110 CONTAINED     0 NOT_HELD_BY_ANY_LIVE_ORIGIN_REF

**The reds, shown rather than asserted.** The gate refuses instead of passing when its
input is degenerate, and it reports the dangerous answer when the dangerous answer is
true:

    $ git commit-tree <main's tree> -m 'negative control'   # a commit no origin ref holds
    /control/not-on-origin  bbc80fef6888  NOT_HELD_BY_ANY_LIVE_ORIGIN_REF

    $ (cd /tmp && containment_live_s8.sh …)                 # no repo, so no refs
    REFUSING: ls-remote advertised only 0 refs
    exit=2

It also validates the reachable set before using it — every live sha must appear in the
set built from it, all of `origin/main` must be inside it, and the null sha must not be —
because an empty set makes every head look lost, and a set built from `refs/remotes`
makes deleted branches look alive.

## The one ABANDON, re-verified at the blob

Shard C has exactly one ABANDON, `/home/reyerchu/_v1126` on `.112`, and it is the only
deletion-bound verdict in the shard that is **not** justified by "main already has it".
So it was re-checked in full rather than stamped.

Against current main the picture is the one session 6 recorded, and 673 commits did not
change it: 21800 files, exactly **one** `(path,blob)` pair main's history has never
held —
`vibe-ic-marketplace/plugins/vibe-ic/programs/gate_host_independence_check.py` at blob
`f8ffb71bfba1`, 45097 bytes. Main has held **thirteen** different blobs at that path and
none of them is this one.

The ABANDON is correct because the twin holds the same bytes — and that is now checked
at the blob, not inferred from tree equality:

* `/home/reyerchu/_i_solo_1126` HEAD `30ca1a916507` holds **the same blob**
  `f8ffb71bfba1` at that same path
* both directories re-read on `.112` today: HEADs unmoved, both trees
  `f5f659f2a22a`, both `mod=0 untracked=0`
* both heads contained by refs origin advertises **now** — this one by
  `harvest/worktree-triage-jharvest`, the twin also by `harvest/rescue-reanchor-3`,
  still among the 13 live `harvest/rescue-reanchor-*` branches

So the exposure session 3 recorded — an ABANDON resting on a single other row — is
still lifted. **The row is preservation-bound, not "already on main":** if both
preservations lapse, that one file is what is lost, and the row now says so in those
words.

## Shard C after session 8

**110 rows — 73 RECOVER, 36 LANDED, 1 ABANDON.** Two rows moved, both RECOVER -> LANDED.
`bin_jharv3/contract_check.py` reports `CONTRACT OK` on the amended file, with
`landed_since_judging: 0`, no provenance note, and the one outstanding contract problem
resolved.

Every row is now judged against `ae78abb285`, every row was re-read on its host today,
and every judged head is held by a ref origin advertises now:

| check | result |
|---|---|
| rows judged against current main | 110 / 110 |
| rows re-read on their host today | 110 / 110 |
| judged heads held by a live origin ref | 110 / 110 |
| LANDED rows clean on disk (`-uall`) | 36 / 36 |
| verdicts that changed | 2 |

Nothing was deleted. Nothing was written on any other host — every probe was piped in on
stdin and every temporary file it made was under `/tmp` on the far host and removed by
the script itself.
