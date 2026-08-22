# The routed-DEF corpus is empty because it was emptied, and the gate should stay BLOCKING

Adjudication of the one NOT CHECKED row on `origin/main` that carries no exemption:

```
NOT CHECKED (rc 2, BLOCKING; no exemption):
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
[population: producer rc 0, 0 items]
```

Measured 2026-08-22 on a clean worktree of `origin/main` @ `81cd5321b`
(`git clean` tree, `PYTHONDONTWRITEBYTECODE=1`).

## Verdict

**The corpus is legitimately empty right now.** The producer is correct, its path
is correct, and it is asking the right question of the right repository. It
returns zero because **every artefact that used to answer it was withdrawn on
purpose two days ago.**

Not "the producer is wrong" and not "the artefacts are under another name". Both
were checked against the artefacts, not against the producer's intent.

**CORRECTED 2026-08-22, later the same day.** The verdict above stands and the
withdrawal is real, but it was only *half* the reason the population is zero, and
the half it missed is the one that mattered. This document originally claimed the
gate was "satisfied again by one publication … with nothing in this repository
changed." That was never measured, and it is false: `benchmark_evidence_publish.py`
— the program that publishes a cell — does not stage `phase3/stage3/` at all, so
**no cell it has ever produced could be a member of this corpus.** The one member
the corpus ever held was hand-staged. See
[Correction: the satisfaction condition was unreachable](#correction-the-satisfaction-condition-was-unreachable),
which supersedes the paragraphs marked below.

## What was measured

### 1. The producer resolves the right tree, and the tree is real

`tools/ci/routed_def_corpus.py` resolves through `_corpus_location.resolve()`,
which follows `$VIBE_IC_BENCHMARK_DATA` to a clone of the published-corpus
repository. That repository is the one `routed_def_corpus._ORIGIN` names,
`https://github.com/vibeic/benchmark-data.git`, and a clone of it is present on
this host at the same default path the landing verifier uses
(`tools/gatekeeper-verify-merge.sh:prepare_benchmark_snapshots` →
`$HOME/_matrix_benchmark_data`). Its `origin` remote is that exact URL.

### 2. Pointed at the real corpus, the answer is still zero

```
$ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo <repo>
[routed-def corpus] note: VIBE_IC_BENCHMARK_DATA overrides <repo>/benchmark-data/ic -> <clone>/ic
rc=0, 0 items
```

Against the corpus repository's own tip, freshly fetched on 2026-08-22
(`origin/main` = `3b58ccd42`):

| query | result |
|---|---|
| `git ls-tree -r --name-only origin/main \| grep -c 'routed\.def'` | **0** |
| `git ls-tree -r --name-only origin/main -- ic/ \| grep -c 'phase3/'` | **0** |
| `v<version>_<PDK>` published cell directories under `ic/` | **0** |
| what remains under `ic/<design>/` | `input/` only |

So the population is zero at the published tip, not merely zero in this checkout.

**Read the second row with its scope attached.** `phase3/` paths under `ic/` are
zero; repo-wide there are **444** of them, under `protocol_parity/`. The commit
message of `0f4c0eeda` dropped that qualifier and stated "0 `phase3/` paths"
unscoped, which is false. What follows from these rows is only that the `ic/`
population is empty — see
[the second correction](#second-correction-the-corpus-is-not-free-of-post-route-evidence-only-of-defs)
for what is outside it.

### 3. It was not always zero, and it was emptied deliberately

At `bcf2f94^` the corpus contained exactly one member:

```
ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def
```

Relative to the `ic/` prefix that is `spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def`
— six components, with `parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`,
which is **exactly** the shape `routed_def_corpus._index_paths` matches. The
producer's query was matching this artefact until it stopped existing.

It stopped existing in the published-corpus repository at commit `bcf2f94`,
2026-08-20 19:28 +0800, *withdraw all four published cells, and write down what
may be published here*, whose first line is an owner instruction dated
2026-08-20: remove the current `ic` results, none of them is a pass. That commit
removed 1387 files and recorded, per cell, the measurement it was removed on —
two of the four carried a passing verdict over an audit in which none of 246
registered gates had run.

`ic/<design>/input/` was left in place on the stated ground that a design input
is not a result. That is why `ic/spm/` still exists while the population is zero.

### 4. The gate has therefore been unable to check anything since 2026-08-20

The wiring that makes an empty population a blocking dispatcher-owned refusal —
`routed_def_corpus.py`, `GATE_DISPATCH_ATTEST_POPULATION=1` at the wiring site,
and the `nunexempted` exit-2 branch in `_gate_dispatch.sh` — all arrived
together on 2026-08-18 in v1.10.69 (`7c376e348`). The corpus was withdrawn on
2026-08-20. The window in which this gate could have examined a cell was those
two days, and only for a run that had the corpus pointer bound.

## What would have to exist for this gate to check anything

One file, published into the corpus repository:

```
ic/<design>/v<plugin-version>_<PDK>/phase3/stage3/pnr/routed.def
```

with the rest of that cell beside it — the same shape `spm/v1.5.58_ihp-sg13g2`
had. Concretely, all of:

1. A run that reaches an independently re-derived Overall `PASS` or
   `PASS_WITH_WAIVERS`, staged by `benchmark_evidence_publish.py`, which
   refuses to stage a non-converged run.
2. Exactly one completion audit per cell, at `reports/audit/…` — the withdrawal
   commit named a second audit one directory too deep, reading FAIL 3.5 s before
   the PASS the public page displayed.
3. A non-zero `passed_gate_count`: a verdict is not evidence. Two of the four
   withdrawn cells carried a passing verdict over 0 gates actually run.
4. The cell committed under `v<plugin-version>_<PDK>`, validated by
   `benchmark_evidence_structure_check.py`.

The moment one such cell lands in the corpus repository and the pointer is
bound, this loop expands to a real population and the four per-cell gates
(`macro OBS not crossed`, `DRC PASS is not vacuous`, `inner FAILs reach the
verdict`, `new tool diagnostic id`) become live verdicts.

> **SUPERSEDED — the two paragraphs that stood here claimed this happened "with
> nothing in this repository changed", and that the gate was "satisfied again by
> one publication". Neither was measured and both are false. Read
> [the correction](#correction-the-satisfaction-condition-was-unreachable)
> instead; list items 1-4 above are still necessary, they were just not
> sufficient.**

> **ALSO NARROWED — this list reads as if one of the cells that already reached
> post-route could satisfy it. None of the six that did can, without being
> republished under the `ic/<design>/v<plugin-version>_<PDK>/` layout. See
> [the second correction](#second-correction-the-corpus-is-not-free-of-post-route-evidence-only-of-defs).**

## Decision: BLOCKING stays, and it buys no exemption

Neither of the two instruments is the right one.

**Not an exemption.** `uncheckable_until` exists to buy a dated tolerance for a
gate that reports NOT_CHECKED. Attaching one here is refused by construction —
`_dispatch` mode 2 raises a wiring error, *"a dispatcher-owned population
refusal … cannot consume an uncheckable exemption — an unknown denominator must
remain blocking"* — and that refusal is right for the reason
`repo_hygiene_gates.sh` already records against this exact corpus: the last time
these four gates were absorbed under exemptions, all four stated reasons were
FALSE, and the empty-population refusal was the only thing left that could
notice. An exemption dated into 2027 would restore precisely that silence.

**Not a declaration change.** This row is now the only statement anywhere on
`main` that post-route geometry is checked over nothing at all. Downgrading it
to advisory would let the project ship with zero published post-route evidence
and no signal saying so — and, worse, would still be advisory on the day the
corpus refills, i.e. it would stop blocking exactly when it regains the ability
to find something.

So the honest declaration is the one already there. The row is true, it is the
correct verdict for a zero population, and it should stay red until a cell is
published. What was missing is not a change to the gate; it is this record of
*why* it is zero, which existed nowhere in this repository. A reader who hits
the row today is told `EMPTY` and has no way to learn that the population was
withdrawn by instruction on 2026-08-20 or what would restore it.

This agrees with the adjudication already written into `gatekeeper_review.py`
(2026-08-20), which rejected softening the empty-corpus refusal on cited
evidence and resolved the corpus in the review arm instead. That note predates
the withdrawal by a few hours and so does not record it; this one does.

## Two things this adjudication does not do, and why

**It does not change the declaration or the producer.** `routed_def_corpus.py`,
`repo_hygiene_gates.sh`, `_gate_dispatch.sh` and `_corpus_location.py` are all
inside `REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`.
The merge verifier reads that manifest from the BASE commit and refuses a
candidate whose protected bytes BASE does not already authorise, so both
instruments the question offers are unavailable to any candidate commit: they
can only move through a base-authorised PREPARE/ACTIVATE transition. That is not
an obstacle to route around — it is the reason a single agent cannot quietly
retune the landing runtime, and it applies to this agent too.

**It does not publish anything to make the corpus non-empty.** Making this row
green by putting a routed DEF where the producer would find it, without a
converged run behind it, is the exact defect the withdrawal commit removed four
cells for.

## The first defect found while proving the above: filed as #1764, and FIXED in the base

**This section is a correction of itself, and the correction is the load-bearing
part.** What stood here reported a live defect. It was real when it was measured
— on `origin/main` @ `81cd5321b` — and it is **repaired on `a4caccefe`
(v1.11.69), which is the base this branch stands on.** Leaving the report as
written would have shipped a citation whose target no longer exists, inside the
document whose whole subject is a gate that says something untrue about its own
state.

### What was reported, and was true then

`routed_def_corpus.main()` passes `may_be_absent=True` to
`_corpus_location.refuse()`, which answered **rc 0** — so two of the four
outcomes `_corpus_location` exists to keep apart reached the dispatcher as the
same bytes:

| situation | producer stdout/rc | row the reader sees |
|---|---|---|
| corpus supplied, measured, contains no routed DEF | rc 0, 0 items | `is EMPTY — nothing was checked over it` |
| no corpus supplied, nothing scanned at all | rc 0, 0 items | *identical* |

Filed as **#1764**.

### What the base does now, re-measured on this worktree 2026-08-22

```
$ env -u VIBE_IC_BENCHMARK_DATA python3 tools/ci/routed_def_corpus.py --repo .
[routed-def corpus] NO_CORPUS: nothing at …/benchmark-data/ic and
  VIBE_IC_BENCHMARK_DATA is unset. … NOTHING WAS SCANNED, 0 routed DEF(s) were
  examined and nothing is claimed about them …
[routed-def corpus] NOT FOUND (rc 3): no corpus was resolved, so no index was
  opened and 0 routed DEF(s) is the ABSENCE of a measurement, not a measurement
  of zero.
rc=3

$ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo .
[routed-def corpus] MEASURED EMPTY: git's index at <clone> was read under 'ic'
  and it publishes no */*/phase3/stage3/pnr/routed.def. This IS a measurement …
  and it is NOT the same state as a corpus that could not be found (rc 3).
rc=0
```

`NO_CORPUS_RC = 3` in `tools/ci/routed_def_corpus.py` and
`GATE_DISPATCH_ABSENT_RC=3` in `tools/ci/_gate_dispatch.sh` are the same number
in two languages, pinned against drift by
`test_the_absent_exit_code_is_one_number_in_two_languages`; the two states are
pinned apart by `test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict`
and `test_the_dispatcher_gives_absent_and_empty_different_rows`.

### And the repair taken was the OPPOSITE of the one proposed here

This document proposed defaulting `may_be_absent` to `False`, which would make
an unconfigured checkout **rc 2**. `routed_def_corpus.main()` now carries the
reason that was declined, at the call site:

> vibe-ic#1764 argued for reversing it; reversing it would have made an absent
> corpus borrow the FAILED PRODUCER row instead, which is a second wrong
> sentence rather than the missing one.

rc 3 gives the absent state a row of its own rather than borrowing another
state's. Still blocking, still never a pass, and correct about **which** state
it is in — which rc 2 would not have been. The proposal here was tightening in
the right direction and wrong about the destination.

### What this does to the adjudication: it removes a hedge

The superseded text ended: *"Today, on `origin/main` with no pointer set, the one
blocking row on the board states the wrong reason for its own redness — which is
why this reads as a publishing question when it is first a configuration
question."* **That is no longer true, and its falsity strengthens everything
above it.**

The row this document adjudicates reads `[population: producer rc 0, 0 items]`.
On this base, rc 0 out of this producer can mean one thing only: an index was
opened, read, and publishes no routed DEF. An unconfigured checkout cannot reach
that row at all — it reaches the rc 3 row instead. So the redness is not a
configuration artefact: it is a measurement, and the question it poses is exactly
the publishing question the rest of this document answers.

## A second defect, found by writing the guard this adjudication rests on

The argument above leans on one structural fact: an `uncheckable_until` armed in
front of an attested-population loop **cannot** be consumed by the population
refusal, because `_dispatch` mode 2 rejects it.

**CORRECTED, and against this branch's own base.** An earlier revision of this
section called that fact *unpinned*. It was, when the earlier lineage of this
investigation measured it — and it stopped being so a few hours later, before
this branch was cut, in the landing that closed #1763:
`test_routed_def_corpus_dispatch.py::test_a_population_refusal_cannot_buy_an_uncheckable_exemption`
(`e1b98d8f9`, 2026-08-22 00:06). Shipping the claim would have been a citation
whose target had already been built. So it is replaced by a measurement of
**who actually catches the mutation**, taken by deleting the mode-2 `elif` from
the TRACKED dispatcher and restoring it with a reverse edit —
`sha256 e4088103…` byte-identical before and after, `git status` clean:

| test | control | mode-2 arm deleted |
|---|---|---|
| base `test_a_population_refusal_cannot_buy_an_uncheckable_exemption` | pass | **FAIL** |
| `…cannot_be_bought_off::test_an_exemption_cannot_buy_off_an_empty_population_refusal` | pass | **FAIL** |
| `…cannot_be_bought_off::test_a_refused_exemption_does_not_leak_onto_the_next_gate` | pass | pass |

The guard is not a free edit any more, and **this branch is not what made it
so.** What `test_population_refusal_cannot_be_bought_off.py` adds over the base
test should therefore be read as two things and not four:

* **ARM A2** states the record/console contradiction below as a DEFECT to be
  repaired rather than as behaviour to be characterised, with a `strict` xfail
  that XPASSes the day it is fixed. Now filed as **#1770**.
* **ARM C** pins that a refused exemption does not leak onto the NEXT gate (the
  #584 property, on the mode-2 path). Row 3 above shows it survives this
  mutation — which is the honest way to say it is about something else.
* **ARMs A and B overlap the base test's subject.** They drive the dispatcher
  without `--shard`, so they are an independent driver rather than new subject
  matter. Kept as controls; not claimed as coverage this branch introduced.

The half of the original paragraph that holds: the three general empty-corpus
files (`test_empty_corpus_gate_keeps_the_array_invariant`,
`test_issue1025_empty_corpus_sweep_blocks`, `test_issue1075_…`) do all drive the
loop with no exemption armed and are verdict-identical across the mutation.
That is why the base test had to be written at all.

Re-measured on this base, driving the real dispatcher over an attested-population
loop with `uncheckable_until 2999-01-01` armed in front of it, against a **copy**
carrying the deletion (tracked file untouched, same `sha256 e4088103…` after):

| | guard present | `elif` deleted |
|---|---|---|
| exit code | **2** | **0** |
| `wiring_errors` | 1 entry | `[]` |
| roll-up says | `NOT CHECKED (rc 2, BLOCKING; no exemption)` | `1 NOT CHECKED — this is NOT a pass` |
| `not_checked_unexempted` | `[]` | `[]` |
| row `exempt_until` | `2999-01-01` | `2999-01-01` |

One deleted `elif` turns the only blocking row on the board into a silent
**exit-0 pass**. Note what the roll-up does NOT do on this base: it still
prints `this is NOT a pass` while exiting 0, so the sentence and the exit
code disagree, and every automated consumer reads the exit code.

**And look at the bottom two rows: they are identical in both columns.** The
dispatcher raises the wiring error and then appends the date to `GATE_EX_UNTIL`
anyway, so even in the guarded run the record states the *refused* exemption as
a *granted* one — `exempt_until: "2999-01-01"`, `exemption_expired: false`, and
`not_checked_unexempted: []` for the row it had just declared unexemptable. The
printed line for that same row says `BLOCKING; no exemption`. The console and
the record give opposite answers about the same gate.

Nothing is unsafe today only because `gatekeeper_review`, `repo_hygiene_parallel`
and `hygiene_finding_delta` each independently refuse on `wiring_errors`. But
`not_checked_unexempted` is the field NAMED for this question, and
`gatekeeper_review`'s own comment documents it as the **fail-safe** derivation —
"every NOT_CHECKED in it reads as UNEXEMPTED and refuses … the opposite default
would make 'hand a record in the old format' the way to buy silence". Here it
fails the other way: a date that was never granted defeats the fail-safe, and
the whole refusal rests on one unrelated field staying fatal in every consumer
forever.

The fix is one line — append `""` instead of `$ex_until` on the refused branch,
which is strictly tightening and cannot turn any red green. `_gate_dispatch.sh`
is a protected authority file, so it is **filed as #1770, not fixed**, and
pinned as a `strict` xfail that will go RED (XPASS) the day it is repaired.
The issue also names the base test that moves with it:
`test_a_population_refusal_cannot_buy_an_uncheckable_exemption` asserts the
hazard AS current behaviour, so the repair reddens it and inverts its last two
assertions. A fix that updated only one of the two files would leave the suite
red either way.

## Correction: the satisfaction condition was unreachable

Everything above this heading was written without asking the one question that
decides whether the row is honestly BLOCKING: **can the supported publishing path
actually produce a member of this corpus?** It cannot, and could not on any day
in the gate's history.

### What the producer selects on

`tools/ci/routed_def_corpus.py` builds the entire population from one path shape
inside the published tree — `_index_paths` matches a path of exactly six
components under `ic/` whose tail is `("phase3", "stage3", "pnr", "routed.def")`:

```
ic/<design>/<version>/phase3/stage3/pnr/routed.def
```

### What the publisher stages

`benchmark_evidence_publish.py` is the program `PUBLISHING.md` names as the one
that stages a converged run into a cell ("You do **not** hand-assemble an evidence
folder"). Its `_COPY_SUBTREES` is:

```python
("phase1", "phase2", Path("phase3") / "reports", Path("phase3") / "analog", "reports")
```

`phase3/stage3` is not in it and never was. Its own docstring said so and named
the consequence without connecting it to this gate:

> Raw PnR scratch under phase3/stage3 is still not staged … NOTE that the three
> hand-staged reference cells DO carry `phase3/stage3/pnr/routed.def` … so on that
> subtree this program still publishes less than they do.

### Measured, not read

A synthetic converged run, published through the supported path with no flags,
carrying a routed DEF of 38 bytes — six orders of magnitude under the 50 MB
`_SIZE_CEILING`:

```
SOURCE   routed.def exists: True  38 bytes
PUBLISHED routed.def exists: False
any .def anywhere in the published cell: []
phase3/ subtree actually staged: ['reports', 'stage4']

LAYOUT_ROUTING.txt:
phase3/stage3/pnr/routed.def  38B  sha256:fee7400…  NOT_PUBLISHED  source-run-only
phase3/stage4/gds/top.gds    704B  sha256:b987ad6…  STAGED         in-cell
```

`NOT_PUBLISHED source-run-only` — not `ROUTED_AWAY`. It is not a size decision:
the size rule never saw the file, because the directory it lives in is not
published at any size. The GDS beside it, 704 bytes, staged.

### So the corpus had exactly one member and it could not have had a second

`ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def` entered the published
repository in its initial `snapshot: vibe-ic benchmark results, no history`
import — a hand-staged legacy cell, from before the publishing program — and left
in `bcf2f94`. Across the whole history of that repository, `git log --all
--diff-filter=A -- '*.def'` returns that one path and nothing else. No cell
`benchmark_evidence_publish.py` has ever produced was a member, and none ever
could have been.

That is the brief's option (3) after all, arrived at from the publishing side
rather than the producing side: **the artefacts exist under a path the supported
publisher does not write.** The producer is asking the right question of the right
repository — the writer was never able to answer it.

### What this changes about the adjudication, and what it does not

**It does not change the decision.** BLOCKING stays and it still buys no
exemption, for every reason in the section above. Nothing here makes the gate
pass: the corpus is still empty, the row is still `rc 2 NOT CHECKED`, and it still
blocks.

**It changes what the row is a statement about.** Before the repair, "NOT CHECKED,
BLOCKING, no exemption" was a permanent verdict wearing a temporary one's clothes.
Every list item in *What would have to exist* was necessary and none of them was
sufficient, so a reader following that list to the letter — publish a converged
cell, structure-check it, land it — would have produced a cell, bound the pointer,
and watched the row stay `EMPTY`, with nothing in the record to say why.

### The repair, and its exact boundary

`_ROUTED_DEF_RELPATH` in `benchmark_evidence_publish.py` stages
`phase3/stage3/pnr/routed.def`, size-routed exactly like the GDS. This is the same
omission the GDS block already carries its own comment about, one artefact over:

> `phase3/stage4` is not a copy subtree, so until this existed the GDS was omitted
> at EVERY size — the size routing could not reach the one artefact the manifest
> is actually about.

**One artefact, not the subtree.** `placed.def`, `floorplan.def`, `post_cts.def`,
the stage's `.tcl` and `phase3/stage3/extracted/*.spef` all stay `NOT_PUBLISHED`.
Widening published scope to raw PnR scratch remains the evidence-policy call the
docstring defers, and it is still deferred. A routed DEF over the ceiling is still
`ROUTED_AWAY`, because the guard that blocks the commit is a size rule and a cell
that ignored it would not land.

It is a restoration rather than a new policy: the hand-staged reference cells
carry this file, and on the rest of that subtree the program still publishes less
than they do.

### Pinned

`programs/tests/test_routed_def_corpus_is_reachable_by_publishing.py`, four arms,
all four RED before the repair:

| arm | subject | before |
|---|---|---|
| A | the DEF reaches the cell at the path the producer selects on | cell held `[]` `.def` files |
| B | CONTROL — an oversize DEF is `ROUTED_AWAY`, not staged | recorded `NOT_PUBLISHED`; the ceiling never saw it |
| C | CONTROL — the rest of the PnR scratch stays unpublished | staged `.def` set was `[]`, not `['routed.def']` |
| D | `routed_def_corpus.py` itself COUNTS the published cell | producer rc 0, stdout `[]` |
| E | CONTROL — a cell carrying it is still a LANDABLE cell | (green either way) |

ARM D is the load-bearing one, and the reason this is not a file-copying test: it
runs the gate's own producer over a real git checkout of the published tree. A
file at a path is not a population member until the producer says it is.

ARM E is green before the repair as well as after, which is what makes it a
control rather than evidence. It is there because the failure it rules out is
silent: a repair that made every future cell nonconformant to
`benchmark_evidence_structure_check` would have traded an unreachable corpus for
an unpublishable one — strictly worse, and invisible to ARMs A-D.

### The condition, restated so it is now true

One converged cell, meeting items 1-4 of *What would have to exist*, **published
by a `benchmark_evidence_publish.py` that carries this repair**, with its routed
DEF under the 50 MB ceiling. Cells published before it will not become members
retroactively; the artefact was never staged, so there is nothing in them to find.

### Verified: the repair does not make the gate pass

Run after the repair, on this branch, against a real clone of the published
repository at its own `main` (`3b58ccd42`):

```
$ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo .
rc=0    stdout: 0 lines

[routed-def corpus] MEASURED EMPTY: git's index at <clone> was read under 'ic'
  and it publishes no */*/phase3/stage3/pnr/routed.def. This IS a measurement …
[routed-def corpus] … its git index holds 0 routed DEF(s). … This is an EMPTY
  POPULATION, not a clean one: no published cell was examined and nothing is
  claimed about any.
```

Population still zero, row still `rc 2 NOT CHECKED`, still BLOCKING, still no
exemption. The repair changes what a FUTURE publication can do; it changes
nothing about today's verdict, which is the only outcome that would have been
worth refusing.

It does make one sentence the producer already prints true. *"The per-cell gates
go live again on the first cell published with a routed DEF"* was, until this
branch, a promise the publishing path could not keep.

### The regression sweep, and the base red it distinguishes itself from

The 13 test files touching `benchmark_evidence_publish`, `LAYOUT_ROUTING` or
`_COPY_SUBTREES`, as they stood when this was measured: **201 passed, 7 failed.**

> **This sweep is DATED, not withdrawn.** It was taken before the third finding
> below existed, over the 13 files matching at that time; the set is 16 now that
> this branch has added to it. The numbers were true of that tree and the
> attribution argument below is the one that still holds. For the tree as it
> stands read [the later sweep](#regression).

Six of the seven are `test_matrix_d3_outputs_produced[step15/17/19/20/30/32]`,
and the control is what makes them attributable: the **same six** fail on a
pristine `origin/main` worktree at `a4caccefe` (6 failed / 76 passed). Base red,
not this branch.

The seventh was mine and is repaired in `0119c53e9` —
`test_an_artefact_outside_published_scope_is_recorded_not_erased` used
`routed.def` as its example of an out-of-scope artefact. The example moved to its
sibling `placed.def`; the property is untouched; and the test now pins the
boundary from BOTH sides, so the carve-out cannot silently grow into the subtree
it was carved out of. Confirmed not vacuous: the re-pointed test is RED on
pristine `origin/main`.

### One residual condition, named rather than guarded

Staging the artefact is necessary and it is still not quite sufficient, and the
remaining gap is worth writing down because it is invisible if it ever bites.

`size_policy_drift_check` passes on this branch and says so with a caveat in its
own output:

> NOT covered by this gate: … per-cell `.gitignore` files nested under
> `benchmark-data/ic/**` — several published cells carry one that ignores layout
> artefacts locally. This gate reads the root file only.

Measured: `ic/edge_llm_accel/.gitignore`, added by the published repository's
initial snapshot import, is exactly that shape —

```
# Heavy / reproducible backend artifacts — excluded to keep this a lean,
# results-only commit …
*.gds
*.def
*.spef
```

A cell published UNDER such a rule would stage its routed DEF correctly and then
never commit it: `git add` skips it silently, the corpus stays empty, and nothing
in `LAYOUT_ROUTING.txt` — which records the PUBLISHER's decision, not git's —
would say why. `_git_ignored` exists in the publisher and already annotates
`provenance.jsonl` for this case, but it is a record, not a refusal.

**Not guarded here, deliberately.** No such file exists in the corpus repository
today (the only `.gitignore` it carries is
`ic/opentitan_aes/input/reference_flow/pre_syn/.gitignore`, holding `syn_out` and
`syn_setup.sh`), and `benchmark_evidence_publish.py` does not write one. Building
machinery against a shape nothing currently has would be speculative; naming it
in the satisfaction condition costs nothing and is checkable by anyone publishing
the first cell.

**So the full condition is:** one converged cell meeting items 1-4, published by
a publisher carrying this repair, routed DEF under the 50 MB ceiling, into a tree
with no `.gitignore` above the cell that excludes `*.def` — and then verified the
only way that counts, by running `tools/ci/routed_def_corpus.py` against the
committed result and seeing it print one path instead of `MEASURED EMPTY`.

### The condition demonstrated in the real repository, not a synthetic one

ARM D proves the producer counts a published cell in a tree the test builds. That
leaves one thing unmeasured: whether it works in the tree that actually matters,
with its real layout and its real ignore configuration. So it was done there.

A **throwaway local clone** of `vibeic/benchmark-data` at its own `main`
(`3b58ccd42`). One synthetic converged cell published into it by the repaired
`benchmark_evidence_publish.py`, committed locally. **Nothing was pushed; the
published corpus is untouched and still empty.**

```
baseline (before)   producer rc 0, 0 items, "MEASURED EMPTY"

publish rc                       0
staged into the real tree        True
git check-ignore                 rc 1  (not ignored)
tracked after commit             ic/widgetmul/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def

PRODUCER  rc 0
population  ['…/bd2/ic/widgetmul/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def']
```

One item instead of `MEASURED EMPTY`. `gate_dispatch_over` expands on exactly
that population, so the loop that reports `EMPTY — nothing was checked over it`
becomes three per-cell gate invocations over a real cell.

This also **measures** the residual named in the previous section rather than
leaving it as a caution: `git check-ignore` returns rc 1 against the real
repository's configuration, so no `.gitignore` above the cell excludes the
artefact today. The hazard is real in shape and absent in fact, which is the
strongest thing that can honestly be said about it.

**What this is not.** It is not a published cell and it is not evidence the
corpus has a member. It is a reachability measurement: the satisfaction
condition this document states can be met, in the repository it names, by the
program it names. Before the repair the same procedure ends at
`population: []` — which is what made the earlier version of this document
wrong.

---

## Second correction: the corpus is not free of post-route evidence, only of DEFs

Everything above adjudicates the population from the `ic/` tree, because that is
the tree `routed_def_corpus._index_paths` is pointed at
(`_index_paths(checkout / "ic")`). Scoped that way every number in it is right,
and re-measured on 2026-08-22 against `3b58ccd42` they still are.

But the sentence the LANDED adjudication of 2026-08-21 uses to justify
`BLOCKING` is not scoped that way, and as written it is false:

> "The subject of these four gates is post-route geometry on published silicon.
> Today nothing published carries post-route geometry."

**Six published cells carry post-route geometry today.** They are not under
`ic/`, which is why every `ic/`-scoped query in this document missed them:

```
$ git ls-tree -r --name-only origin/main | grep -c 'phase3/'          444
$ git ls-tree -r --name-only origin/main | grep -ciE '\.gds$'           6
$ git ls-tree -r --name-only origin/main | grep -c '/pnr/'             62
$ git ls-tree -r --name-only origin/main | grep -c 'routed\.def'        0
```

All 444 sit under `protocol_parity/<design>/`. Six of those designs carry a
completed back end: `phase3/stage4/gds/chip_top.gds`, `routed.drc.rpt`,
`stage3/extracted/chip_top.spef`, `stage3/sta/`, `stage3/lvs/` with per-cell
`.ext` extractions, `spare_cells.json`, `cts/clock_tree.rpt`.

### And each of the six carries a receipt for the exact file the corpus selects on

`reports/phase3/pnr/def_progression.json`, published in every one of them,
records the routed DEF as a stage that **exists**, with its size and digest:

| cell | recorded path | size | components | `has_routing` | sha256 |
|---|---|---|---|---|---|
| `protocol_parity/espi` | `phase3/stage3/pnr/routed.def` | 854,871 B | 3166 | true | `00ae72d6b35c07dc…` |
| `protocol_parity/interlaken` | `phase3/stage3/pnr/routed.def` | 2,627,603 B | 4078 | true | `21d6abec1af4ec27…` |
| `protocol_parity/lpc` | `phase3/stage3/pnr/routed.def` | 702,279 B | 2912 | true | `3dd156b38f88d5ce…` |
| `protocol_parity/mdio` | `phase3/stage3/pnr/routed.def` | 705,010 B | 2977 | true | `95a96654b7248127…` |
| `protocol_parity/sgmii` | `phase3/stage3/pnr/routed.def` | 900,384 B | 3219 | true | `963216b4ac67e7b9…` |
| `protocol_parity/usb_pd` | `phase3/stage3/pnr/routed.def` | 2,251,977 B | 6653 | true | `eed85d1fad8f1237…` |

Six routed DEFs were produced, hashed, and named — at `phase3/stage3/pnr/routed.def`,
character for character the path the producer selects on. Every one is between
0.7 MB and 2.6 MB, one to two orders of magnitude under the 50 MB
`_SIZE_CEILING`. **Not one of the six files is published.** The corpus publishes
the receipts and drops the artefacts.

### Two independent barriers, and this branch removes only the first

**Barrier 1 — the publisher drops it.** `_COPY_SUBTREES` never contained
`phase3/stage3/pnr/`, so the artefact was omitted at every size. That is the
defect the parent commits repair, and it is what these six receipts are
independent evidence of: the file existed at publish time and did not survive it.

**Barrier 2 — the path shape could not match it anyway.** The producer scans
`ic/` and accepts exactly six components,
`<design>/<version>/phase3/stage3/pnr/routed.def`. These cells are
`protocol_parity/<design>/phase3/stage3/pnr/routed.def`: a different root, and
five components with no `<version>`. **Even with Barrier 1 repaired and all six
DEFs published, none of them would enter the population.**

So the answer to "what would have to exist" is narrower than this document said.
It is not "publish one of the cells that already reached post-route". None of the
six can become a member without also being republished under the
`ic/<design>/v<plugin-version>_<PDK>/` layout, which is a republish, not a
publish, and is a corpus-governance decision made in the other repository.

### What is NOT done here, and why

The producer is **not** widened to scan `protocol_parity/`. Three reasons, in
order of weight:

1. **It would add zero members today.** No DEF is published there. Widening the
   selector would move the corpus from "empty" to "empty", which is a change
   with no measurement behind it.
2. **`tools/ci/routed_def_corpus.py` is in `REQUIRED_AUTHORITY_PATHS`**
   (`tools/ci/protected_landing_transition.py:58-74`, verified by reading it).
   It moves only through a base-authorised PREPARE/ACTIVATE transition — two
   landings, and not this candidate's to make. `benchmark_evidence_publish.py`
   is not in that set, which is why Barrier 1 is repairable here and Barrier 2
   is not.
3. **Whether a `protocol_parity/` cell is a *published cell* in the governed
   sense is not settled.** None of the six appears in `ic/INDEX.md`, in
   `ic/retention.json`, or in the `corpus: yes` column those two maintain. A
   selector that silently adopted them would enlarge a blocking gate's
   population by a definition nobody wrote down.

### What this does to the verdict: nothing, and it sharpens the reason

The corpus is still empty, the row is still rc 2 `NOT CHECKED`, it still blocks,
and it still buys no exemption. **An empty corpus must never become a pass**, and
nothing here moves toward making it one — the six cells are named precisely
because they are *not* members, and none of them is proposed as one.

What changes is the justification. `BLOCKING` was defended on the ground that
there is no post-route geometry to check. There is; six cells of it, with the
DEFs measured and discarded. The honest defence is stronger than the one it
replaces: this gate is blind to the only post-route evidence the project has
published, and a row that says `NOT CHECKED` is the single place that fact is
visible. Making it advisory would retire the only statement anywhere that
post-route geometry goes unchecked, at the moment it is most true.

### Reproduction

```
git clone https://github.com/vibeic/benchmark-data && cd benchmark-data
git ls-tree -r --name-only origin/main | grep -c 'routed\.def'      # 0
git ls-tree -r --name-only origin/main | grep -c 'phase3/'          # 444
git show origin/main:protocol_parity/espi/reports/phase3/pnr/def_progression.json
```

Measured 2026-08-22 against `vibeic/benchmark-data` `origin/main` = `3b58ccd42`,
freshly fetched. **This is an observation about another repository's published
tree, not a property of this one, so it is deliberately not pinned by a test
here** — a test asserting it would either need network access or would encode
another repository's contents as this one's fixture, and both are worse than a
dated measurement with its command line written down.

---

## Third finding: after the repair, "I could not find it" and "I declined it" were still the same word

The Barrier-1 repair puts `phase3/stage3/pnr/routed.def` INTO published scope. That
makes a state exist that did not exist before it: **the run has a routed DEF and it
is not at that path.** Until this section, `LAYOUT_ROUTING.txt` wrote that state and
a deliberate policy exclusion with the same word.

### Measured, on the shape the published corpus actually carries

A converged run identical to ARM A's except that its routed DEF sits at
`phase3/phase3/stage3/pnr/routed.def` — the doubled prefix
`protocol_parity/lpc` carries in 28 committed files, 11 of them in
`phase3/phase3/stage3/pnr/` itself — published through the
supported path with no flags:

```
publish rc:            0
cell exists:           True
published .def files:  []

LAYOUT_ROUTING  phase3/phase3/stage3/pnr/routed.def   NOT_PUBLISHED
LAYOUT_ROUTING  phase3/stage3/pnr/placed.def          NOT_PUBLISHED
LAYOUT_ROUTING  phase3/stage3/pnr/floorplan.def       NOT_PUBLISHED

any mention of routed.def on stdout/stderr:  (none)
```

The artefact the post-route gates are about, and the scratch the publisher
excludes on purpose, are indistinguishable in the only record that speaks for
either. The cell reads as one whose run had no post-route geometry.

**And the corpus consequence is the collapse this branch already pinned.**
`routed_def_corpus.py` answers `rc 0` with an empty population for a cell like
that — byte-for-byte what it answers when nothing was ever published
(`test_routed_def_population_is_depth_exact.py`). So the blocking row keeps
saying `is EMPTY — nothing was checked over it`, which is true, and no artefact
anywhere says a routed DEF existed and was dropped.

### The repair: one word, and the sentence the publisher was not saying

`OFF_CANONICAL_PATH`, emitted only when nothing is at the canonical path and the
run holds a `routed.def` elsewhere, deduped on the resolved path so a `steps/`
alias is not a second artefact. Plus a stderr warning naming every path found and
the one path the population is built from.

This is the repair `CITATION_ROUTING.txt` — the sibling record, written for the
same cell — already argues for citations, in its own header:

> a directory that ships its neighbours and not this file is a HOLE, and is
> recorded as `DANGLING` / `DANGLING_UNDER_PASS`. The distinction is load-bearing
> downstream … the wrong word here retires a finding instead of reporting one.

### What it is not

**Not a widening of scope.** Nothing new is staged. The cell is byte-identical;
only the record and stderr change.

**Not a refusal.** The run may be converged and the cell worth publishing. A
`Refuse` here would also block a legitimate multi-macro layout that keeps a DEF
per block, which is a real shape nobody has argued against. What must not happen
is the drop being *silent*, and that is all this changes.

**Not a way to make the gate pass.** The corpus is still empty, the row is still
`rc 2 NOT CHECKED`, it still blocks, and it still buys no exemption. Publishing a
cell with `OFF_CANONICAL_PATH` in its record adds no member, which is the point:
it makes the reason visible instead of making the row green.

**Not retroactive.** No cell in the published corpus carries a `routed.def` at
any path, so this fires on future publishes only.

### Pinned, RED first

`programs/tests/test_routed_def_off_the_canonical_path_is_not_out_of_scope.py`.
ARM A is the finding; B–E are controls and were GREEN before the repair, which is
what makes them controls rather than evidence:

| arm | subject | before |
|---|---|---|
| A | the off-canonical DEF is `OFF_CANONICAL_PATH`, and stderr names both paths | **`NOT_PUBLISHED`** — `1 failed, 4 passed` |
| B | CONTROL — a canonical DEF is `STAGED` and nothing is `OFF_CANONICAL_PATH` | green |
| C | CONTROL — a run with no DEF at all emits no such row | green |
| D | CONTROL — an OVERSIZE canonical DEF stays `ROUTED_AWAY` | green |
| E | CONTROL — a `steps/` symlink back to the staged DEF is not a second artefact | green |
| F | CONTROL — a DEF inside a PUBLISHED subtree gets exactly ONE line | **caught the first draft** |

ARM A also asserts that `placed.def` KEEPS the word that is true of it, so the arm
cannot be satisfied by renaming every exclusion.

### ARM F is there because the first draft of this repair was wrong

The first draft rglobbed for the basename without asking what was already
recorded, and emitted a SECOND row for a blob `_copy_tree` had already decided
about — `ROUTED_AWAY` *and* `OFF_CANONICAL_PATH` for one file, breaking the
invariant `LAYOUT_ROUTING.txt`'s own header states: *"ONE LINE PER BLOB, not per
path"*. It was caught by an existing test, not by me:

```
FAILED test_organic419b_signoff_gds_ships_and_routing_is_recorded.py::
       test_an_oversized_artefact_is_absent_but_recorded_with_its_hash
assert 2 == 1
  reports/phase3/routed.def 60000000B sha256:1dd28892… ROUTED_AWAY        not-retained
  reports/phase3/routed.def 60000000B sha256:1dd28892… OFF_CANONICAL_PATH source-run-only
```

The seed is `{Path(r["src"]).resolve() for r in layout_records}`, and it draws
the boundary the new word needs: `OFF_CANONICAL_PATH` is for an artefact the
publisher **never looked at**, not for one it looked at and decided about. ARM F
pins it here too — measured RED with the seed removed and restored byte-identical
after — because the test that caught it is about the GDS block and should not
have to keep covering this one.

### Regression

The **16** test files touching `benchmark_evidence_publish`, `LAYOUT_ROUTING` or
`_COPY_SUBTREES` (`programs/tests/test_*.py`; the grep also matches
`_pdk_revision_fixture.py` and `matrix_d7_write_record.py`, which pytest does not
collect): **`228 passed, 6 failed, 66 skipped`** after the dedupe repair. The
seventh failure in the first sweep was ARM F's subject and is fixed.

> **The two numbers in this paragraph were wrong when first written and are
> corrected here.** It said "18 test files" and "226 passed". 18 was the grep's
> file count, not the set pytest ran; 226 was drafted from the *pre-hardening*
> sweep and never re-read against the run that followed it. Both are the defect
> class this whole document is about — a number written beside a measurement
> instead of taken from it — so they are corrected in place rather than quietly
> overwritten.

The six are `test_matrix_d3_outputs_produced[step15/17/19/20/30/32]`. **Measured
rather than inherited:** a pristine detached worktree at `a4caccefe`, that file
alone, gives `6 failed / 52 passed / 61 skipped` — the same six. Base red, not
this branch.
