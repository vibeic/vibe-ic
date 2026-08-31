# LAND.md — rename `matrix_63x8` -> `flow_matrix` (attempt 5)

Working file. Written incrementally as the work happens; every section is
stamped with what was actually measured, not what was expected.

Host: 192.168.1.120. Started 2026-08-31T08:04+08:00.
`origin/main` at start of work: `3f169b1195` [v1.14.5].
Base ref: `agent/jflowmx4-rename-rebased` = `2377e324a4` (2 commits ahead of an
older main).

## 1. THE BLOCKER (named first, before any rename work)

### 1.1 What killed attempts 1-4

Named verbatim in the jflowmx4 rename commit `e50844a9b6`, section
"REFUSED (1) — the protected-runtime pair":

> `test_matrix_63x8_census_freshness.py` and `test_matrix_63x8_coverage.py` are
> pinned BY PATH, role `runtime`, in `tools/ci/protected_landing_transition.json`,
> and the same tuple is hard-coded as `RUNTIME_PATHS` in
> `tools/ci/protected_landing_transition.py` — an authority-role file the merge
> verifier reads from BASE, never from the candidate.

That is the BASE-read blocker: the landing verifier loads the path policy from
the BASE tree (today's main), not from the candidate being landed. So the
candidate can rename the two files all it likes — the verifier still checks the
base's five-file `runtime` tuple against the candidate's tree, does not find
those exact paths, and REFUSES with "manifest runtime role set is not the exact
five-file tuple". The refusal is reached by *every* landing whose base carries
the renamed code, so it does not merely block this rename — it would wedge the
queue after the rename landed.

The jflowmx4 measurement (on main `678b1b2bda`): with both files renamed,
`parse_manifest(manifest, 40)` REFUSES; unrenamed it ACCEPTS.

STATUS ON TODAY'S MAIN: _pending re-measurement — see §1.2._

### 1.2 Is the blocker still live on today's main? YES — and it moved location

Re-read on `origin/main` = `3f169b1195` [v1.14.5], 2026-08-31.

Two things changed since jflowmx4 measured it, and NEITHER of them removes it:

1. The register is no longer a hand-kept JSON list. `derived_paths()` now builds
   `manifest.paths` from the module's own `RUNTIME_PATHS | REQUIRED_AUTHORITY_PATHS`
   (`tools/ci/protected_landing_transition.py:105`). Good hygiene, irrelevant here.
2. `RUNTIME_PATHS` grew from five files to ELEVEN, and the refusal string that
   jflowmx4 quoted ("is not the exact five-file tuple") was itself fixed for going
   stale about a size — the same disease this rename treats. It now reads
   "manifest runtime role set does not match RUNTIME_PATHS".

The two `matrix_63x8` test modules are STILL pinned by path, still role `runtime`
(`protected_landing_transition.py:132`):

    vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py
    vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py

### 1.3 The blocker's TRUE shape, read from the code that enforces it

jflowmx4 described the symptom (`parse_manifest` refuses). The mechanism is one
line, and it is not in `parse_manifest` at all — it is in `build_receipt`:

    tools/ci/protected_landing_transition.py:776-779
        base_files      = _observe_files(repo, base_commit, base_manifest["paths"], ...)
        candidate_files = _observe_files(repo, cand_commit, base_manifest["paths"], ...)

THE CANDIDATE IS OBSERVED AT THE BASE'S PATH LIST. `_observe_files` raises
`Refusal("protected path is absent: <p>")` (line 604) for any path in that list
the candidate does not carry. So the moment the candidate renames a protected
runtime file, the receipt cannot even be BUILT.

And the path set is pinned from three directions at once, all read from BASE:
  * `parse_manifest`: `if runtime != RUNTIME_PATHS: raise` — exact equality (:407)
  * `build_receipt`:  candidate observed at `base_manifest["paths"]`      (:778)
  * `parse_receipt`:  `if base_paths != candidate_paths: raise`           (:1172)

The three operations the protocol offers are STEADY / PREPARE / ACTIVATE, and
none of them is a MOVE:
  * STEADY   — same bytes, same manifest.
  * PREPARE  — same bytes, new manifest; and explicitly
               `if candidate_manifest["paths"] != base_manifest["paths"]: raise
                Refusal("PREPARE changed the protected path/role set")`  (:793)
  * ACTIVATE — different BYTES at the SAME paths, same manifest.

So bytes may evolve; PATHS may not. **Renaming a protected runtime file is
structurally inexpressible in the landing protocol.** That — not a missing sed —
is what killed attempts 1 through 4, and it is why the correct response is not a
fifth, more careful rename.

### 1.4 MEASURED, bidirectionally, on today's main (not asserted)

Probe repo: a `--shared` clone of this repo at `origin/main` `3f169b1195`.
Three commits, one base and two candidates:

  probe-base       = 3f169b1195 (v1.14.5, untouched)
  probe-renamed    = base + `git mv` of ONLY the two protected runtime test
                     modules to their `flow_matrix` names. Nothing else.
  probe-unrelated  = base + one unrelated new file. NEGATIVE CONTROL.

Driver: `scratchpad/probe/measure.py` — loads BASE's own
`tools/ci/protected_landing_transition.py`, parses BASE's manifest, then calls
`_observe_files(candidate, BASE.paths)` exactly as `build_receipt:778` does.

RESULT (verbatim):

    BASE manifest parsed OK: 52 protected paths
    RUNTIME_PATHS size = 11; manifest runtime rows = 11
      PINNED-BY-PATH: .../tests/test_matrix_63x8_census_freshness.py
      PINNED-BY-PATH: .../tests/test_matrix_63x8_coverage.py
    [probe-unrelated] _observe_files(candidate @ BASE paths) -> OK (no refusal)
    [probe-renamed]   _observe_files(candidate @ BASE paths) -> REFUSAL:
        protected path is absent:
        vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py

The negative control is the load-bearing half: the refusal is caused BY THE
RENAME, not by the probe harness. A test that cannot pass against the unrenamed
tree would have proved nothing.

VERDICT: **the blocker is LIVE on v1.14.5.** It is not a leftover; it is
enforced by an authority file that this or any candidate is judged against from
BASE.

### 1.5 The consequence attempts 1-4 never wrote down

Because the protocol offers only STEADY / PREPARE / ACTIVATE, and ACTIVATE moves
BYTES at FIXED paths, this rename **cannot be one landing**. Not "is hard as one
landing" — cannot. Any single candidate that both (a) renames the protected pair
and (b) is judged against a base that names the old paths, refuses at
`build_receipt`, before a single test runs.

That is the un-named cause of failures 1-4: each was shaped as ONE landing of a
rename, and the shape itself is refused. A fifth attempt shaped the same way
fails the same way no matter how careful the sed is.

## 2. COORDINATION with kcensus5 (.105) — ordering verified

Checked 2026-08-31T08:1x+08:00, before starting rename work:

  * `git ls-remote origin`  — no ref matching `kcensus|census5|kc*`; the only
    census-named ref is `refs/archive/fix/1382-census-bound-on-1532` (archived).
  * `git ls-remote intB105` — 11157 refs. Every ref whose name mentions
    `census`, `matrix`, or `63x8` was listed; NONE is a kcensus5 ref.
  * The three plausible candidates were FETCHED and dated, not guessed:
      fix/1451-census-freshness-aggregate-bound  1e52968ae2  2026-08-13
      fix/63x8-waiver-citations-reverified       3d5ecf73d4  2026-08-13
      agent/jppa-p0-closed-loop-census           779e4eed51  2026-08-21
    All predate this work by 10+ days. None is the five-stale-reds fix.

**ORDERING VERIFIED: kcensus5 has NOT pushed a ref as of the check above.**
So the ordering I verified is: this ref is FIRST; kcensus5 rebases over it.

To make that rebase mechanical rather than a merge fight, §4 below is written as
an explicit OLD -> NEW path map. kcensus5's five red fixes are content edits
inside files this ref MOVES; `git rebase` follows the rename automatically when
the fixes are content-only. If kcensus5 pushes before this ref is landed, the
ordering INVERTS and this ref rebases instead — the rename is a pure `git mv`
plus mechanical text substitution, so it is the cheaper of the two to redo. Say
so to whoever lands second.

### 1.6 THE PRECEDENT — how the protected path set was changed before

`RUNTIME_PATHS` is not frozen historically: it went 5 -> 9 -> 11. So there had to
be a mechanism, and if one existed this rename should use it. There is not one.

  * 5 -> 9: `7c376e3481` "feat(landing): activate the semantic landing runtime
    [v1.10.69]". Done through the BOOTSTRAP path (`build_bootstrap_receipt`,
    `BOOTSTRAP_RECEIPT_KIND`), where an OLD trusted verifier judges a Phase-A
    tree that installs the NEW authority. That path is unavailable now: it
    refuses outright unless the base carries NO manifest at all —
    `if MANIFEST_PATH in base_entries: raise Refusal("bootstrap base already
    carries a transition manifest")` (:861). Today's main carries one.

  * 9 -> 11: `c51f830824` "fix(protected-landing): register the file the code
    protects, and catch the register up to the tree" (2026-08-28). Its own last
    line says how it got in:

        Landed with --no-verify under the owner's standing instruction to
        converge main.

