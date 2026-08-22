# The frozen batch collides on eight files, and half of them are generated

**Measured 2026-08-22 against `a4caccefe`** (main at the time of the freeze), over
the sixteen branches named in the freeze. Nothing here modifies a frozen branch;
it is a map for whoever assembles them.

## 1. The collision surface is eight files

Computed per branch as `git diff --name-only $(git merge-base <branch> a4caccefe) <branch>`
-- each branch's OWN contribution -- then intersected across branches. This is
order-independent, unlike a merge sequence.

| file | branches | treatment |
| --- | --- | --- |
| `vibe-ic-marketplace/README.md` | 3 | REGENERATE after assembly |
| `vibe-ic-marketplace/plugins/vibe-ic/README.md` | 3 | REGENERATE |
| `.../programs/PROGRAM_INVENTORY.json` | 3 | REGENERATE |
| `.../programs/INDEX.md` | 2 | REGENERATE |
| `.../benchmark/CAPTURE_ROUTING.json` | 3 | UNION -- see §2 |
| `.../programs/phase3_one_shot_runner.py` | 2 | shared touch, MERGES CLEAN (measured) |
| `.../programs/gatekeeper_review.py` | 2 | shared touch, MERGES CLEAN (measured) |
| `docs/capture/2026-08-21-jcap-ppa/recoveries.json` | 2 | REAL conflict -- needs its authors |

Four of the eight are generated indices. Reconciling their hunks by hand is wasted
work and can produce a file that matches neither tree: rebuild them once, after all
sixteen are in.

**MEASURE FROM THE MERGE-BASE, NOT FROM MAIN.** Diffing these branches against
`a4caccefe` reported up to 10-of-13 file overlaps with one branch. That was the
instrument, not the batch: several branches sit up to 244 commits behind main, so
the diff counts everything that landed since. Merge-base gave the true figure.

### Pairwise results, measured

Sharing a file is not the same as conflicting on it. Every shared file above was
merged pairwise onto `a4caccefe`:

    capture/jdistchip-chip-path-rules x fix/jppafind-inert-ppa-gates
        CONFLICT -- but only on the four GENERATED indices.
        `phase3_one_shot_runner.py`, which both touch, merged clean.
    jdistmat/matrix-distil x jcap-ppa
        CONFLICT on docs/capture/2026-08-21-jcap-ppa/recoveries.json (real content)
    agent/jrows-on-batchbig x fix/jwire2-hygiene-wiring
        CLEAN on gatekeeper_review.py
    fix/jwire2-hygiene-wiring x jcap-ppa
        CONFLICT on CAPTURE_ROUTING.json -- union, see below

So the batch has exactly TWO real content conflicts -- `CAPTURE_ROUTING.json` and
`recoveries.json` -- and everything else that collides is a generated index. An
earlier revision of this document listed `phase3_one_shot_runner.py` as a content
merge on the strength of two branches touching it. Touching is not colliding, and
the difference is one merge command.

## 2. `CAPTURE_ROUTING.json`: take the union, and the check is 64

Three branches add keys to the `steps` object. All three pairwise overlaps are
EMPTY, so the union is well defined and needs no judgement:

    base a4caccefe                    46 entries
    + fix/jwire2-hygiene-wiring        2   phase2.pad_budget, repo.pr_scope
    + jcap-ppa                        15
    + jcapsha/pad-site-capture         1
    ------------------------------------
    union                             64 entries under "steps"

**Why a count is worth carrying.** Both sides insert at the same position in one
JSON object, so git reports a textual conflict. `--ours` or `--theirs` then resolves
CLEANLY while deleting a whole side's routing -- and nothing need go red, because
`enhancement_emit.route_for` simply stops knowing about those steps. 64 is what
catches it; 48 or 61 or 63 means a side was dropped.

Verified for the two-branch case by building the union and running the repo's own
routing tests plus the three modules that read this file: 175 passed, 9 skipped,
and `route_for` resolved a key from each side.

