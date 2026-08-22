# The frozen batch collides on eight files, and half of them are generated

**Measured 2026-08-22 against `a4caccefe`** (main at the time of the freeze), over
the sixteen branches named in the freeze. Nothing here modifies a frozen branch;
it is a map for whoever assembles them.

## What this says, in short

Read this first. The sections below are the working, in the order it happened, and
several were superseded by later measurement.

**Also worth confirming:** three `land/*` refs exist and two look live; only
`land/one-assembled` carries the frozen batch (last section).

**The one thing still open:** `fix/jppafind-inert-ppa-gates` is ON THE FREEZE LIST
but is NOT in `land/one-assembled` (`e11626e28`). Verified two ways -- 5 of 5
sampled files are byte-identical to MAIN rather than to the branch, so it was never
applied. It merged clean in every test here, so this looks unintended (§9).

**Already settled, do not redo:**

* The collision surface is **eight files**; four are generated indices to REBUILD
  after assembly, not merge (§1).
* Only **two** files were real content conflicts: `CAPTURE_ROUTING.json` and
  `recoveries.json` (§1, §8).
* `CAPTURE_ROUTING.json` -- take the UNION. The check is **64** entries under
  `steps`, and the real assembly came out at exactly 64 with no side dropped (§2, §9).
* `recoveries.json` -- **RESOLVED at 45 rows**; the disputed rule was KEPT under
  `jdistmat`'s renamed form. §7 said eleven entries needed two authors, §8 reduced
  it to one row by measuring content instead of keys, and §9 records how it landed.
* The batch **assembles**: fifteen of the sixteen frozen branches are in (§6, §9),
  and the assembled tree is regression-clean across the modules covering the files
  where branches overlap -- 444 passes, no failures (§9).

**A caution on the numbers here:** the hygiene baseline in §4 is stamped
`a4caccefe` and expires into a FALSE ACCUSATION if diffed after exemption work
lands -- read §4 before using it.

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
| `docs/capture/2026-08-21-jcap-ppa/recoveries.json` | 2 | REAL conflict -- ONE row needs one author (§8) |

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

**THIS BASELINE HAS A SHELF LIFE, AND THE WAY IT EXPIRES CAUSES MISATTRIBUTION.**
Its eleven NOT CHECKED rows are all DATE EXEMPTIONS carried in
`tools/ci/repo_hygiene_gates.sh`, and that file is under active edit by other
work -- observed 2026-08-22, commits reworking exemptions whose stated reason the
gate does not actually enforce. When such a fix lands, gates that were NOT CHECKED
begin to DECIDE, and some will decide FAIL. Diffed naively against the numbers
below, those read as reds the batch introduced. They are not: they are gates that
could finally look. Re-measure the "before" side at whatever main actually is
before attributing any new red to a branch -- the sha this was taken at,
`a4caccefe`, is stated for exactly that reason.

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

## 6. The batch assembles: 15 of 16, and the one blocker is named

Not a prediction -- performed. Merging all sixteen onto `a4caccefe`, resolving
generated indices by REGENERATION and `CAPTURE_ROUTING.json` by UNION:

    merged 15 of 16
    left out: jcap-ppa -- docs/capture/2026-08-21-jcap-ppa/recoveries.json
              conflicts with jdistmat/matrix-distil

Every other conflict fell to the two mechanical rules. Then, on the assembled
tree:

    python3 programs/gen_program_inventory.py
        -> changed exactly ONE file, PROGRAM_INVENTORY.json

So the four "collisions" in the generated indices are not merges at all: rebuild
once at the end and the READMEs and INDEX.md come out identical to what the
generator produces anyway.

    CAPTURE_ROUTING.json "steps" = 49 entries
        = 46 base + 2 (fix/jwire2-hygiene-wiring) + 1 (jcapsha/pad-site-capture)
        jcap-ppa's 15 are absent because that branch is the one left out;
        with it the count is 64, as in section 2.

    pytest: test_enhancement_emit + the three modules that read the routing file
        -> 175 passed, 9 skipped