**So the only in-band mechanism is gone, and the only live precedent is a
BYPASS.** `--no-verify` is exactly what the repo-gatekeeper role is forbidden to
use ("Never --admin/--force/--no-verify"), so it is not available to this rename
and I am not proposing it.

That same commit also records, unprompted, that the scheme cannot express this
class of change: "A register that has fallen behind cannot be caught up in one
commit by construction."

### 1.7 WHAT THE FIX HAS TO BE

The protocol offers byte-evolution at frozen paths. It needs path-evolution at
base-authorised destinations. The fix is to make a MOVE one of the things a BASE
manifest can authorise, so the candidate PERFORMS a move the base already
declared — preserving the property the whole design exists for: *the candidate
never supplies the policy it is judged by.*

Shape (kept deliberately minimal so the empty case is bit-identical to today):

  * `manifest.moves` — optional, default `[]`; rows `{"from","to"}`, sorted by
    `from`, `from` in the current path set, `to` not in it, both sides unique.
  * `current.files` covers the CURRENT path set (unchanged).
    `next.files` covers the MOVED path set. With `moves == []` these are the
    same list, so every existing check is untouched — that is the negative
    control the change must carry.
  * `runtime == RUNTIME_PATHS` still compares the CURRENT set against BASE's
    code. BASE authority is not weakened; the destination is authorised because
    BASE wrote the manifest that names it.
  * `build_receipt` observes the candidate at the current set, or — only when
    the manifest declares moves — at the moved set, and classifies that as the
    ACTIVATE of the authorised move.
  * `parse_receipt`'s `base_paths != candidate_paths` refusal relaxes to
    `candidate_paths == moved(base_paths)`, which needs `moves` carried in the
    receipt payload.

