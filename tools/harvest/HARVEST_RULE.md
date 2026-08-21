# The keep-or-drop rule — vibe-ic worktree harvest

Follow this exactly and you will reach the same verdict I do on the same worktree.
Reference implementation: `~/.claude/fleet/wt_classify.sh`, `wt_full.sh`,
`wt_dirty2.sh`, `verdict_final.py`. Working notes: `~/_harv_priv/findings.md`.

---

## 0. FETCH FIRST. Never judge against a stale ref.

`main` on this repo moves fast — it went v1.11.18 → **v1.11.66 in one day**. A
worktree judged against yesterday's main is judged wrong.

Before touching any clone:

    git -C <repo> fetch origin '+refs/heads/main:refs/remotes/origin/main'

Fetch ONLY. No checkout, no reset, no `git worktree prune`, no config change.
Then record what you actually got and **verify the ref moved**:

    git -C <repo> log -1 --format='%h %cs' origin/main

**Trap that already bit me.** Four clones have `origin` = the local path
`/home/reyerchu/vibe-ic`. `+refs/heads/main` fetches that repo's local *branch*
`main`, which is itself weeks stale even when its `origin/main` is current. The
fetch exits 0 and reports success. If the sha did not move, re-fetch from GitHub
with an ad-hoc URL (writes only the tracking ref, changes no config):

    git -C <repo> fetch https://github.com/vibeic/vibe-ic.git \
        '+refs/heads/main:refs/remotes/origin/main'

Your shard owns whole HOSTS. Never touch a host outside your shard — two agents
fetching in one clone is a race with no upside.

*(Correction to the dispatch note: the 223 were mis-judged because nobody fetched,
not because two agents fetched at once. Host-disjoint shards are still right.)*

---

## 1. CONTENT, never ancestry.

vibe-ic **squash-lands everything**. A branch whose content is entirely on `main`
is still not an ancestor of it. These all report landed work as unlanded and are
FORBIDDEN as evidence:

    git merge-base --is-ancestor        git branch --merged
    git rev-list --count origin/main..HEAD    git cherry
    git status / "your branch is ahead by N commits"
    any merge that says "nothing to land" — that is the merge's account of itself

Judge by comparing file content. Git's object ids **are** content hashes
(SHA-1/SHA-256 of the blob), so comparing blob ids IS hashing the files — you do
not need to shell out to `sha256sum`, and you must not, because it would compare
the working tree instead of the commit.

    mb=$(git merge-base "$head" origin/main)
    for f in $(git diff --name-only "$mb" "$head"); do
      a=$(git rev-parse -q --verify "$head:$f")        # "" if deleted
      b=$(git rev-parse -q --verify "origin/main:$f")  # "" if absent
      [ "$a" = "$b" ] || echo "DIFFERS $f"
    done

Second chance for files that differ — are the tree's hunks already in `main`?
Reverse-apply its patch against a temp index read from `main`. Read-only; creates
no worktree:

    T=$(mktemp -d); export GIT_INDEX_FILE=$T/idx; git read-tree origin/main
    git diff "$mb" "$head" -- "$f" > $T/f.patch
    git apply --cached --check -R $T/f.patch && echo "already in main"

**Self-test or your numbers are worthless.** A patch known to be in main MUST
reverse-apply. If this fails, stop — the tool is broken, not the worktree:

    git diff origin/main~1 origin/main > $T/ctl && git apply --cached --check -R $T/ctl

---

## 2. The load-bearing number: `nadd`

    nadd = added lines of `git diff --numstat origin/main <head>`
           restricted to the files the worktree itself touched (mb..head)
         = what the tree HAS that main DOES NOT.   THIS is recoverable work.

    ndel = the mirror. Lines main has that the tree lacks = how far BEHIND main
           it is. Staleness. NEVER work.

**Do not sum them.** Summing made an already-landed tree (`_J1745`) score ~2000
lines of "novel work" when it was simply old. Beware also that a changed *value*
(a version pin `0.2.82` vs `0.3.14`) scores as one added line plus one deleted —
an old pin reads as novelty.

Split `nadd` further into `code_add` — exclude `benchmark-data/`,
`*.json|html|csv|svg|lock|log|gds|def|lef|sdf|spef`, and `reports?/runs?/logs?/out/output/results?/`
dirs. The single largest "88,225 line" RECOVER was 94% one regenerated
`corpus_baseline.json`.

---

## 3. Uncommitted state: count edits, not deletions

    tracked edits : git -C <wt> status --porcelain -uno | grep -c '^[MARC]'
    emptied shell : git -C <wt> status --porcelain -uno | grep -c '^.\?D'

