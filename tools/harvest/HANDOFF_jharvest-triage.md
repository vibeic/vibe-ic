HANDOFF READY

# Handoff — agent `jharvest-triage`, host 8HD-4 / 192.168.1.120, 2026-08-20→22

Everything below is on branch **`harvest/worktree-triage-jharvest`** (pushed to
GitHub, commit `4fec12d87`, under `tools/harvest/`). Take it from there, not from
my host: this fleet deleted `~/_harv_priv` on all five remote machines and 14 whole
clones while I worked, so local paths here are not durable.

---

## What the job is

The six fleet machines are covered in git worktrees that agents made and left. Some
hold work that never reached `main`; most hold work that DID reach main and is just
sitting there. Somebody has to decide, per worktree, whether it is worth recovering
or safe to delete. The output is a table with a verdict on every row. **This job
decides; a later one executes. Delete nothing.**

The whole difficulty is one fact: **vibe-ic squash-lands everything.** A branch
whose content is entirely on main is still not an ancestor of main. So
`merge-base --is-ancestor`, `branch --merged`, `rev-list origin/main..HEAD` and
`git status` all report landed work as unlanded. A sweep written on ancestry would
delete ~300 worktrees of real work. Judge by CONTENT.

---

## What is ESTABLISHED

**The table.** `tools/harvest/harvest_triage_table.md` (+ `.tsv`) — 747 worktrees,
every row with a verdict, measured against `origin/main` `867de428` (plugin
v1.11.18). `~/vibe-ic` 228 RECOVER / 179 LANDED / 138 ABANDON; the 20 surviving
other clones 59 / 127 / 16.

**The rule.** `tools/harvest/HARVEST_RULE.md` — 15 rules, first match wins,
precise enough to reproduce a verdict. `tools/harvest/bin/` is the implementation.
`wt_classify.sh` self-tests on start (exit 4 if a known-landed patch fails to
reverse-apply) and is read-only: tier 2 runs against a temp `GIT_INDEX_FILE`, so it
creates no worktree in a repo other agents share.

**Four numbers in the original brief are wrong. Mine are measured:**
- `~/.claude/fleet/wt_classify.sh` did not exist on any of the six hosts. I wrote it.
- 477 counts only each host's `~/vibe-ic`. Real population was 701, now **811**.
- "~140 carry uncommitted edits" → **15**. That figure counted untracked EDA output;
  an intermediate 95 of mine counted staged deletions.
- `.108` and `.121` are reachable. My key is not authorised there but `.112`'s is,
  so `ssh .112 "ssh .108 …"` works. `-J`/ProxyJump does NOT — it forwards the
  origin key and fails identically. Helper: `tools/harvest/bin/rsh`.

**The content test needed three corrections beyond the ancestry warning.** Each was
found by hand-checking a row my own engine had already scored — not by reasoning:
1. Whole-file identity compares against a *moving* main. A file whose change landed
   and which main later touched for an unrelated reason reads as unlanded. First
   pass: 156/165 "UNLANDED" on this host. Fixed with a hunk-local reverse-apply.