BLAST RADIUS, measured: 26 files reference `protected_landing_transition`;
the module is 2137 lines; the receipt payload shape is consumed by
`landing_merge_verdict.py`, `_protected_transition_fixture.py`,
`test_landing_gate_direct_push_tier.py`, `test_protected_landing_transition.py`,
`test_phase_b_activated_parity.py`, `protected_landing_manifest_author.py`,
`protected_landing_prepare.sh` and `gatekeeper-verify-merge.sh`.

This is a BLOCKING flow-level gate, so `vibe-ic:flow-change-acceptance` governs
it: bidirectional negative control, corpus sweep with zero false positives, and
prove-by-run that the gate still stops what it is supposed to stop.

### 1.8 WHERE THE BLOCKER BITES — measured on today's main, and it is not everywhere

`docs/research/2026-08-22-protected-tuple-unenforced-on-the-landing-path.md`
found that the validator is wired into the MERGE path and not into the plain
lander. That was 9 days and ~40 versions ago, so it was RE-MEASURED here at
v1.14.5 rather than quoted:

    tools/gatekeeper-land.sh                    0 references
    tools/gatekeeper-verify-merge.sh           12 references
    tools/ci/repo_hygiene_gates.sh              1 reference — line 1748, a
                                                  COMMENT about the runner
                                                  image, not a gate
    tools/ci/_gate_dispatch.sh                  0 references
    tools/gatekeeper-land-differential.sh       absent from the tree entirely

**Unchanged. The plain lander still does not consult the transition validator.**

So the blocker's true status is two-sided, and stating only one side would be
misleading either way:

  * ON THE MERGE PATH it is fully live and refuses — measured in §1.4.
  * ON THE PLAIN-LANDER PATH it is not enforced at all. This rename could
    physically be pushed today and nothing would stop it.

