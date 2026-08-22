# Shard C — every worktree on this host decided by CONTENT

agent `jharv3` · host **8HD-6** (192.168.1.108) · 2026-08-22

| | |
|---|---|
| judged against | `origin/main` = **`a00f53f2094812041c8aa6094f27058bc1b14ddd`** — *"ppa(crosslayer): an agent that read the specification beat a tuner that did not…"* `[v1.11.66]`, 2026-08-21 |
| fetched | **first**, once per clone, all four clones, before any verdict — and it changed the answer, see [F] |
| clones on this host | **4 sharing this repository's history** — `vibe-ic` (68 checkouts) · `vibe-ic-shard` (16) · `_jppa_power/tree` (2) · `.claude/plugins/marketplaces/vibe-ic-marketplace` (1) — **plus 2 standalone repositories** with no shared history, judged separately: `/tmp/codex-fixall.m9SimJ/repo` and `gkaudit_mainck`. The shard file's `clone` column therefore holds 6 distinct values, not 4. |
| checkouts decided | **89 / 89** — 0 undetermined |
| verdicts | **59 KEEP · 30 DROP** — as of **2026-08-21T17:45:36Z**; see [L], five of these rows are volatile |
| deleted | **nothing.** No path removed, no worktree pruned, no local branch, HEAD, index or working file touched. The only writes were the four fetches' own remote-tracking ref updates. |

## The shard, and what I could not reach — read this first

The brief names five coordination files on **8HD-4** (`_harv_remaining.tsv`,
`_harv_shard_a/b/c.tsv`, and the file stating the rule). **None is on this host, and 8HD-4 is
not reachable from 8HD-6**: no `/etc/hosts` or DNS entry, no `ssh_config` alias, and
`ListAgents` shows no `jharvest-triage` and no `jharv2` session to ask. So I could take
neither a pre-written shard C nor the rule file. I did not invent either.

What I did is the brief's own fallback, applied honestly: **shard by HOST.** I am the only
agent on 8HD-6, so this host's checkouts are a shard by construction — no second agent can
fetch in these four clones behind me, which is the exact failure the brief says cost the
first 223. I enumerated every checkout here and decided **all 89**, and wrote the membership
out so a coordinator can merge:

- `/home/reyerchu/_harv_shard_c.tsv` — this shard's 89 checkouts, one per line, with verdict
- `/home/reyerchu/_harv_remaining.tsv` — the same enumeration before judging, for the merge

I did **not** write `_harv_shard_a.tsv` or `_harv_shard_b.tsv`. Those must list worktrees on
hosts whose disks I cannot read; writing them would be inventing a split I have no evidence
for. **89 of the 477 are now decided. The rest are on hosts I cannot see, and this report
says nothing about them.**

## [E] The enumeration was wrong the first time, and finding that mattered most

The first pass trusted `git worktree list` and decided 75. **`git worktree list` reports only
REGISTERED worktrees.** A checkout whose registration was pruned still holds its commits and
its files on disk; it is simply invisible. Sweeping the filesystem for `.git` instead found:

- **9 unregistered checkouts** under `jf-63x8-work/` (`base-mml`, `mut-arm`, `revert1`–`6`,
  `revert-b`), all of them `.git`-files pointing into `vibe-ic/.git/worktrees/…`. **All 9 are
  KEEP**, and between them they carry thousands of uncommitted tracked changes.
- **A third clone**, `_jppa_power/tree`, owning 2 worktrees — its `origin/main` had **never
  been fetched at all**, so it was judging against nothing.
- **A fourth clone**, the plugin marketplace checkout under `.claude/`.
- **2 checkouts with no shared history at all**, decided separately below.

**14 checkouts, 11 of them KEEP, were invisible to the enumeration the first pass trusted.**
If this shard had shipped at 75, those 11 would have read as "not present" rather than KEEP.

## The rule I applied

> A checkout is **KEEP** if it holds content that is not on main. It is **DROP** only if
> every file it is responsible for is byte-identical to current `origin/main`.

Per checkout:

1. `own` = the files it is responsible for — `git diff --name-only <base> <HEAD>`.
2. `differ` = of those, the ones whose **bytes are not main's** — `own` intersected with
   `git diff --name-only origin/main <HEAD>`. A git blob OID is a content hash over the exact
   bytes, so this is `sha256sum` of `git show origin/main:<path>` against `sha256sum` of
   `git show <HEAD>:<path>`, computed once instead of once per file. Every KEEP row below
   re-checks its named example with **real `sha256sum`**, so any line here can be verified by
   hand.
3. **DROP requires `differ == 0`.** Nothing else drops.
4. Uncommitted state is judged separately, and can only ever turn a DROP into a KEEP.

**merge-base scopes step 1; it never decides.** No verdict here reads ahead/behind, commit
count, ancestry, `git status`, or any merge's report of itself. That is the whole point: this
repository lands by **squash**, so every one of these branches reads as "ahead" of main, and
30 are fully landed anyway. Three DROPs are exactly that trap — `_jppa_fixtures/tree`
(**32 files touched, all 32 byte-identical to main**), `_g360` (3 files), `_gsplit` (1 file).
Judged by ancestry all three look like live work.

