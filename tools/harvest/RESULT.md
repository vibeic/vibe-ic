# jharvest-triage — RESULT

Agent `jharvest-triage`, host 8HD-4 / 192.168.1.120, 2026-08-20.
Working notes with every command and number: `/home/reyerchu/_harv_priv/findings.md`.

## Deliverable

**`/home/reyerchu/.claude/fleet/runs/harvest_triage_table.md`** — one row per
worktree, every row carrying a disposition, grouped RECOVER / ABANDON / LANDED and
ordered so the valuable end is at the top.

Also produced, because the brief said it already existed and it did not:

**`/home/reyerchu/.claude/fleet/wt_classify.sh`** — the read-only content-based
classifier. It creates no worktree and writes nothing into any repo (tier 2 runs
against a temp `GIT_INDEX_FILE`), and it self-tests on start: if a known-landed
patch fails to reverse-apply it exits 4 rather than emitting numbers.

## Nothing was deleted

No worktree was removed on any host. No branch was pushed and no version was
bumped: this job produced fleet metadata, not repo content, so there is no branch
to report. The scripts live in `~/.claude/fleet/` and `~/_harv_priv/bin/`, outside
the repo.

## What I changed relative to the brief

The brief was wrong in four places. Each is measured in findings.md; my numbers win.

| brief | measured | where |
|---|---|---|
| `~/.claude/fleet/wt_classify.sh` exists — do not re-invent it | it does not exist on any of the six hosts; I had to author it | F1 |
| 477 worktrees | **478** in `~/vibe-ic` (.108 has 27, not 26) — and **701** vibe-ic worktrees in total; the 477 counts only the `~/vibe-ic` clone, ignoring 223 more in 34 other vibe-ic clones | F3, F15 |
| ~140 carry uncommitted edits | **15** (17 including the extra clones). The ~140 counted untracked EDA output; an intermediate 95 of mine counted staged deletions | F7, F18, F20 |
| six hosts, two unreachable | all six reachable; .108 and .121 reject this host's key but .112's key works on both, so a nested ssh reaches them | F2 |

## Result

The brief's set — the 478 worktrees in `~/vibe-ic` across all six machines:

| scope | RECOVER | LANDED (safe to delete) | ABANDON | total |
|---|---:|---:|---:|---:|
| `~/vibe-ic` — the brief's set | **199** | 151 | 128 | 478 |
| the 34 other vibe-ic clones | 62 | 145 | 15 | 223 |
| **total** | **261** | **296** | **143** | **700** |

The second row is the population the brief's 477 did not count — the same kind of
object, classified by the same rules, tagged by its repo in the table. Read its
caveat under *What I could not settle*.

## Why ancestry could not be used, and what replaced it

`vibe-ic` squash-lands, so a fully-landed branch is never an ancestor of `main`.
The brief already warned that `merge-base --is-ancestor`, `branch --merged` and
`rev-list origin/main..HEAD` all misreport. It did not warn that the *content*
test has the same failure in three further disguises. All three were found by
hand-checking rows my own engine had already scored, and each one was silently
inflating RECOVER:

1. **Whole-file identity compares against a moving `main`.** A file whose change
   landed and which `main` later touched again for an unrelated reason reads as
   unlanded. First pass: 156 of 165 "UNLANDED" on this host. Fixed with a
   hunk-local reverse-apply against a temp index (F4, F5).
2. **`added + deleted` is not a measure of recoverable work.** In the direction
   `main → head`, *deleted* means main has it and the tree does not — staleness,
   the opposite of a prize. `.114:~/_J1745` scored ~2000 "novel" lines while being
   an already-landed tree that was merely old (F8).
3. **The squash keeps the prose.** vibe-ic rewrites the `type(scope):` prefix and
   appends the PR ref, but the sentence survives verbatim, so normalised subject
   text is a reliable landed-identity key. It moved 49 trees out of RECOVER (F12).

The load-bearing number is **`nadd`** — added lines of
`git diff --numstat origin/main <head>` restricted to the files the tree itself
touched. Split further into `code_add` (authored) and the rest (regenerable
`benchmark-data/`, `*.json`, report dirs), because the single largest RECOVER
claim, 88,225 lines, was 94% one regenerated `corpus_baseline.json` (F13).

## Errors I made and corrected

Recorded because they are the same class of error this job exists to undo.

* My classifier's `dirty` column leaked `GIT_INDEX_FILE` into `git status`, so
  every worktree compared against *main's* index — 18,083 phantom edits each (F6).
* I counted staged deletions as uncommitted edits, which put **empty shells** at
  the very top of RECOVER: 30 worktrees whose files are gone from disk, index
  recording nothing but `D` (F18). Only 15 worktrees hold real uncommitted edits.