**So the only human decision blocking a full assembly is `recoveries.json`,**
between `jdistmat/matrix-distil` and `jcap-ppa`. It is one file, it belongs to
those two authors, and nothing else in the batch waits on anything.

This assembly was built to MEASURE and was not pushed anywhere. Assembling and
landing the batch belongs to whoever owns it; this section says only that the
path is clear and where it is not.

## 7. The one blocker, sized: 11 entries need their two authors

> **SUPERSEDED BY §8.** The count below is wrong: it was measured by KEY,
> and the key is the field that moved. Measured by CONTENT, eleven of the
> twelve are mechanical and ONE row is the question. The section is kept
> because how the number collapsed is the useful part.

`docs/capture/2026-08-21-jcap-ppa/recoveries.json` is the only thing standing
between this batch and a full assembly (§6). It is a JSON LIST, and the two sides
did different KINDS of thing to it. Taking entry identity as
`(rule_name, step, design)` over the merge-base `a4caccefe`:

    base                          14 entries
    jcap-ppa   adds 31, removes  1, MODIFIES 13 of the shared entries
    jdistmat   adds 12, removes 12, modifies  0 of the shared entries

    added by BOTH                  0
    modified by BOTH               0

So there is no head-on clash: no entry is edited by both, and no entry is
introduced by both. **43 of the changes are mechanical** -- jcap-ppa's 31 new
entries and jdistmat's 12 new entries are disjoint and both belong; 2 further
jcap-ppa edits touch entries jdistmat left alone.

**The whole question is 11 entries that jdistmat REMOVED and jcap-ppa MODIFIED.**
That is a delete/modify, and it is not resolvable by inspection: jdistmat's
`adds 12, removes 12` at a constant total of 14 reads like a REWRITE that changed
the entries' identity fields, in which case its new rows supersede the old ones
and jcap-ppa's edits to them are moot. If instead those removals were incidental,
jcap-ppa's edited rows should survive. Only the two authors know which.

Four of the eleven, so the question is concrete rather than abstract:

    a metric constant across arms that differ is not measured under that lever   (ppa.search)
    a published absence claim is rechecked against the tree                      (ppa.search)
    a runtime output path may not resolve inside the installed tree              (ppa.artefact_write)
    a writer enforces the field shapes its declared consumer requires            (capture.emit)

This is deliberately NOT resolved here. A union would resurrect eleven rows that
one author may have deliberately replaced, and a merge that silently reinstates
retired rules is worse than the conflict -- the file is a recovery register, and a
stale rule in it is a rule somebody will act on.

WHAT IS ACTUALLY NEEDED: one yes/no from the `jdistmat/matrix-distil` and
`jcap-ppa` authors -- "did the rewrite supersede these eleven?" -- after which the
rest of the file merges mechanically and the batch assembles 16 of 16.

## 8. Correction to §7: the blocker is ONE row, and eleven are mechanical

§7 said eleven entries needed a ruling from two authors. That was measured by KEY,
and the key was the thing that moved. Measured by CONTENT it collapses.

Every one of `jdistmat`'s twelve "removals" has an EXACT content match among its
twelve "additions" -- identical `pattern`, `docstring`, `expected_signal` and
`fix_action`, similarity 1.00 on all twelve. Only `rule_name` changed form:

    "gate proof vocabulary has a producer"  ->  gate_proof_vocabulary_has_a_producer
    "population guard asserts equality not a floor"
                                           ->  population_guard_asserts_equality_not_a_floor

That is a RENAME of the identity field from prose to a snake_case slug, not a
deletion. Comparing by key made a rename look like twelve deletes and twelve
unrelated adds.

So what each side did to those rows is INDEPENDENT:

    jdistmat  renames the row               (rule_name)
    jcap-ppa  updates the row's content     (fix_action on 11, docstring on 2)

which is an ordinary three-way merge -- take the renamed row, apply the content
edit. Git could not see it because the rename changed the identity of a LIST
ENTRY, and a JSON list has no key for git to follow.

**ELEVEN of the twelve are therefore mechanical.** The mapping is not guesswork:
each is pinned by a 1.00 content match, so which renamed row receives which edit
is determined, not chosen.