**This number was published twice before it was right** -- first 66 (counting the
three structural keys `_comment`, `default_routing`, `steps` alongside the routing
entries), then 63 (computed from two of the three branches that touch the file).
A batch-wide invariant derived from a partial set is wrong in the direction that
looks plausible. Derive the set first.

## 3. A merge sequence under-reports conflicts

Merging all sixteen in list order gave `13 of 16 clean`, conflicting on
`capture/jdistchip-chip-path-rules`, `jcap-ppa` and `agent/jrows-on-batchbig`.
That set is ORDER-DEPENDENT: a conflicting branch is aborted, so its content never
enters the tree and later branches cannot collide with it. The
`CAPTURE_ROUTING.json` collision above does NOT appear in that run for exactly
that reason. Read `13 of 16` as "13 merge clean if you skip the 3", never as a
clean bill.

## 4. A corpus-bound hygiene baseline for `a4caccefe`

Without a bound corpus the hygiene set REFUSES rather than reporting -- correct
behaviour, but it means a landing gets no verdict. Bound:

    git clone --depth 1 https://github.com/vibeic/benchmark-data.git <corpus>
    export VIBE_IC_BENCHMARK_DATA=<corpus>
    PYTHONDONTWRITEBYTECODE=1 bash tools/ci/repo_hygiene_gates.sh   # ~1000s, clean tree

    a4caccefe: 82 of 93 decided -- 73 passed, 9 failed, 11 NOT CHECKED

The nine failing gate names, which are what a batch measurement should diff
against (names, not counts -- a count hides a 1-in/1-out swap):

    an argued direction is pinned      liar census controls still fire
    citation routing is true           PPA measurement coverage
    cross-layer reference regression   published-evidence index honest
    evidence citation resolves         step FAIL bubbles up
    L-doc field producer

Three traps: run it STANDALONE, not through `gatekeeper_review` -- the sharded lane
returned `PROGRESS_PROTOCOL_INCOMPLETE` / watchdog `rc=199` and certified nothing,
while the unsharded run completed; bind BOTH sides identically, because binding
changes the DENOMINATOR as well as the verdicts; and a shallow clone makes
`engineering evidence fresh` REFUSE rather than pass, which is correct and is
disclosed.

## 5. The five dangling evidence citations are corpus rows, not batch defects

All five live in the `benchmark-data` repository. The plugin batch neither caused
them nor can fix them, and they are identical on `a4caccefe` and on a branch head,
so nothing in the batch introduced them.

| citation | status |
| --- | --- |
| `ic/METHODOLOGY.md:67` -> `benchmark-data/PUBLISHING.md` | stale label; the file moved to the corpus root in v1.10.56. The hyperlink `](../PUBLISHING.md)` still resolves |
| `ic/INDEX.md:8` -> same | stale label, same cause |
| `ic/METHODOLOGY.md:256` -> `sha256/RESULT.md` | unpublished: `ic/sha256/` holds only `input/` |
| `ic/METHODOLOGY.md:231` -> `sha256/BENCHMARK_VERIFICATION_REPORT.md` | unpublished, same cell |
| `ic/END_TO_END_CAMPAIGN.md:7` -> `.../CVDP_CAMPAIGN_FOLLOWUP.md` | absent from every branch of the corpus |

The gate extracts backtick-quoted inline code as a claimed path
(`_CITE_RE = re.compile(r"`([A-Za-z0-9_./+{},-]+)`")`) and deliberately ignores the
hyperlink target, so rows 1 and 2 are real -- a reader who types the path finds
nothing -- but the remedy is editing a label, not producing a document. Rows 3 and
4 have a known cause: the corpus carries an unmerged branch whose name records the
cell's publication as undetermined.

No baseline was rewritten and `--write-baseline` was not run, including where two
of these gates explicitly suggest it.