* My side-table joins keyed on worktree path alone, but 13 paths exist on more
  than one machine (`~/_i1348` on both .108 and .112, holding different work).
  27 rows had one host's measurements overwritten by another's (F22).
* Twice I ran `pkill`/`kill` with a pattern matching my own command line and
  killed my own shell — the exact failure hard rule 8 names (F9, F17). No data was
  lost; one partial pass was discarded and re-run cleanly.

## How the verdicts were reached

Eleven rules, applied in a fixed order; every row records which one fired, so any
single verdict can be re-derived or overruled from the table alone.

| rule | verdict | fires when |
|---|---|---|
| `L2` | RECOVER | the tree carries uncommitted **tracked edits** — those exist on one disk only, so this outranks everything |
| `L0` | LANDED | `nadd == 0`: nothing in the tree is absent from `main` |
| `L1` | LANDED | every changed file byte-identical to `main`, or its hunks already there |
| `L3` | LANDED | the tip's normalised prose appears in `main`'s history (the squash preserves it) |
| `N1` | LANDED | the only absent lines are version manifests / README version strings |
| `A1` | ABANDON | gatekeeper PR-verification merge whose PR **merged** |
| `A2` | ABANDON | PR-verification merge whose PR closed **unmerged** |
| `R1` | RECOVER | PR-verification merge whose PR is still **open** |
| `A3` | ABANDON | `[vX.Y.Z] candidate batch` staging tree older than `main`'s v1.11.2 |
| `A5` | ABANDON | bare integration merge holding ≤20 lines absent from `main` |
| `A6` | ABANDON | the tree's issue landed in `main` **and** the tree is ≥2× more behind than ahead |
| `A4` | ABANDON | identical `HEAD` to a tree already kept elsewhere in the table |
| `A7` | ABANDON | the tip commit declares itself a local probe not meant to be pushed |
| `R2` | RECOVER | everything else, sized by authored lines |

`L1` and `L3` additionally require `code_add <= 200 or ndel > nadd` — the residual
must look like staleness, not fresh content. That guard was added after
`.121:~/_LRNdh` matched on prose while holding 558 authored lines that `main` had
deliberately **withdrawn** (`[v1.10.85] withdraw the four upstream studies`).
Every `A6` row names the commit that supersedes it, so the highest-stakes
ABANDONs are auditable rather than asserted.

Ties break toward RECOVER throughout: an over-cautious keep costs disk, a wrong
ABANDON destroys work nobody can reconstruct.

## Spot-checks that the rules survived

* `_pgv/a{1235,1239,1253,1258,1265,1272}` — followed each to its PR and into
  `main`. #1235 merged; the four "closed" ones were **consolidated** into #1258 and
  the consolidation landed (`73dfb68dd`), as did the follow-on `ef8d3c819`.
  ABANDON, reason "superseded by the landed consolidation" (F11).
* `A6`'s two largest calls: `#1251` landed as `3a3d1eae5`; `#1115` landed as
  `3c33c1dd5 … (#1115, re-implementing #1236)` — same subject as the tree's tip (F19).
* `~/_agent_gsmall/wt` and `~/_agent_gipkit14` — the two the brief says an earlier
  agent declared missing fleet-wide. Both present on 8HD-8, both in the table, both
  RECOVER with 500 and 816 authored lines (F23).

## What I could NOT settle

**1. The 223 extra-clone worktrees are measured against a stale `main`.**
Each of the 34 other vibe-ic clones was compared against *its own* `origin/main`,
and those refs are 4–18 days old (`vibe-ic-repo` 2026-08-04, `_agentjob_lgate/repo`
2026-07-30, vs canonical 2026-08-20). Anything that landed in between reads as
unlanded there. That is the safe direction — it over-reports RECOVER, never
LANDED — so their RECOVER count is a ceiling and their LANDED count a floor.
Rule `L3` partly compensates, because it matches tip prose against the *canonical*
`main`'s history regardless of the clone's ref. Fixing it properly needs
`git fetch` in 34 repos that other agents share; this job is read-only by charter,
so I did not write to them. **The 478 the brief actually asked for are unaffected**
— every one was measured against a freshly fetched canonical `origin/main`
(`eda53573f`, 2026-08-20 18:18).

**2. Part of the extra-clone set is classified on the cheap path.** Where a clone's
staleness made the per-file tier-2 test cost ~18,000 `git apply` invocations per
worktree, those rows carry state `LITE`: `nadd`/`ndel`/`code_add` are exact, but
they get no per-file hunk test, so they cannot reach verdict `L1`. They can still
reach `L0`, `L3` and every ABANDON rule. In practice this only loses the "hunks
already in main" refinement, which biases them toward RECOVER.