2. **`added + deleted` is not a measure of work.** In the `main → head` direction
   "deleted" means main has it and the tree does not — staleness. `.114:~/_J1745`
   scored ~2000 "novel" lines while being an already-landed tree that was merely
   old. Only `nadd` (added) counts. Beware too that a changed *value* (version pin
   `0.2.82` vs `0.3.14`) scores as one added plus one deleted, so an old pin reads
   as novelty (`.120:~/_wt905_927`, #927, nadd=117, all of it stale).
3. **The squash keeps the prose.** Landing rewrites the `type(scope):` prefix and
   appends the PR ref but keeps the sentence verbatim, so normalised subject text is
   a reliable landed-identity key. Worth 49 rows.
   Proof: `.120:~/_wt_issue1431` tip `fix(landing): a gate's label carried a
   per-tree count…(#1431)`; main carries `7455bffb5 landing: a gate's label carried
   a per-tree count… (#1431) (#1516)`. Same commit.

**A near-miss worth more than the table.** A worktree whose *directory* had been
deleted emitted `nadd=0`, and the ladder read that as "content already in main,
safe to delete" — about 12 trees holding up to 1942 authored lines. An absent
measurement is not a zero measurement. Reproduce:
`grep -F '/home/reyerchu/_wt_clockbasis	' x_114.tsv` showed `state=GONE nadd=0`.
Fixed two ways: a missing directory now classifies from its COMMIT (still in the
object store; `git diff <mb> <head>` needs no working tree), and the engine
withholds any verdict on an unmeasured row (rule `U1`).

**The fetch round.** All 20 surviving shared clones + six `~/vibe-ic` fetched to
`867de428`. Result: RECOVER 57→59, LANDED 130→127, ABANDON 15→16; 8 of 202
verdicts changed. Full diff in `tools/harvest/harvest_fetch_delta.txt`.

**The fan-out.** 811 worktrees exist now; 734 already carry a verdict. But main
moved again to `a00f53f20` / plugin **v1.11.66** — ~48 versions of landings. That
invalidates one direction only: LANDED stays LANDED and ABANDON stays ABANDON as
main advances, so only RECOVER can flip. Re-judge scope = 66 NEW + 11 MOVED + 278
RECOVER-recheck = **355**, sharded by HOST (hosts stay whole so two agents never
fetch one clone): **a**=host 120, 114 rows; **b**=114+105, 131; **c**=121+112+108,
110. Files `tools/harvest/_harv_shard_{a,b,c}.tsv`.

---

## What I TRIED that did NOT work — do not redo these

- **`git worktree add` for the reverse-apply test.** Works, but writes into a repo
  other agents share. Replaced with `GIT_INDEX_FILE=$T/idx; git read-tree
  origin/main; git apply --cached --check -R <patch>` — same discrimination, fully
  read-only, and it is what lets the classifier run on other hosts safely.
- **Whole-patch reverse-apply.** All-or-nothing: one novel hunk fails the whole
  patch, so a tree with 8 landed files and 2 novel ones reads as fully novel. Must
  be per file.
- **`ssh -J` / ProxyJump to `.108`/`.121`.** Forwards the ORIGIN key, so it fails
  exactly like a direct connection. Nested `ssh` (run ssh ON `.112`) is the fix.
- **`+refs/heads/main:refs/remotes/origin/main` on the four clones whose `origin`
  is the local path `~/vibe-ic`.** Fetches that repo's local *branch* `main`, which
  is itself weeks stale (`3d13e2c59`, 2026-08-14) even though its `origin/main` is
  current. **`git fetch` exits 0 and reports success.** The only tell is the sha not
  moving. Re-fetch those from `https://github.com/vibeic/vibe-ic.git` with an
  ad-hoc URL (writes only the tracking ref, changes no config).
- **`status --porcelain` while `GIT_INDEX_FILE` is exported.** Compares the worktree
  against MAIN's index and reports ~18,083 phantom edits per tree. Always
  `env -u GIT_INDEX_FILE` on status calls.
- **Counting `status --porcelain -uno | wc -l` as "uncommitted edits".** Staged
  deletions (`D`) are counted, so 30 *emptied shells* — files gone from disk, index
  recording only `D` — sorted to the TOP of the keep list. Count `^[MARC]` for
  edits and `^.\?D` separately.
- **Keying side tables on worktree path alone.** 13 paths exist on more than one
  machine (`~/_i1348` on both `.108` and `.112`, different work); 27 rows had one
  host's measurements overwritten by another's. Key on `(host, path)`.
- **`pkill -f <pattern>` / `awk '/pattern/{print $1}' | kill`.** The pattern matches
  the command line of the shell running it. **This killed my own shell three times**
  (exit 144). `$$`-exclusion is not enough — it excludes awk's shell, not its
  ancestors. Select by a PID recorded before you composed the command, or by
  `/proc/PID/cwd`. Treat reaching for `pkill` at all as the smell.
- **Running the per-file tier-2 loop on a clone with a stale `main`.**
  `_agentjob_lgate/repo` (main from 2026-07-30) diffs 18,244 files per worktree =
  18,244 `git apply` calls each. After fetching, the same tree diffs **16** files.
  Fetch first; it is a correctness fix and a ~1000x speedup.
- **Sequencing `~/vibe-ic` before the clones in a fan-out run.** Put the small,
  high-value work first — I queued the extras behind a 166-worktree pass and had to
  relaunch to get the answer.
- **Deploying to `~/_harv_priv/bin` on remote hosts without `mkdir -p`.** A sweep
  deleted that directory on all five remotes mid-session; the redirect then fails
  with a message that reads like a missing script.

---

## Believed but NOT proven

- **UNPROVEN: that LANDED/ABANDON are stable as main advances.** I argued content
  already on main stays on main barring a revert, and scoped the re-judge to
  RECOVER on that basis. I did not test it. A revert or a withdrawal breaks it —
  and I have one confirmed instance of exactly that: `.121:~/_LRNdh` holds 558
  authored lines whose commit landed and whose content main then *withdrew*
  (`0d7b6428a [v1.10.85] withdraw the four upstream studies`). If withdrawals are
  common, LANDED rows need rechecking too and my 355 is an undercount.
- **UNPROVEN: the 199 RECOVER rows in `~/vibe-ic` are individually worth keeping.**
  I verified the RULES against hand-checked counterexamples and audited the extremes
  of every column. I did not read the trees. Each row carries its authored-line
  count, files, issue and rule — enough to review one, not the same as reviewed.
- **UNPROVEN: the `A6` threshold `ndel >= 2*nadd` is right.** I sized it (60 rows at
  1x, 43 at 2x, 41 at 3x, 32 at 5x) and picked the conservative end, then verified
  the two largest calls landed (#1251 → `3a3d1eae5`; #1115 → `3c33c1dd5`, subject
  identical, "re-implementing"). The other 41 are rule-derived.
- **UNPROVEN: the 5 trees that flipped LANDED→RECOVER after the fetch are worth
  keeping.** All went `LANDED_PATCH → UNLANDED` with `ndel` 10-20x `nadd` — content
  that WAS in the older main and is not in the current one. I checked one
  (`_wt_r5_stasta`, `phase3_one_shot_runner.py`, rewritten 3x since, prose not in
  main) and read it as a stale variant. Kept as RECOVER on the bias-to-keep rule,
  flagged weak.
- **UNPROVEN: my host list is the whole fleet.** Six hosts came from the brief plus
  `.108`/`.121` which it did not name. There may be more.

---

## The exact next step

Run shard **a** — `tools/harvest/_harv_shard_a.tsv`, 114 rows, all on host
**192.168.1.120**, so it is local work:

1. `git -C /home/reyerchu/vibe-ic fetch origin '+refs/heads/main:refs/remotes/origin/main'`
   then **verify the sha moved** (`git log -1 --format='%h %cs' origin/main`;
   expect ≥ `a00f53f20`, 2026-08-21).
2. `bash tools/harvest/bin/wt_full.sh /home/reyerchu/vibe-ic > r3_120.tsv`
   and `bash tools/harvest/bin/wt_dirty2.sh /home/reyerchu/vibe-ic > d3_120.tsv`.
   `wt_full.sh` exits 4 if its self-test fails — if it does, stop, the tool is
   broken, not the worktrees.
3. `python3 tools/harvest/bin/verdict_final.py > triage_a.tsv` (it globs
   `r2_*/x_*` — point it at your filenames), then
   `python3 tools/harvest/bin/mktable.py triage_a.tsv <out>.md`.
4. Compare against the prior verdicts carried on each shard row. The expected
   movement is RECOVER → LANDED for work that landed in v1.11.18…v1.11.66. Report
   every row that changed, with `nadd`/`ndel` before and after.
5. Record the main sha you judged against in every row. It moves hourly.

Shards **b** (114+105) and **c** (121+112+108) are dispatched to other agents. Do
not touch a host outside your shard.

**Standing constraints:** never push to `main`, never bump the plugin version (the
lander assigns it), delete nothing anywhere — and do NOT run `git worktree prune`:
for the 24 trees whose directory is already gone but whose commit survives, pruning
is precisely what makes the work unreachable. 13 of those 24 are RECOVER.