THE SECOND ONE IS A TRAP, NOT A DOOR. The same research note measured what
happens when a landing moves a protected path without a transition: main stops
matching either authorised state of its own manifest, and then

    candidate = the batchbig PREPARE     rc 2  protected tuple matches neither
    candidate = land/batchbig-assembled  rc 2  (same)
    candidate = agent/jrows-eight-rows   rc 2  (same)

— "Nothing can verify against today's main... the refusal is about the BASE, and
no candidate can route around it." Three queued batches were assembled without
transitions not because anyone ignored the mechanism but because, as that note
concludes, "it was not available."

Pushing this rename through the unenforced door would do exactly that again, and
this time to a path set that names files which no longer exist — deadlocking
every later protected-path landing for everyone. **A rename that wedges the
merge queue is worse than a stale name.** That is the second reason not to reach
for the bypass, on top of the role rule against `--no-verify`.

## 3. THE REF

    agent/jflowmx5-rename-flow-matrix   (branched from origin/main 3f169b1195)

      fbbe00d084  fix(protected-landing): a protected path could not be
                  renamed, only rewritten          <- THE BLOCKER FIX, commit 1
      92c0a436d4  rename(flow-matrix): the package was named for a size the
                  flow outgrew

Commit 1 is the blocker fix, as required: it makes a protected-path MOVE
expressible in-band by adding an optional `manifest.moves` and a fourth
operation, RENAME, in which the candidate PERFORMS the move BASE declared and
re-photographs the register in the same landing. `apply_moves` with no moves is
the identity, so a landing that declares no move is judged by exactly the old
code — that identity is the negative control.

Commit 1 is rename-free on purpose: it still names the OLD paths in
`RUNTIME_PATHS`, so it can be reviewed, and landed, without depending on the
rename at all.

## 4. THE RENAME, TOTAL — every hit with its disposition

Census taken on `origin/main` 3f169b1195: **1073 hits across 156 files**
(`grep -rIn 'matrix_63x8\|63x8\|63X8'`, excluding `.git`).

### 4.1 MOVED — 11 paths, all recorded by git as renames (R94-R99)

    programs/tests/matrix_63x8/{__init__,cells,flowref,substitution,waivers}.py
    programs/tests/matrix_63x8/README.md
                                        -> programs/tests/flow_matrix/...
    tools/gen_matrix_63x8_census.py     -> tools/gen_flow_matrix_census.py
    programs/tests/test_matrix_63x8_coverage.py         -> test_flow_matrix_coverage.py          [PROTECTED]
    programs/tests/test_matrix_63x8_census_freshness.py -> test_flow_matrix_census_freshness.py  [PROTECTED]
    programs/tests/test_matrix_63x8_figure_coverage.py  -> test_flow_matrix_figure_coverage.py
    programs/tests/test_matrix_63x8_ledger.py           -> test_flow_matrix_ledger.py

The two marked [PROTECTED] are the pair every previous attempt descoped. They
are renamed HERE, which is what commit 1 exists to make landable.

### 4.2 RENAMED IN PLACE — 307 occurrences across 78 live files, to zero

One substitution, `matrix_63x8` -> `flow_matrix`, covers the whole family
because every live spelling contains it: the package, `from flow_matrix import
...`, the four test module names, and `gen_matrix_63x8_census` ->
`gen_flow_matrix_census`. Measured before/after: **307 -> 0**.

No collision: `git grep flow_matrix origin/main` returns nothing, so the new
name was unused. No double-substitution: zero hits for `flow_flow_matrix` or
`flow_matrix_63x8`.

### 4.3 STAYS — historical records, excluded BY PREFIX, 45 files

Excluded by prefix rather than by a hand-kept file list, so a record that lands
later is covered without being named — the same reason the register in commit 1
derives itself instead of being maintained:

    docs/findings/  docs/measurements/  docs/capture/  docs/harvest/
    docs/research/  tools/harvest/  reports/timeout-as-verdict/
    RESULT_ROWS.md  tools/ci/J63B_63X8_RED_SET.md  docs/PHASE0_FINDINGS_U3_U5_U6.md

45 files, 650 hits, untouched. These are dated measurements and triage records;
renaming them would make them describe a run that did not happen.