**[F] The fetch changed the answer, and it is measurable.** `_jppa_power/tree` had **no
`origin/main` at all** before this run. `vibe-ic-shard` was at `867de4289` (`v1.11.18`,
2026-08-21 05:50) and moved to `a00f53f2094` (`v1.11.66`) — **52 commits**; its 16 checkouts
would otherwise have been judged against a main 52 landings old. Each clone was fetched
**once**, before any checkout in it was read.

## [D] "Absent from main" was overstating five KEEPs, and that is now fixed

The strongest KEEP evidence is a file main does not have. But main sometimes **deletes** a
file — and then a branch that predates the removal shows the same "absent from main" signal
while holding nothing new. Auditing every KEEP example against
`git log --diff-filter=D origin/main -- <path>` found **5 of them resting on a path main had
deliberately deleted** (`benchmark-data/ic/spm/SOURCE_MANIFEST.md` removed by `75776dbbb`,
`benchmark-data/ic/INDEX.md` by `c5d7f2d00`, `.image-version-ignore` by `752a8baaf`, …).

No verdict changed — every one of those rows had other genuinely novel files — but the
*evidence* did. Example selection now prefers a path main **never had**, and every
"absent from main entirely" claim in the table below has been re-checked against that.

## The classes

| class | count | meaning |
|---|--:|---|
| `KEEP_NOVEL_CONTENT` | 54 | ≥1 file differs from main and its patch does **not** reverse-apply onto main |
| `KEEP_SUPERSEDED_CONTENT_DIFFERS` | 1 | files differ, but every one reverse-applies onto main: work looks landed, only main's drift remains |
| `KEEP_UNCOMMITTED_*` | 3 | committed content matches main; the work is in the index or on disk, on **no ref at all** |
| `KEEP_NOVEL_SEPARATE_HISTORY` | 1 | shares no history with any clone, but its base tree is one main published, so it scopes exactly |
| `DROP_ALL_FILES_MATCH` | 28 | every file it owns is byte-identical to main |
| `DROP_…_TREE_EMPTIED` | 1 | content matches main **and** the working files are gone from disk |
| `DROP_TREE_IS_A_TREE_MAIN_PUBLISHED` | 1 | its entire tree OID is a tree main published — a byte-verbatim snapshot |

`KEEP_SUPERSEDED` is reported **KEEP, not DROP**, deliberately. Reverse-apply is good evidence
that work reached main, but it is *inference about a patch*, not the byte equality the rule
asks for — and against a drifted main it fails for content that did land, so it is unreliable
in both directions. The rule's DROP test is "every file matched"; these files do not match.
**A wrong DROP is unrecoverable, so uncertain cases are labelled and kept, never quietly
dropped.**

## Every DROP was checked twice, by two different routes

No drop rests on the pass that produced it. All 32 checkouts whose *committed* content the
first pass called landed were re-derived by `verify_drops.sh`, which shares no code with
`judge.sh`:

- **Route A — it touched files (3).** Hash **both sides of every touched file with real
  `sha256sum`** and require every pair to match.
  `_jppa_fixtures/tree` **32/32** · `_g360` **3/3** · `_gsplit` **1/1**.
- **Route B — it touched nothing (29).** Require its whole tree OID to equal the tree OID of a
  commit `origin/main` actually published — so the tree is a *verbatim snapshot of a state
  main went through*, a statement about bytes, not about ancestry.

**32 checked, 32 CONFIRMED, 0 disagreements.** Three of those 32 are still reported KEEP
above, because their committed content is landed but their *uncommitted* content is not —
that is the only way a DROP became a KEEP here, never the reverse.

## [L] These verdicts are a SNAPSHOT, and this host is NOT quiescent

This is the finding that changes how the list must be used. It was caught only because the
whole harvest was re-run end to end as a self-test instead of being trusted.

**Another agent is working in these trees right now.** Over roughly forty minutes of
re-checking, six checkouts moved, one of them twice:

| checkout | observed | consequence |
|---|---|---|
| `wt/b68-base-hy` | `a00f53f20` → `8db6669bb` (3 new commits, 10 files absent from main, *"the evidence logs were never committed"*) → back to `a00f53f20` | **DROP → KEEP → DROP** |
| `wt/b68-head-hy`, `wt/b68-head-py` | `3c3c51aee` → `37769d59e`, last commit **11 minutes** before this line was written | KEEP → KEEP |
| `wt-j63x8c` | `1199bdff4` → `3ab7fc723` | KEEP → KEEP |

**A DROP became a KEEP and then a DROP again while the report was being written.** Every row
above is correct as of the timestamp in the header, and re-judging further is a race I cannot
win — so instead the volatile set is named, and a guard ships with the list.

> **A verdict is true only as of the HEAD it was taken against.** Acting on a stale DROP is
> precisely the unrecoverable outcome this whole rule exists to prevent.

**6 rows are marked `volatile=yes` in the shard file** — the five `/home/reyerchu/wt/b68-*`
checkouts and `wt-j63x8c`. Do not act on those six on the strength of this document alone. The other
83 were byte-stable across every pass.

**The flag held predictively.** After it was assigned, the guard was run again and caught a
seventh movement — `wt/b68-head-vfy`, `3c3c51aee` → `2794fb1d2`. It is inside the declared
volatile set, and its verdict (KEEP) does not change. Every movement observed during this
entire run fell within those 6 rows; the other 83 never moved once.

Before anyone deletes anything, on any host:

```bash
bin/recheck_drift.sh ~/_harv_shard_c.tsv    # exit 0 only if every HEAD is where it was judged
```

It re-reads each checkout's current HEAD, compares it to the one recorded in the file, and
**exits non-zero naming every one that moved.** It is not advisory: run it, and if it refuses,
re-judge the rows it names rather than overriding it.

## What is on no ref at all — the most losable work in the shard

Committed content identical to main, so a verdict reading commits alone drops every one:

| checkout | what is loose |
|---|---|
| `/home/reyerchu/_v1123` | the entire tree of `bd2a9a1c` (= `refs/pr/1123`) **staged in the index**: 224 blobs differ from main, 17 paths absent from it. An index is not a ref. |
| `/home/reyerchu/_tim_priv/wt-jsetup-base` | 2 **untracked** files — `declared_clock_period.py` and its test, both differing from main's copies. No commit, no branch, no reflog. |
| `/tmp/regen_4e51c4853` | 1 modified tracked file, `programs/tests/matrix_63x8/README.md` |

And the nine checkouts the enumeration nearly missed carry, on top of their KEEP verdicts,
uncommitted work measured against `origin/main` file by file:

| checkout | differs from main | absent from main | deletions on disk |
|---|--:|--:|--:|
| `jf-63x8-work/base-mml` | 120 | **10** | 1518 |
| `jf-63x8-work/mut-arm` | 118 | **10** | 1518 |
| `jf-63x8-work/revert1`…`revert6` | 30–35 each | 0 | 12–15 each |
| `jf-63x8-work/revert-b` | 5 | 0 | 2 |

**A deadline this triage does not control:** 21 of the 89 checkouts live under `/tmp`, which
`/usr/lib/tmpfiles.d/tmp.conf` clears with `D /tmp` **on every boot** — and 8 of those are
KEEP, including `/tmp/codex-fixall.m9SimJ/repo`, whose five commits of gatekeeper work are
reachable from **no clone on this host**. They are on an ext4 disk, so they survive until the
next reboot and not one moment longer.

## Redundant copies — and one that stopped being one

Byte-identical checkouts, same HEAD *and* same tree OID, so keeping one of each loses nothing:

| tree | checkouts | note |
|---|---|---|
| `a30e850bd` (HEAD `5935ae020`) | `_green` · `_gsw_green` | stable across every pass |
| `473bed578` (HEAD `37769d59e`) | `wt/b68-head-hy` · `wt/b68-head-py` | **volatile** — both moved mid-run |
| `a3788ac5a` (HEAD `a00f53f20`) | `wt/b68-base-hy` · `wt/b68-base-py` | **volatile**; that tree *is* `origin/main`'s, which is why both are DROP |

**An earlier version of this report said `b68-head-hy`, `-py` and `-vfy` were three identical
copies. That is no longer true**: `hy` and `py` advanced to `37769d59e` and `vfy` stayed at
`3c3c51aee`, so `vfy` is now a distinct tree and must be kept on its own merits. It is the
clearest illustration of [L] — even a statement about two trees being equal has a shelf life
on a host someone else is working on.

I am not naming which copy of an identical pair to keep: they are identical, so that is a
preference, not a measurement, and the brief reserves the action to the owner.

## What was ruled OUT of scope, and on what evidence

The filesystem sweep found **993 checkouts**. Only 89 are checkouts of this repository. The
rest were excluded by measurement, not by their names:

| excluded | count | evidence |
|---|--:|---|
| pytest fixture repos under `/tmp/pytest-of-reyerchu/garbage-…` | 33 | they carry a `vibe-ic` plugin manifest, so they were checked: **0 of 33 share a single object with the real clone.** Synthetic trees the suite builds and throws away ("base commit, deliberately untagged"). |
| repos with no `vibe-ic` content at HEAD | 740 | no `vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json` |
| paths that are not repositories | 136 | `git rev-parse` fails |

The 33 fixtures are the ones worth naming: they *look* like this repository and are not it,
and only the shared-object test separates them.

## Two known limits of this method

- **Renames.** The comparison is path-by-path, so a file main kept under a *new* path reads as
  "absent from main" and the checkout is KEPT. This can only ever produce an over-KEEP, never
  a wrong DROP, so it is left conservative rather than guessed at.
- **`KEEP_NOVEL_SEPARATE_HISTORY` magnitude.** For a checkout sharing no history, `own` exists
  only because its base tree happened to be one main published. Had it not been, the honest
  output would have been UNDETERMINED with that as the named missing input — not a verdict.

## Every checkout, one line each

`own` = files it is responsible for · `differ` = of those, the ones whose bytes are not
main's. Every sha256 is the first 16 hex of `sha256sum` over `git show <rev>:<path>`.