A worktree whose status is entirely `D` has had its files removed from disk; the
registration and index survive and there is nothing in it to recover. Counting
those deletions as edits put empty shells at the TOP of the keep list.

`env -u GIT_INDEX_FILE` on every status call — if the temp index from §1 leaks in,
status compares the worktree against MAIN's index and reports ~18,000 phantom
edits per tree.

Untracked files are regenerable EDA/benchmark output. They are not work.

---

## 4. An ABSENT measurement is not a ZERO measurement

If the worktree directory is gone, **do not emit zeros** — `nadd == 0` then reads
as "content already in main, safe to delete", and that is how 12 trees holding up
to 1942 authored lines were nearly marked deletable.

A missing directory is not missing work: the commit is still in the object store
and `git diff <mb> <head>` needs no working tree. Classify from the COMMIT and flag
the directory as removed. If you genuinely cannot measure a row, give it rule `U1`,
withhold the verdict, and default to keep.

---

## 5. The verdict ladder — first rule that fires wins

| rule | verdict | fires when |
|---|---|---|
| `U1` | RECOVER | state GONE/NOHEAD/NOMERGEBASE — could not measure, verdict withheld |
| `L2` | RECOVER | ≥1 tracked uncommitted EDIT — exists on one disk only, outranks everything |
| `L0` | LANDED | `nadd == 0` and clean — nothing in it is absent from main |
| `L1` | LANDED | every changed file blob-identical to main, or its hunks reverse-apply |
| `L3` | LANDED | the tip's normalised prose appears in `main`'s history |
| `N1` | LANDED | only lines absent are version manifests / README version strings |
| `A1` | ABANDON | tip is `Merge …pr/NNNN`, that PR **merged** |
| `A2` | ABANDON | tip is `Merge …pr/NNNN`, PR closed **unmerged** |
| `R1` | RECOVER | tip is `Merge …pr/NNNN`, PR still **open** |
| `A3` | ABANDON | `[vX.Y.Z] candidate batch` older than main's plugin version |
| `A5` | ABANDON | bare integration merge holding ≤20 lines absent from main |
| `A6` | ABANDON | the tree's issue landed in main **and** `ndel >= 2*nadd` |
| `A4` | ABANDON | identical HEAD to a tree already kept |
| `A7` | ABANDON | tip declares itself a local probe not for pushing |
| `R2` | RECOVER | everything else, sized by `code_add` |

**`L3` — the squash keeps the prose.** Landing rewrites the `type(scope):` prefix
and appends the PR ref but keeps the sentence verbatim, so normalised prose is a
reliable landed-identity key:

    lowercase; drop trailing "(#NNNN)"; drop leading "[vX.Y.Z]";
    drop leading "type(scope): "; drop "#N"; strip punctuation; require >=25 chars

**Guard on `L1` and `L3`:** only fire when `code_add <= 200 OR ndel > nadd` — the
residual must look like staleness (main holds more), not fresh content. Without it,
`_LRNdh` was called LANDED while holding 558 lines main had deliberately
*withdrawn* (`[v1.10.85] withdraw the four upstream studies`).

**`L3` refuses bare `Merge ` tips** — merge prose is too weak an identity key.

**Every `A6` must name the commit that supersedes it** (sha + subject), so the
call is auditable rather than asserted.

---

## 6. Standing constraints

* **Ties break toward RECOVER.** An over-cautious keep costs disk. A wrong ABANDON
  destroys work nobody can reconstruct.
* **DELETE NOTHING.** Not worktrees, not clones, not refs, not even obvious LANDED.
  This job decides; a later one executes. Do not run `git worktree prune` — for the
  trees whose directory is already gone, pruning is exactly what makes the commit
  unreachable and loses the work.
* **Never `pkill`/`pgrep` a pattern that can match your own command line.** This
  killed my shell three times. `$$`-exclusion is not enough. Select by a PID
  recorded before you composed the command, or by `/proc/PID/cwd`. Treat reaching
  for `pkill` at all as the smell.
* **Key every join on (HOST, path), never path alone.** 13 worktree paths exist on
  more than one machine (`~/_i1348` on both .108 and .112, different work); a
  path-only key silently merged 27 rows' measurements.
* **The fleet moves under you.** During my run 14 clones, `~/_harv_priv` on five
  hosts, and 44 worktrees were deleted, while the total grew 747 → 811. Record the
  main sha you judged against in every row, and treat your output as a snapshot.

## 7. Output

One row per worktree, every row carrying a verdict, plus enough to re-derive it:

    host  repo  path  branch  head  state  nadd  ndel  code_add  trk_edits
    issue  verdict  rule  subject  novelfiles  main_sha_judged_against  why