### 4.4 STAYS — citations inside LIVE files, read individually

Each of these was read, not pattern-matched. They name events and artefacts that
happened under the old name and still did:

    `.audit_63x8.json`      an UNTRACKED historical artefact resolved BY
                            BASENAME (`_AUDIT_BASENAME` in flow_matrix/cells.py).
                            The file does not move, so a reference to it must
                            not. ~18 hits.
    `63x8 finding #20`      a numbered finding. matrix_mutation_ledger.py x2,
                            test_matrix_artefact_mutation_channel.py x1.
    `the 63x8 round-2 review`   design_one_shot_runner.py,
                            test_design_verdict_has_no_silent_catch_all.py.
    `the 2026-07 63x8 audit`    flow_matrix/cells.py:410, explicitly labelled
                            "HISTORY ONLY".
    `fix/63x8-waiver-citations-reverified`   a branch name, quoted as PR
                            evidence in pr_base_reachability_check.py x3.
    `test/matrix-63x8-coverage (241563f66)`  verbatim tool output measured at a
                            named sha. matrix_d4_probe.py, analog_a6_block_pv_check.py.
    `Measured at 6a61dbf2c: [PASS] 63x8 census fresh: 504 cells over 8
    dimensions`             repo_hygiene_gates.sh:2746 and the sibling quotes in
                            test_issue972 / test_issue1296 / gate_host_independence_check.
                            These quote OLD output — and the stale figure 504 in
                            them is the very evidence the name was lying.

## 5. THE GATE-LABEL CLUSTER — deliberately NOT renamed, with the reason

`63x8 census freshness` (the gate label) and `[PASS] 63x8 census fresh` (the
printed verdict) are a second, separate cluster. jflowmx4 renamed them. This ref
does NOT, and the reason is that the label no longer names a running gate:

  * `1e74ab469` (owner decision, 2026-08-16) DELETED `run "63x8 census
    freshness" ...` from `tools/ci/repo_hygiene_gates.sh`. Confirmed on
    v1.14.5: every `63x8 census freshness` in that file is now a COMMENT.
  * What is left is `repo_hygiene_parallel.py:80`
    `LOAD_SENSITIVE_LABELS = ("63x8 census freshness",)` — a matcher for a
    label nothing emits any more — and `hygiene_gate_profile.json:393`, which
    is a RECORDED PROFILE (`"state": "PASS", "seconds": 148`), i.e. a
    measurement, not a definition.

Renaming a dead matcher changes no behaviour, and renaming a measurement record
falsifies it. So the label stays, and it stays as a NAMED loose end rather than
an oversight: whoever re-wires that gate should introduce it under the new name
at that point, when the rename is a behaviour change somebody can actually test.

The one live thing in this cluster IS handled: the emitter
`tools/gen_matrix_63x8_census.py` moves to `gen_flow_matrix_census.py`, and the
source-anchored regex in `test_issue1296...py:341` that pins its `print(...)`
call still resolves, because that regex matches the printed STRING, which this
ref does not change.

### 5.1 jflowmx4's second refusal, RE-MEASURED not inherited

jflowmx4 left `tools/gatekeeper-land.sh:29` stale on the grounds that editing it
moves the lander's sha256 and reddens 10 tests. `tools/gatekeeper-land.sh` is in
`RUNTIME_PATHS` with a recorded digest, so the claim is structurally plausible —
but it was measured on a different tree, so it is re-measured here rather than
quoted. Result in §6.3.

## 7. THE LANDING ORDER — why this cannot be one landing, and what it is instead

This is the part attempts 1-4 never wrote down, and it is the reason a fifth
attempt shaped like them would have failed the same way.

A candidate that renames a protected runtime path is refused by
`build_receipt` before any test runs, because the candidate is observed at the
BASE's path list. No amount of care inside the rename changes that. The rename
is therefore not one landing; with commit 1 in place it is FOUR, in this order:

  L1  Land commit 1 alone (`fbbe00d084`) — the protocol gains `manifest.moves`
      and the RENAME operation. This is a BYTE change at a FIXED path
      (`tools/ci/protected_landing_transition.py`), which the protocol already
      expresses. It renames nothing and is reviewable on its own.

  L2  PREPARE. A manifest-only landing that declares the two moves and the
      `next` state naming the new paths. Live bytes and the `paths`/role set
      are unchanged, so it satisfies PREPARE's existing rules; it needs L1
      already in the base, because BASE's parser is what reads the new key.

  L3  RENAME. Commit 2 (`92c0a436d4`) — the `git mv`s, the 307 substitutions,
      `RUNTIME_PATHS` updated to the new paths, and the register
      re-photographed in the SAME landing. This is the operation L1 added.

  L4  Regenerate `PROGRAM_INVENTORY.json` against the landed tree.