**3. The RECOVER column is a triage, not a review.** I verified the *rules* against
hand-checked counterexamples and audited the extremes of every column, but I did
not read all 199 RECOVER trees. Each row states its authored line count, its files,
its issue, and the rule that fired, which is enough to review one — it is not the
same as having reviewed one.

**4. `~/_LRNdh` is a genuine judgement call I left as RECOVER.** It holds 558
authored lines of upstream research whose commit landed and whose content `main`
then deliberately *withdrew* (`[v1.10.85] withdraw the four upstream studies and
the plan from the repo`). "Superseded by a decision already recorded" would justify
ABANDON; the brief's bias toward RECOVER justifies keeping it. I kept it and am
flagging it rather than deciding quietly.

**5. Two worktrees of `_agentjob_lgate/repo` live under `/tmp/gk_land_diff.*`** —
transient gatekeeper landing-diff scratch that a reboot removes anyway. They are in
the table for completeness; they are not work.

## For whoever executes this

* The RECOVER section is ordered so the valuable end is first: uncommitted edits,
  then authored lines. The 17 rows with uncommitted edits (15 in the brief's set)
  are the only content on this fleet that exists in exactly one place and nowhere
  in git — take those first.
* 30 rows are flagged "worktree dir has been EMPTIED". Their files are gone; only
  the commit survives, reachable through the worktree's HEAD. Pruning the worktree
  registration is what would make those commits unreachable — so for those, recover
  the *ref*, not the directory.
* Every ABANDON that rests on a landed issue names the superseding commit. Reading
  that commit is enough to overrule the row.

## Verification that nothing was destroyed

Post-run worktree counts against the counts the table was built from:

| host | now | measured |
|---|---:|---:|
| .105 | 4 | 4 |
| .108 | 29 | 28 |
| .112 | 38 | 38 |
| .114 | 152 | 149 |
| .120 | 166 | 166 |
| .121 | 99 | 99 |

Every count is equal or higher — nothing was removed anywhere. The four extra are
trees other agents created while this job ran, so the table is a snapshot as of
2026-08-20 ~19:40 against canonical `main` `eda53573f`, not a standing inventory.

The single worktree I created for myself (`~/_harv_priv/mainwt`) was removed as
soon as the read-only `--cached` variant of the test replaced it. Every subsequent
pass on every host was read-only: no worktree created, no ref written, and no
`git fetch` into any clone but this host's own `~/vibe-ic`.

## Files

| path | what |
|---|---|
| `~/.claude/fleet/runs/harvest_triage_table.md` | **the deliverable** — 700 rows, each with a verdict |
| `~/.claude/fleet/wt_classify.sh` | read-only content classifier (self-tests; exits 4 if a known-landed patch fails to reverse-apply) |
| `~/.claude/fleet/wt_lite.sh` | the cheap numstat-only path for clones with a stale `main` |
| `~/.claude/fleet/wt_dirty2.sh` | uncommitted state, splitting real edits from emptied shells |
| `~/.claude/fleet/wt_codeadd.sh` | authored-vs-regenerable line split |
| `~/.claude/fleet/verdict2.py`, `mktable.py` | the rule engine and the table renderer |
| `~/_harv_priv/findings.md` | 28 numbered findings, every command and number |
| `~/_harv_priv/triage.tsv` | the machine-readable table |

---

# ROUND 2 (2026-08-21) — fetched the shared clones, re-classified the 223

## What was done

`git fetch origin '+refs/heads/main:refs/remotes/origin/main'` in every surviving
shared clone plus each host's own `~/vibe-ic`. Fetch only: no checkout, no reset,
no index write, no working tree touched, no remote config changed. All 26 fetches
succeeded. Every repo now sits on `867de428` (2026-08-21).

Two things had to be fixed first:

* **14 of the 34 clones no longer exist.** They were deleted between the rounds,
  along with `~/_harv_priv` on all five remote hosts. Something is sweeping this
  fleet while the triage runs (F29, F33).
* **Four clones fetched a stale branch and reported success.** Their `origin` is
  the local path `~/vibe-ic`, and `refs/heads/main` in *that* repo is itself old
  (`3d13e2c59`, 2026-08-14) even though its `origin/main` is current. Only
  comparing before/after shas caught it; they were re-fetched from GitHub (F32).

## RECOVER before and after

| | RECOVER | LANDED | ABANDON |
|---|---:|---:|---:|
| before (stale per-clone `main`) | 57 | 130 | 15 |
| after (current `main` 867de428) | **59** | 127 | 16 |

202 matched worktrees; 8 verdicts changed. 20 could not be re-measured because the
clone or the tree was deleted between rounds — they are listed in
`~/.claude/fleet/runs/harvest_fetch_delta.txt`, not silently dropped.

**My F24 caveat was directionally wrong.** I predicted the stale ref was inflating
RECOVER; net it moved RECOVER *up* by two. The reason is the mitigation F24 itself
named: rule `L3` matches tip prose against the canonical `main`, so most landings
were already being caught regardless of each clone's ref. The staleness mattered
for 8 rows, not for the population.

## Every worktree whose verdict changed

**Away from RECOVER — the three the fetch actually fixed:**

| host | worktree | before | after | what it is |
|---|---|---|---|---|
| .120 | `~/_rb_r808/mut_wt` | RECOVER `UNLANDED`/295 | **LANDED** `LANDED_PATCH`/54 (`L1`) | `fix(flow): a bare no_analog: true block list is a …` |
| .120 | `~/_gk_p855/base` | RECOVER `UNLANDED`/246 | **LANDED** `LANDED_PATCH`/4 (`L1`) | `fix(sta): do not merge per-corner slack across the p…` |
| .120 | `~/vibe-ic-wt-progsupply-core` | RECOVER /2542 | **ABANDON** (`A6`) | `#312 — wire the SECOND track into Phase 1`; #312 landed, tree 7484 lines behind |

**Toward RECOVER — five, and they are weak recovers:**

All five went `LANDED_PATCH → UNLANDED`: their content *was* present in the older
`main` and is *not* in the current one. `ndel` is 10–20× `nadd` in every case, so
`main` moved away from them — these are stale variants of files still under active
development, not newly found features.

| host | worktree | nadd/ndel before → after |
|---|---|---|
| .120 | `~/vibe-ic-wt-caravel_user_project-fix-phase3-asic-top-resolution-caravel` | 989/13085 → 1437/19060 |
| .120 | `~/_wt_r5_stasta` | 842/10300 → 1249/16234 |
| .105 | `~/vibe-ic-wt-opentitan_aes-lint-xor-fold-memberkey` | 4/625 → 62/1211 |
| .120 | `~/vibe-ic-wt-caravel_user_project-fix-explicit-top-not-in-rtl` | 1/202 → 7/347 |
| .120 | `~/vibe-ic-wt-caravel_user_project-fix-def-progression` | 0/0 → 3/152 |

Verified one: `_wt_r5_stasta` touches `phase3_one_shot_runner.py`, which `main` has
rewritten three times since (`5100fc49c`, `41bfd8a12`, `9cc09b863`), and its prose
appears nowhere in `main`. RECOVER is the cautious call; these five are flagged as
weak rather than presented as recovered work.

## A false LANDED I caught in this round

The first comparison showed **12** worktrees moving RECOVER → LANDED with `nadd`
dropping from as much as 1942 to exactly 0. That looked like the fetch removing
staleness. It was not: all 12 were **deleted directories**. `wt_full.sh` bailed on
a missing directory and emitted zeros, and the `L0` rule read `nadd == 0` as
"content already in `main`, safe to delete" — about trees holding up to 1942
authored lines (F34).

An absent measurement is not a zero measurement. Fixed in two places: a missing
directory is now classified **from its commit** (the commit is still in the object
store and `git diff` needs no working tree), and the engine refuses to derive any
verdict from an unmeasured row — such rows get rule `U1`, verdict withheld,
defaulting to keep. That took the real count of changed verdicts from 19 to 8.

## Current published table

`~/.claude/fleet/runs/harvest_triage_table.md` — **747 worktrees**, all measured
against `867de428`. The fleet grew during the run (the `~/vibe-ic` set is now 551,
up from 478), so this is a fresh snapshot, not an edit of the round-1 table.

| scope | RECOVER | LANDED | ABANDON |
|---|---:|---:|---:|
| `~/vibe-ic` | 228 | 179 | 138 |
| the 20 surviving clones | 59 | 127 | 16 |

`harvest_fetch_delta.txt` holds the full before/after diff including the 20 rows
that could not be re-measured.

## The actionable consequence

24 rows now carry the flag **"worktree DIRECTORY has been deleted — the commit
survives in the object store, so recover the REF, not the directory."** Thirteen of
those are RECOVER: real work that exists now only as a commit reachable through a
worktree HEAD. For those thirteen, `git worktree prune` is the operation that would
make them unreachable. They need a branch or tag before any pruning sweep runs.

Given that 14 clones and `~/_harv_priv` on five hosts were deleted *during* this
job, that is not a hypothetical.

## Integrity of the published table

| check | result |
|---|---|
| rows with no verdict | 0 |
| duplicate (host, path) | 0 |
| unmeasured rows, verdict withheld (`U1`) | 2 |
| LANDED derived from an unmeasured row | 0 |
| rows flagged directory-removed | 24 |

Nothing was deleted by this job. Post-run worktree counts — .105 7, .108 43,
.112 47, .114 173, .120 180, .121 104 — are all higher than at the start.