**ONE row is a real question, and it is the whole blocker:**

    an optional import is guarded by capability not by exception type
        jdistmat RENAMED it   (to optional_import_is_guarded_by_capability...)
        jcap-ppa DELETED it

A delete against a rename. Nobody should infer which wins: either `jcap-ppa`
retired the rule deliberately, or it deleted a row whose replacement it had not
seen. That is one yes/no from one author.

Merged mechanically the file holds 45 rows (jdistmat's 14, twelve of them renamed,
plus jcap-ppa's 31 new), or 44 if the deletion stands.

THE GENERAL POINT, because it will recur: a JSON LIST has no key, so any tool --
git included -- compares its entries positionally or by whole value. A change to
an identity field inside such a list is indistinguishable from delete+add, and a
"conflict" of that shape is worth re-measuring by CONTENT before anyone is asked
to adjudicate it. Here it turned twelve authorial decisions into one.

### The mechanical part, performed

Not asserted. Reconstructing the merge -- take `jdistmat`'s rows, map each renamed
row to its base original by exact content on
`(pattern, docstring, expected_signal)`, carry `jcap-ppa`'s edit onto it, then
append `jcap-ppa`'s new rows:

    merged rows                                   44
    jcap-ppa content edits carried onto renames   13   (fix_action 11, docstring 2)
    rows withheld pending the one decision         1
    JSON valid                                    yes

    => 44 rows if jcap-ppa's deletion stands, 45 if jdistmat's rename does.

The withheld row is the only one whose fate is not determined by the data:

    base    : an optional import is guarded by capability not by exception type
    renamed : optional_import_is_guarded_by_capability_not_exception_type

This reconstruction was performed to VERIFY that eleven rows are mechanical, and
the result is deliberately not shipped here. The file belongs to its authors, and
a merged register handed over by a third party is exactly the artefact nobody
audits. What is offered is the finding: the work is one decision, not twelve.

### The one row: it is a real delete, and no replacement covers it

Checked, because "deleted" and "renamed differently" need different answers, and
because a nearby rule looked like it might supersede it. Neither guess survived.

`jcap-ppa`'s merge-base with main IS `a4caccefe`, and the row is present there, so
this is not a branch that forked before the rule existed. Searched `jcap-ppa` by
CONTENT rather than by name: the best match for the retired row scores **0.08**.
It is a genuine deletion, not a rename.

The nearest rule `jcap-ppa` adds is NOT a replacement:

    retired : an optional import is guarded by capability not by exception type
              step repo.host_independence -- an optional dependency imported inside
              a handler that catches the import failure, with a fallback that binds
              a name whose attributes nothing checks
    added   : a third-party import at test module scope must be guarded or it
              aborts collection
              step repo.test_population -- a TEST file importing an optional package
              at module scope, which aborts pytest collection on a host without it

Different step, different scope, different failure. The added rule is about test
COLLECTION; the retired one is about capability checking after a guarded import
anywhere. Retiring the first is not covered by adding the second.

So the question for the `jcap-ppa` author is specific: **was dropping the
`repo.host_independence` capability-check rule intended?** If yes the merged file
holds 44 rows; if it was incidental, `jdistmat`'s renamed row should survive and it
holds 45.

This is the shape of loss this file is most exposed to. A recovery register does
not fail loudly when a rule leaves it -- nothing goes red, the rule is simply never
applied again. That is why this one row was worth chasing to the end instead of
being folded into a union.

## 9. Outcome, measured against the real assembly

`land/one-assembled` at `e11626e28` (2026-08-22). Stamped, because that ref moves.

**`recoveries.json` was resolved to 45 rows**, carrying the disputed rule under
`jdistmat`'s renamed form, `optional_import_is_guarded_by_capability_not_exception_type`.
That is the "rename survived" branch of §8 -- the `repo.host_independence`
capability rule was KEPT, which is the outcome §8's evidence pointed to, since the
rule `jcap-ppa` added covers test collection and not capability checking.

**`CAPTURE_ROUTING.json` came out at exactly 64 entries**, the invariant this
document published in §2, with both of `fix/jwire2-hygiene-wiring`'s keys and
`jcap-ppa`'s present. No side was dropped -- the failure this document warned
about did not happen.

**The rc-3 pair stayed together**: the gate's `GateArgumentParser` and the runner's
`elif rc == _usage_rc():` are both in the assembly. On that tree,
`checker_execution_wiring_audit` and `hdl_declaration_scan_strips_comments_check`
both exit 0, and the four modules that exercise this work pass 175 / 9 skipped.

**FIFTEEN of the sixteen frozen branches are in it. The absent one is
`fix/jppafind-inert-ppa-gates`** -- flagged here because it is on the freeze list
and merged clean in every test this document ran, so its absence looks unintended
rather than decided.

The `jppafind` absence is stated with more care than the rest of this document,
because acting on it means re-assembling. It was tested TWO independent ways, after
the first two methods here proved unreliable:

    12 distinctive added lines of its own      ->  2 found in the assembly
    5 of its 24 changed files, by sha256       ->  5 of 5 identical to MAIN,
                                                   not to the branch

Files matching MAIN exactly is the decisive one: it means the branch was never
applied, not that it was applied and then merged with someone else's edit. That is
the same distinction that made `agent/jrows-on-batchbig` look absent when it is
present.

TWO WRONG READINGS OF MY OWN, ON THE WAY TO THAT LIST, both from a weak detector:
"is this branch in the assembly" was first answered by testing ONE added file
(missed branches whose first file is shared), then by byte-identity across all
changed files (missed branches whose files were legitimately merged with someone
else's -- it reported `agent/jrows-on-batchbig` absent at 2-of-17 when four of four
of its distinctive added LINES are present). Presence in a merged tree has to be
tested by CONTENT THAT SURVIVES MERGING, not by whole-file equality. And §8
predicted `jcap-ppa` would be the hold-out; the count was right and the name was
wrong.

### Regression-tested on the assembly, not only on a branch

The interesting case is a module that passes on each branch alone and fails when
two land together. Nothing tested before this touched that: the pre-existing
modules were run against a single branch. Re-run on `land/one-assembled`
(`e11626e28`), choosing the modules that cover the files where branches actually
overlap -- `gatekeeper_review.py` and `CAPTURE_ROUTING.json`:

    gatekeeper_review, three_orphan_checkers_have_a_machine_runner,
    two_gates_declare_where_their_verdict_is_consumed, ledger_is_not_a_runner
        -> 55 passed
    ppa_pr_scope_check, pg_rail_geometry_check, issue306_gate_enforcement_audit,
    issue459_landing_is_one_commit, matrix_d2_falsifiable
        -> 214 passed, 2 xfailed
    the four modules exercising this work (§9)
        -> 175 passed, 9 skipped

    444 passes on the assembled tree, no failures.

`suite_write_guard` confirmed each session wrote nothing into the tree.

### Three `land/*` refs exist, and two of them are live

Worth checking before landing, because only one carries the frozen batch. Measured
2026-08-22:

    land/one-assembled        672 commits ahead of a4caccefe   CARRIES the frozen batch
    land/batchbig-assembled    29 commits ahead                does NOT carry it
    land/batch67-assembled     39 commits ahead                does NOT carry it

`batch67-assembled` looks SUPERSEDED: six of six sampled distinctive lines from it
are present in `one-assembled`. `batchbig-assembled` does NOT look superseded --
only one of six -- so on this sample it holds content `one-assembled` lacks, and it
lacks everything `one-assembled` gained in the last four hours, this batch included.

HEDGE, because the detector matters here: this is a six-line sample, and the same
class of test called `agent/jrows-on-batchbig` absent when it was present. Treat it
as "worth confirming before either is landed", not as a finding. The cheap
confirmation is the one that failed for jppafind: take files each ref changes and
compare them by sha256 against the other and against main.

The consequence if it is real is one-directional and expensive: landing
`batchbig-assembled` ships none of the sixteen frozen branches.