| checkout | verdict | class | evidence |
|---|---|---|---|
| `/home/reyerchu/vibe-ic` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_issue1469_private_helper_import_resolves.py` sha256 `94ce4a97dbd8be40` (227 lines) vs main `ABSENT_ON_MAIN` (0 lines) — 4 of 4 differing files are novel. **Plus 141 untracked files on disk** (new `programs/*.py`, `tools/ci/*`, upstream assessments), committed nowhere. |
| `/home/reyerchu/_L1347` | **KEEP** | `KEEP_SUPERSEDED_CONTENT_DIFFERS` | `vibe-ic-marketplace/plugins/vibe-ic/programs/checker_execution_wiring_audit.py` sha256 `f91f3fd1934b1d76` (1209 lines) vs main `396342e59c0c9398` (1242 lines). checker_execution_wiring_audit.py — a checker only its own TEST runs has — but every one of its 2 differing files reverse-applies onto main, so the work looks already landed and only main's later drift remains. Kept because the bytes differ; a wrong DROP is unrecoverable. |
| `/home/reyerchu/_cpath_priv/base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_cpath_priv/tree` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/PROGRAM_INVENTORY.json` sha256 `97a3cdea3d296f2b` (52 lines) vs main `7c6adee28bc9e00f` (52 lines).  (4 of 5 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_dens_priv/wt-jdrc1177` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/die_density_fill_gen.py` sha256 `6314f66aebc76ca4` (673 lines) vs main `67daa7281b615287` (679 lines). die_density_fill_gen.py — DIE-WIDE dummy fill, by the PDK's OWN generator. (2 of 3 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_dens_priv/wt-jdrc1177-base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_fix11` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/ci/protected_landing_transition.json` sha256 `02bffed72931d54e` (1 lines) vs main `cc2abdd9d01beeb5` (1 lines).  (5 of 7 differing files are novel; 2 already reverse-apply onto main.) |
| `/home/reyerchu/_fix11_base` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/ci/protected_landing_transition.json` sha256 `53b6ca11c79b7884` (1 lines) vs main `cc2abdd9d01beeb5` (1 lines).  (6 of 7 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_g360` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched 3 files and **all 3 are byte-identical to `origin/main`** — the squash case: it still reads as "ahead", and its content is entirely landed. |
| `/home/reyerchu/_gf180b_priv/tree` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_gk1347` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/checker_execution_wiring_audit.py` sha256 `57ec7afa4206f4ac` (984 lines) vs main `396342e59c0c9398` (1242 lines). checker_execution_wiring_audit.py — a checker only its own TEST runs has |
| `/home/reyerchu/_gk1734` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py` sha256 `c5debb1c90f0549a` (2181 lines) vs main `dfe829dc07845130` (1990 lines). ci_harness_timeout_ceiling_check.py — a test's own subprocess timeout must |
| `/home/reyerchu/_gk1744` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tapeout_readiness_check.py` sha256 `f2c0099291a321f9` (908 lines) vs main `96053096837fd7f2` (1054 lines). tapeout_readiness_check.py — the EXTERNAL refusal interface, pointed at a (4 of 6 differing files are novel; 2 already reverse-apply onto main.) |
| `/home/reyerchu/_gkpr1759` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/_eda_image.py` sha256 `ff15868e7afb5aed` (163 lines) vs main `d6d26d5ddb590f92` (574 lines). Which vibeic-eda image to run — asked, not remembered. (9 of 12 differing files are novel; 3 already reverse-apply onto main.) |
| `/home/reyerchu/_green` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_issue1424_landing_gate_reaches_every_test_tree.py` sha256 `05c15132ea89e055` (344 lines) vs main `23b908823c086ac8` (363 lines). vibe-ic#1424 — a test tree can be wired into every runner a human uses and (2 of 3 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_gsplit` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched 1 files and **all 1 are byte-identical to `origin/main`** — the squash case: it still reads as "ahead", and its content is entirely landed. |
| `/home/reyerchu/_gsw_green` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_issue1424_landing_gate_reaches_every_test_tree.py` sha256 `05c15132ea89e055` (344 lines) vs main `23b908823c086ac8` (363 lines). vibe-ic#1424 — a test tree can be wired into every runner a human uses and (2 of 3 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_i1348` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_issue1348_census_table_partitions.py` is **absent from main entirely** (sha256 `0906a239160f5477`, 270 lines). A census row may not publish fewer cells than the dimension it names. |
| `/home/reyerchu/_i1410` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py` sha256 `f281b9c0998fc6fe` (1870 lines) vs main `7a4f12cb72ffd7a4` (2029 lines). test_matrix_mutation_ledger.py — the STANDING gate: a cell may not be called (1 of 2 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_i1704` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/step_internal_fail_bubble_up_baseline.json` sha256 `c5976a40b802db4c` (32 lines) vs main `e3f2e375938a359a` (98 lines).  (2 of 3 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_jcapture` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `d4dbe3d3a7f96779`, 559 lines). DISTIL — six captured recoveries into the program layer |
| `/home/reyerchu/_jfeas` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `dfc38eff8bab1105`, 488 lines). RESULT — the feasibility gate can answer (6 of 7 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_jfeas_base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_jppa_closure/base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_jppa_closure/tree` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/ppa_closure_run.py` sha256 `399d6ba4e8545aeb` (253 lines) vs main `5f7ce8ccb6a7b0b2` (256 lines). ppa_closure_run.py — execute one declared closed_loop edge, or report that |
| `/home/reyerchu/_jppa_fixtures/base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_jppa_fixtures/tree` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched 32 files and **all 32 are byte-identical to `origin/main`** — the squash case: it still reads as "ahead", and its content is entirely landed. |
| `/home/reyerchu/_pg_1523v` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/ci/repo_hygiene_gates.sh` sha256 `33143ad3eebfcea2` (1117 lines) vs main `c311b8d27416b22c` (1653 lines). tools/ci/repo_hygiene_gates.sh — the repo-wide invariant gates, in ONE place. (57 of 66 differing files are novel; 6 already reverse-apply onto main.) |
| `/home/reyerchu/_pg_1613` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/gatekeeper-verify-merge.sh` sha256 `afd1347dd1103267` (659 lines) vs main `baa0fb6b3f0c452f` (1420 lines). gatekeeper-verify-merge.sh — put the landing gates ON THE PATH THAT LANDS CODE. (7 of 15 differing files are novel; 8 already reverse-apply onto main.) |
| `/home/reyerchu/_pg_IDX` | **KEEP** | `KEEP_NOVEL_CONTENT` | `docs/ENGINEERING_METRICS.md` is **absent from main entirely** (sha256 `6bc1f2803596ed3d`, 24 lines). Engineering Metrics (69 of 83 differing files are novel; 11 already reverse-apply onto main.) |
| `/home/reyerchu/_pg_VD` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml` sha256 `4144b51acdc0ecb0` (4955 lines) vs main `5f691984067c906f` (6320 lines). Vibe-IC Phase 1+2+3 Canonical Flow Definition (30 of 36 differing files are novel; 2 already reverse-apply onto main.) |
| `/home/reyerchu/_pg_W2` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/bundled_attribution_notice_check.py` sha256 `245abdf88812a2c3` (304 lines) vs main `4b5dd5ca5694a5fe` (319 lines). bundled_attribution_notice_check.py — every BUNDLED third-party work must be |
| `/home/reyerchu/_pg_bigbatch` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/phase1_engine/tests/test_typical_scaffolds_retired.py` sha256 `efa8a05b7462ad29` (393 lines) vs main `f37f52f77e11b2b6` (475 lines). ORGANIC #493 — the `typical_scaffolds` mechanism is RETIRED. (141 of 164 differing files are novel; 19 already reverse-apply onto main.) |
| `/home/reyerchu/_pg_bo` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_ledger.py` sha256 `912b1e6931811e48` (1113 lines) vs main `20add5c62b60ea96` (1374 lines). Meta-test for the `matrix_63x8` shared substrate. |
| `/home/reyerchu/_pg_d8` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_d8_missing_caught.py` sha256 `ffb118dbee575928` (1432 lines) vs main `18ab25c922a0a888` (2446 lines). DIMENSION 8 of the 63x8 matrix — ``missing_caught``. |
| `/home/reyerchu/_spad` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/pad_ring_check.py` sha256 `f60642c33d9ad674` (537 lines) vs main `4e71eb29cf20dc1b` (547 lines). pad_ring_check — step 15.5ic's gate: the pad ring is re-measured from the |
| `/home/reyerchu/_spmfinal_8HD-6` | **KEEP** | `KEEP_NOVEL_CONTENT` | `docs/FOUR_FIXES_COMBINED_RUN.md` is **absent from main entirely** (sha256 `96a287debf13e617`, 224 lines). All four fixes ON, in one run — what the flow produced, and where it still stops |
| `/home/reyerchu/_tim_priv/wt-jsetup-base` | **KEEP** | `KEEP_UNCOMMITTED_UNTRACKED` | Committed content matches main exactly (HEAD is an ancestor). Two UNTRACKED files sit on disk, both on paths that exist on main with different bytes: `declared_clock_period.py` and `tests/test_declared_clock_period_table.py`. Untracked means no commit, no branch, no ref — this is the most losable state in the shard. |
| `/home/reyerchu/_tim_priv/wt-jsetup-timing` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/declared_clock_period.py` sha256 `99e27dc51724e874` (399 lines) vs main `f61827b78cb9bb20` (462 lines). declared_clock_period.py — read the clock period the DESIGN declares for the (3 of 4 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/_v1123` | **KEEP** | `KEEP_UNCOMMITTED_STAGED_TREE` | HEAD is an ancestor of main and holds nothing, but the INDEX holds the whole tree of `bd2a9a1c` (= `refs/pr/1123`): 224 staged blobs differ from main and 17 paths are absent from main. Of PR-1123's own 5 files, all 5 differ from main by sha256 — e.g. `tool_diagnostic_id_gate.py` pr1123=`1d9d24e3cb6e1549` (752 lines) vs main=`1f501b82ff6be19c` (1102 lines). Main carries a LATER version of the same gate, so most of this is superseded — but it was never committed, so nothing here is recoverable from any ref if the tree goes. |
| `/home/reyerchu/jf-63x8-work/basejm9` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/wt-jf63x8b` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `92c2b26c7dcc97b3`, 194 lines). Producer identity for the fill and antenna reports (#1119 A3_CROSS_DESIGN) (1 of 3 differing files are novel; 2 already reverse-apply onto main.) |
| `/home/reyerchu/wt-jfindings-63x8` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/wt-jm9` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `5072ef58ce662956`, 581 lines). The ninth dimension — `verdict_consumed` |
| `/home/reyerchu/wt-jw1-tapeout` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/tapeout_readiness_check.py` sha256 `d8cdce8748357606` (1554 lines) vs main `96053096837fd7f2` (1054 lines). tapeout_readiness_check.py — the EXTERNAL refusal interface, pointed at a |
| `/home/reyerchu/wt-jw2-extract-err` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/magic_extract_illegal_overlap_check.py` is **absent from main entirely** (sha256 `38ce45d55a3ccae3`, 638 lines). magic_extract_illegal_overlap_check.py — read the EXTRACTOR'S ERROR CHANNEL. |
| `/home/reyerchu/wt-jw2-scratch-revert` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/magic_extract_illegal_overlap_check.py` is **absent from main entirely** (sha256 `2aa571f93614acd6`, 618 lines). magic_extract_illegal_overlap_check.py — read the EXTRACTOR'S ERROR CHANNEL. |
| `/home/reyerchu/wt-main62` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/claude-1000/-home-reyerchu-vibe-ic/0144f922-cbe4-48a4-937e-a5e723ca0cec/scratchpad/wt-base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/claude-1000/-home-reyerchu-vibe-ic/0144f922-cbe4-48a4-937e-a5e723ca0cec/scratchpad/wt-ppa` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `56d44ca4e833a042`, 339 lines). RESULT — wiring the PPA stack, and the one blocking clause that could not go red (2 of 5 differing files are novel; 3 already reverse-apply onto main.) |
| `/tmp/claude-1000/-home-reyerchu-vibe-ic/4dda6029-53c1-403d-a352-47be4c3a1519/scratchpad/wt` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/emitted_script_portability_check.py` sha256 `c85a400a6c229517` (219 lines) vs main `7061d39cfbbd30b6` (226 lines). An emitted analysis script that hard-codes the directory it was emitted in |
| `/tmp/claude-1000/-home-reyerchu-vibe-ic/4dda6029-53c1-403d-a352-47be4c3a1519/scratchpad/wt2` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `dfc38eff8bab1105`, 488 lines). RESULT — the feasibility gate can answer (19 of 22 differing files are novel; 3 already reverse-apply onto main.) |
| `/tmp/claude-1000/-home-reyerchu-vibe-ic/4dda6029-53c1-403d-a352-47be4c3a1519/scratchpad/wt3` | **KEEP** | `KEEP_NOVEL_CONTENT` | `jm9/RESULT.md` is **absent from main entirely** (sha256 `10f888abf29f5526`, 177 lines). The ninth dimension — `verdict_consumed` (6 of 7 differing files are novel; 1 already reverse-apply onto main.) |
| `/home/reyerchu/vibe-ic-shard` | **DROP** | `DROP_ALL_FILES_MATCH_TREE_EMPTIED` | **Clone root, not a plain worktree** — its `.git` owns the 16 `/tmp/shard_*` and `/tmp/regen_*` worktrees below and their objects. Its committed content matches main, and its 21951 status lines are ALL `D`: the working files were deleted from disk, so there is nothing in the tree to recover. Dropping the *content* is right; deleting the *directory* would take the object store with it. |
| `/tmp/regen_36db60639` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/regen_4e51c4853` | **KEEP** | `KEEP_UNCOMMITTED_MODIFIED` | Committed content matches main. One tracked file is modified on disk and differs from main: `programs/tests/matrix_63x8/README.md` (7 lines changed). Small, but it is not on main and not committed anywhere. |
| `/tmp/shard_2efa6af35be69b409bfe9c95026e5c0a03ba56bf_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_36db60639da89dd18d116363049c9c23bb05f259_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_3850b444c5654f66f4d6d9a3df3f3c03bde2e877_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_6a092da303c282cf9bab4fdfe48d0b0b985c3dce_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_772c31dcb41a1625bf1c69832628722958752cb9_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_8172cb0b675051e6e8122a5cc6a3e0dc9ebf64c6_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_9a6c0f0b034ea9d73bc4bc6c661aae7b87fa6f0d_1` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/agents/benchmark-agent.md` sha256 `a31a8aa55bf723fe` (466 lines) vs main `01cae9e9f1595214` (467 lines). name: benchmark-agent |
| `/tmp/shard_b486b862c7a0eb1eb4354b7b6bd4c8cf7dea5740_1` | **KEEP** | `KEEP_NOVEL_CONTENT` | `tools/ci/repo_hygiene_gates.sh` sha256 `7e29d348a0b3abb7` (1269 lines) vs main `c311b8d27416b22c` (1653 lines). tools/ci/repo_hygiene_gates.sh — the repo-wide invariant gates, in ONE place. (16 of 20 differing files are novel; 4 already reverse-apply onto main.) |
| `/tmp/shard_c5d7f2d00e1df23c35a8e289bc1dc3d29b62eee9_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_c8c2ab0f750efe97b5804f1bf41c279d28e4d2e5_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_e20d37fd49abd4775ddd7b32450c9226847f91cb_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/shard_ee849c19e4208b0c2e22795b9a02a5d08210c270_1` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/tmp/sp_ee849c19e` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/.claude/plugins/marketplaces/vibe-ic-marketplace` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/jf-63x8-work/base-mml` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `e7ef3e520f0ffaad`, 671 lines). The 63x8 matrix family on main: 54 red test IDs, driven to 12 |
| `/home/reyerchu/jf-63x8-work/mut-arm` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `e7ef3e520f0ffaad`, 671 lines). The 63x8 matrix family on main: 54 red test IDs, driven to 12 |
| `/home/reyerchu/jf-63x8-work/revert1` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert2` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert3` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert4` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert5` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert6` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/adversarial_agent.py` sha256 `c0f3170ae7b18761` (770 lines) vs main `b2836fc6d8032b4d` (786 lines). adversarial_agent.py — a role whose objective is to make PASS a lie. #1119. |
| `/home/reyerchu/jf-63x8-work/revert-b` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `92c2b26c7dcc97b3`, 194 lines). Producer identity for the fill and antenna reports (#1119 A3_CROSS_DESIGN) (1 of 3 differing files are novel; 2 already reverse-apply onto main.) |
| `/home/reyerchu/_jppa_power/base` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/_jppa_power/tree` | **KEEP** | `KEEP_NOVEL_CONTENT` | `vibe-ic-marketplace/plugins/vibe-ic/programs/_ppa/power.py` sha256 `b5333808ce223230` (909 lines) vs main `8b9b0b186a5b7d74` (935 lines). mean anything: WHERE THE ACTIVITY CAME FROM. |
| `/home/reyerchu/wt/b68-base-hy` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/wt/b68-base-py` | **DROP** | `DROP_ALL_FILES_MATCH` | Branch touched no file relative to main; every path in its tree that it owns is byte-identical to `origin/main`. Nothing in it is not on main. |
| `/home/reyerchu/wt/b68-head-hy` | **KEEP** | `KEEP_NOVEL_CONTENT` | `docs/capture/2026-08-21-jcap-chip/candidates/bucket_A_programs_phase3_one_shot_runner_rule_sketches.py` is **absent from main entirely** (sha256 `4fe9a9a4ef3aeca2`, 90 lines). Bucket A — program-rule sketches for programs/phase3_one_shot_runner.py |
| `/home/reyerchu/wt/b68-head-py` | **KEEP** | `KEEP_NOVEL_CONTENT` | `docs/capture/2026-08-21-jcap-chip/candidates/bucket_A_programs_phase3_one_shot_runner_rule_sketches.py` is **absent from main entirely** (sha256 `4fe9a9a4ef3aeca2`, 90 lines). Bucket A — program-rule sketches for programs/phase3_one_shot_runner.py |
| `/home/reyerchu/wt/b68-head-vfy` | **KEEP** | `KEEP_NOVEL_CONTENT` | `docs/capture/2026-08-21-jcap-chip/candidates/bucket_A_programs_phase3_one_shot_runner_rule_sketches.py` is **absent from main entirely** (sha256 `4fe9a9a4ef3aeca2`, 90 lines). Bucket A — program-rule sketches for programs/phase3_one_shot_runner.py |
| `/home/reyerchu/wt-j63x8c` | **KEEP** | `KEEP_NOVEL_CONTENT` | `RESULT.md` is **absent from main entirely** (sha256 `e7ef3e520f0ffaad`, 671 lines). The 63x8 matrix family on main: 54 red test IDs, driven to 12 |
| `/tmp/codex-fixall.m9SimJ/repo` | **KEEP** | `KEEP_NOVEL_SEPARATE_HISTORY` | Shares no history with any clone, but its base commit `7e73283` has tree `dad63c660` — **a tree `origin/main` published**, at `116bcb5a8` (2026-08-18) — so its 5 later commits scope exactly: **41 files owned, 23 already byte-identical to main, 18 differing, 15 of them novel.** e.g. `programs/ci_harness_timeout_ceiling_check.py` sha256 `2ca31e0f0cc2b6fb` (1761 lines) vs main `dfe829dc07845130` (1990 lines). Plus 3 uncommitted. Five commits of gatekeeper work reachable from **no clone on this host**, sitting under `/tmp`. |
| `/home/reyerchu/gkaudit_mainck` | **DROP** | `DROP_TREE_IS_A_TREE_MAIN_PUBLISHED` | Shares no history with any clone, but its whole-tree OID `86df13076` **is a tree `origin/main` published** — commit `74ac9fa78`, 2026-08-19. A git tree OID is a content hash, so this is a byte-verbatim snapshot of main, exactly as its one commit message ("origin/main snapshot") claims. Its 168 files "differing" from today's main are main's drift since 08-19, and its 11 files "absent from main" were **deleted from main** by `752a8baaf` and `41baeadad`. Nothing in it is not on main. |

## What this run did not do, stated plainly

- **Deleted nothing.** No path removed, no worktree pruned, no local branch, HEAD, index or
  working file touched, no `git worktree prune`. Every checkout was read through a temp
  index; no checkout was created. The only ref writes on this host were the fetches' own
  remote-tracking updates. The verdicts above are the decision; the action is the owner's.
- **Did not decide the rest of the 477.** They are on hosts this agent cannot reach — and
  two of those hosts are up and refusing this host's key.
- **Did not write `_harv_shard_a.tsv` or `_harv_shard_b.tsv`,** because writing them would
  mean inventing a split over disks I cannot read.
- **Did not run any test, gate, or docker image.** This triage needed none, so none was run.
- **Did not keep chasing the volatile six.** Re-judging a tree another agent is committing to
  is a race, not a measurement. They are named, timestamped, and shipped with a guard.

### The bugs this pipeline had, and how each was caught

| # | bug | how it was caught | cost if shipped |
|--:|---|---|---|
| 1 | `git worktree list` shows only **registered** worktrees; 14 checkouts here are not registered | swept the filesystem for `.git` instead of trusting the enumeration | 11 KEEPs would have read as "not present" |
| 2 | `IFS=$'\t' read` folds runs of tabs, so an empty field shifts every later column left | 8 rows named a *commit subject* as the differing file, hashed to `e3b0c44298fc1c14` — the sha256 of nothing | 8 rows of nonsense evidence |
| 3 | "absent from main" also fires on paths main **deliberately deleted** | audited every example against `git log --diff-filter=D` | 5 KEEPs justified by stale content |
| 4 | `git ls-tree --format=` is unsupported here; the rename check ran on an **empty inventory** and reported a clean pass | added a guard refusing to conclude on an implausibly small inventory, and printed the rows/files actually measured | a vacuous "0 renames" presented as proof |
| 5 | rename detection rewrites the names `--name-only` reports, which is the list `differ` is built from | re-decided every DROP with `--no-renames` | unknown; 0 as it turned out |
| 6 | gitlinks cannot be hashed by `git show`, so both sides read as empty and compare equal | inventoried all 100 gitlinks and checked for populated submodule trees | a submodule-only difference called identical |
| 7 | **verdicts go stale: this host is live** | re-ran the whole harvest end to end and diffed it against the first pass | **a DROP that had become a KEEP** — see [L] |
| 8 | "these three trees are identical" also goes stale | re-read the tree OIDs after the churn | one tree deleted as a duplicate of two that had moved on without it |
| 9 | the report's own hand-written counts drifted from its data | `bin/audit_report.sh` checks every number in the prose against the TSV | "12 of them KEEP" where the data said **11**, plus two counts stale after a re-derivation |
| 10 | two SHIPPED scripts hardcoded the `/tmp` scratchpad a reboot clears, and would have emitted an **empty file** rather than failing | checked the handoff for durability instead of assuming it | the next agent runs `report.sh`, gets 0 rows, and reads it as "nothing to harvest" |
| 11 | the handoff script printed a plain `DROP` for a tree whose committed content is landed but whose **index or working tree holds work on no ref** — the caveat was only a footnote | reconciled a fresh end-to-end run against the shipped derivation; the only delta was exactly those rows | the next agent deletes `_v1123`, which holds **PR-1123's entire staged tree**, on the strength of a row that says DROP |

Bug 11 is now structural, not advisory: the script emits **`DROP_PENDING_DIRTY_CHECK`**
for any DROP with uncommitted state and names the rows on stderr. On this host it fires on 4
of them, `_v1123` among them. A verdict that needs a second look should say so in the verdict
column, not in a footnote the next agent may skip.

**One process note, because it happened here and it is the same disease.** The patch that
added that guard silently failed to apply — its anchor text did not match — and the commands
chained after it still printed `syntax OK` and a clean end-to-end run, of the *unpatched*
file. The assertion caught it; the reassuring output around it very nearly buried the catch.
Fix applied: assert first, abort on failure, then **grep the file to prove the change is
actually in it** before running anything that reports success.

Bug 4 is the one worth repeating, and bugs 10 and 11 are it again wearing different clothes:
**a stage that examined nothing and a stage that found nothing print the same thing. Only a
refusal tells them apart.** Every stage now defaults to the persistent copy under
`_harv_priv/` and **exits 2 naming the missing input** rather than producing an empty result. Bug 9 is its sibling: every
count in a document like this is typed by hand at least once, and stays right only until the
data is re-derived underneath it. `bin/audit_report.sh` now re-checks the prose against the
table, and this document passes it with **0 failures**.

## Reproducing this, and taking another host

Everything is under `/home/reyerchu/_harv_priv/` (scripts in `bin/`, raw measurements
alongside), copied off the `/tmp` scratchpad that a reboot would clear.

**To harvest another host, one command:**

```bash
bin/harvest_host.sh <hostname>      # sweep -> scope -> fetch once per clone -> judge -> verify
```

It was run end to end on this host as a self-test; that run is what caught bugs 7 and 8. It
writes `~/_harv_shard_<host>.tsv` and `~/_harv_remaining_<host>.tsv`, deletes nothing, and
creates no checkout. **Run one instance per host and never two against the same clone** —
two agents fetching in one shared clone is what corrupted the first 223 verdicts.

**Before acting on any verdict, on any host:**

```bash
bin/recheck_drift.sh ~/_harv_shard_c.tsv    # exit 0 only if every HEAD is where it was judged
```

The individual stages, if you want them separately:

```bash
bin/find_checkouts.sh                    # filesystem sweep, incl. bare clones
bin/scope.sh          < all              # which are checkouts of THIS repo, on evidence
bin/judge.sh          <clone>            # registered worktrees, read-only, temp index
bin/judge_paths.sh    < paths            # the unregistered ones worktree list cannot see
bin/judge_unrelated.sh <repo>            # a checkout sharing no history with any clone
bin/report.sh ; bin/mkmd.sh              # name an example, re-hash it, render the table
bin/verify_drops.sh                      # second, independent derivation of every DROP
bin/dirty.sh          <checkout>         # uncommitted state vs origin/main, file by file
bin/audit_report.sh <RESULT.md> <tsv>    # does the prose still match the data?
```

`judge.sh` self-tests before it judges: it reverse-applies main's own last landing against a
temp index of main and refuses to run if that does not recognise itself. All four clones
passed.