L1 AND L2 CANNOT BE COLLAPSED, and L2 and L3 cannot either: BASE supplies the
policy, so each step must already BE the base before the next is judged. That is
the design working, not an obstacle to route around.

### 7.1 What this ref does NOT contain, stated plainly

L2 and L4 are not in this ref. L2 is a manifest authored against whatever commit
L1 actually lands as, so it cannot be written before that sha exists;
`tools/ci/protected_landing_manifest_author.py` needs a `--move from=to` flag to
emit it, which is a small addition this ref does not make. L4 is mechanical and
belongs to the landing.

So: this ref proves the rename is expressible and performs it; it does not
carry the two steps that can only be written once L1 has a sha.

### 7.2 The one thing NOT to do

The plain lander does not consult the validator (§1.8), so this rename can be
pushed today and nothing will stop it. Doing that would leave main's register
naming two files that no longer exist, and — measured in the 2026-08-22 research
note — that state makes EVERY later protected-path landing refuse on the BASE,
which no candidate can route around. It also requires `--no-verify`, which the
repo-gatekeeper role forbids. The bypass is a trap, not a shortcut.

## 6. ARMS — the collected count asserted on BOTH sides

A rename that silently drops a test from collection is a deletion wearing a
rename's clothes, so the count must be EQUAL, not merely plausible.

### 6.1 Collection — EQUAL

    BEFORE  main 3f169b1195, in a --shared clone
            test_matrix_63x8_{coverage,census_freshness,figure_coverage,ledger}.py
            -> 103 tests collected
    AFTER   this ref
            test_flow_matrix_{coverage,census_freshness,figure_coverage,ledger}.py
            -> 103 tests collected

**103 == 103.** No module vanished from collection, and none appeared.

### 6.2 Execution — run in full on both sides

    BEFORE  6 failed, 97 passed, 0 skipped, 103 total   (793s)

Main's own six reds in these four modules, for the record, because they are the
baseline this rename must not add to:

    census_freshness :: test_the_census_block_is_fresh
    census_freshness :: test_the_generator_cli_can_go_red_and_green
    census_freshness :: test_the_published_total_equals_the_live_census
    coverage         :: test_no_cell_is_counted_enforced_while_its_predicate_is_red
    figure_coverage  :: test_every_anchored_figure_in_the_committed_corpus_is_fresh
    ledger           :: test_output_entries_classify_into_the_four_kinds

Five of those six are census/figure-freshness reds — which is very likely the
set kcensus5 is fixing (§2). They are PRE-EXISTING on main and are not this
ref's to fix; they are recorded so the AFTER arm can be judged against them
rather than against zero.

    AFTER   [result recorded in §6.4 below]

A FIRST AFTER RUN WAS DISCARDED, and saying so is the point. It reported
"8 failed, 81 passed, 14 skipped" — but that run was executing in the worktree
while this ref's history was being rebuilt under it (`git checkout -B`), so the
test files were renamed back mid-run. The 14 skips were files disappearing, not
a property of the tree. It is kept at `scratchpad/arms/after_CONTAMINATED.log`
and is not evidence of anything. The AFTER arm was re-run on the final, quiet
tree.

### 6.3 jflowmx4's second refusal — RE-MEASURED, and the number was wrong

jflowmx4 left `tools/gatekeeper-land.sh:29` — a comment naming the old gate
label — deliberately stale, on the grounds that editing it moves the lander's
sha256 and reddens 10 tests. Re-measured here on main `3f169b1195`, both
directions, in an isolated clone:

    CONTROL  the line UNEDITED
             test_pytest_per_file_junit.py + test_ci_harness_timeout_ceiling_check.py
             -> 183 passed, 0 failed          (240s)

    TREATMENT  the same line, comment text renamed, one occurrence, nothing else
             -> 172 passed, 11 FAILED         (172s)

The refusal STANDS and is confirmed independently on today's tree — but it is
**11 tests, not 10**, and the 11th is not a rounding error:
`test_pytest_per_file_junit.py::test_the_landing_harness_declares_semantic_
progress_not_elapsed_time` reddens too, and the other ten are all in
`test_ci_harness_timeout_ceiling_check.py`. A quoted count that has drifted by
one is the same failure mode as a name that encodes a size, so it is corrected
here rather than carried forward.

The control arm is the load-bearing half: 183/183 green with the line untouched
proves the 11 reds are caused BY THE EDIT, not by the harness or the host.

So the disposition is unchanged and now rests on this tree's own evidence:
`tools/gatekeeper-land.sh:29` STAYS STALE, reported rather than fixed, because a
rename that silently breaks a pin is worse than a stale comment. It is a live
loose end with a named owner: it becomes free to fix in the same landing that
re-authorises `tools/gatekeeper-land.sh`'s digest — which is an ordinary
PREPARE/ACTIVATE of bytes at a fixed path, and needs none of this ref's
machinery.

### 6.5 The census generator, both sides

`gen_*_census.py --check` is the gate that decides whether the published matrix
figures are stale. Run on both trees, capturing the GENERATOR's exit code:

    BEFORE  main 3f169b1195, tools/gen_matrix_63x8_census.py --check
            rc=1
            [FAIL] 15 anchored figure(s) disagree with the tree
            .../matrix_63x8/README.md census block is stale

    AFTER   [recorded in §6.6]

Main is ALREADY red here, by 15 anchored figures plus a stale census block.
That is the same population as five of the six pre-existing test reds in §6.2
and it is not this ref's to repair.

A FIRST AFTER-CENSUS READING OF `rc=0` WAS DISCARDED AS FALSE. It came from
`... --check | tail -20; echo rc=$?`, where `$?` is the exit status of `tail`,
not of the generator. A pipeline's exit code is the LAST stage's, so that
reading could not have been anything but 0 and proved nothing about the census.
Re-run without the pipe.

### 6.6 TWO AFTER RUNS WERE INVALIDATED BY MY OWN EDITS, AND THE METHOD CHANGED

This is recorded because the reason is a trap anyone measuring this repo will
hit, and because reporting either run's numbers would have been reporting noise.

    AFTER run 1   discarded: the branch history was rebuilt (`git checkout -B`)
                  in the same worktree mid-run, so the test files were renamed
                  back underneath it. Reported "14 skipped" — files vanishing.
    AFTER run 2   discarded: 9 failed / 94 passed, against BEFORE's 6 / 97. The
                  three extra reds all carried the same message:

                      the outcome run for test_matrix_d4_criteria_match.py
                      exited rc=1 but every raw test report is non-red. This is
                      an unrepresented session-level refusal, not cell evidence

                  THE CAUSE WAS ME. These tests spawn nested outcome runs whose
                  `suite_write_guard` checks `git status --porcelain`. I was
                  editing `tools/ci/` in that worktree while the arm ran, so
                  the nested runs saw an unclean tree and refused at SESSION
                  level — which the census correctly reads as missing cell
                  evidence rather than as a passing cell. The gate was right;
                  the measurement was contaminated. Run standalone in a quiet
                  tree, `test_matrix_d4_criteria_match.py` is 76 passed.

    AFTER run 3   in `/home/reyerchu/_jflowmx5_arm`, a detached worktree at the
                  ref head that nothing else touches. Result in §6.7.

The lesson generalises past this ref: **any measurement of this repo must run in
a worktree nobody is editing**, because the suite's own write guard makes a
dirty tree indistinguishable from a broken one at the session level.

### 6.7 An operational hazard the rename creates, for whoever lands it

`git mv` moves TRACKED files only. It left an orphaned

    programs/tests/matrix_63x8/__pycache__/{cells,flowref,waivers,__init__}.pyc

behind in the working tree — a stale package directory sitting next to the new
one under the OLD name. It is invisible to `git status` (gitignored), it is not
in any commit, and it is exactly the split-name state this rename exists to
prevent, in the one place git will not warn about.

    ANYONE APPLYING THIS REF MUST `rm -rf` THAT DIRECTORY,
    or run `git clean -xdf` over `programs/tests/`, before measuring anything.

