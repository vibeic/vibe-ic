# A correct pointer at the published corpus was diagnosed as a broken one, and
# it takes the landing test arm's collection with it

Continuation of the routed-DEF corpus adjudication. That record reached verdict
(2) — the corpus is legitimately empty — and named two things it deliberately
did NOT take. **This takes the second one**, and measuring it moved it from
"an operator who follows the printed advice gets a confusing error" to
"every ingredient of a landing-arm collection outage is present and measured".

Measured 2026-08-22 on a clean worktree of `origin/main` @ `a4caccefe`
(v1.11.69), `PYTHONDONTWRITEBYTECODE=1`.

## The defect

`programs/tests/_published_corpus.corpus_root` names THREE causes for "you set
`VIBE_IC_BENCHMARK_DATA` and there are no cells", and refuses:

> They named a corpus. The name is wrong, or the clone failed, or the CI step
> that was meant to fetch it did nothing.

On 2026-08-20 a fourth appeared that is none of the three: the pointer is right,
the clone succeeded, the fetch worked, and `vibeic/benchmark-data` genuinely
publishes zero cells because the publisher withdrew all four of them. The
refusal then closes by advising the reader to

> point it at a clone of vibeic/benchmark-data.

**The remedy it prints is the action that produced it.**

This is the same defect `tools/ci/routed_def_corpus.py` separates into rc 0 (an
index was read and holds none) and rc 3 (nothing was opened) — vibe-ic#1764 —
surviving one layer down in the test helper, where nobody looked for it.

## The corpus, measured at the publisher

`git clone --filter=blob:none --single-branch --branch main` of
`https://github.com/vibeic/benchmark-data`, HEAD `3b58ccd42`:

| query | result |
|---|---|
| blobs in the whole repository | 6929 |
| designs under `ic/` | 9 |
| cell directories `ic/*/v*` | **0** |
| blobs named `routed.def` | **0** |
| blobs ending `.def`, any path | **0** |
| `PUBLISHING.md` at the root | present |

## The reach, and it is the landing path

Each link measured separately rather than inferred from the one before it.

1. **The landing TEST arms bind the pointer.**
   `tools/ci/hermetic_candidate_runner.py` sets
   `_TEST_PROCESS_ENV = {"VIBE_IC_BENCHMARK_DATA": CORPUS_PATH}` and
   `_fixed_process_env` applies it to every arm that is not `A2`/`B2` — i.e.
   to `A1`/`B1`, the test arms. `CORPUS_PATH` is `/corpus`.

2. **`/corpus` is the publisher, and the runner asserts it.**
   `tools/ci/benchmark_data_landing_checkout.py` pins
   `CANONICAL_ORIGIN = "https://github.com/vibeic/benchmark-data.git"` and
   refuses a checkout whose `git remote get-url --all origin` is anything else.

3. **The cron-owned checkout on this fleet is that zero-cell tree.**
   `_checkout_arg` defaults to `~/_matrix_benchmark_data`. On this host it is a
   real clone of the canonical origin at
   `bcf2f94 "withdraw all four published cells, and write down what may be
   published here"`, carrying `PUBLISHING.md` and **0** `ic/*/v*` directories.

4. **Bound at that exact directory, collection dies.** The 55 modules that
   import the helper, `--collect-only`, same file list both sides:

   | tree | pointer | collected | collection errors |
   |---|---|---|---|
   | `origin/main` @ `a4caccefe` | `~/_matrix_benchmark_data` | **52** | **52** |
   | this branch | `~/_matrix_benchmark_data` | **1357** | **0** |

   52 of the 55 modules die AT IMPORT — `needs_corpus` is built at module scope,
   so the exception escapes collection and pytest never reaches a test. Most of
   the ~1300 tests lost that way have no published cell as their subject; they
   are collateral of where the marker is evaluated.

   Cross-check, taken independently against a synthetic corpus carrying one
   cell: 1345 collected, 0 errors. 1357 − 12 new cases in this branch = 1345.
   Two different corpora, same denominator.

5. **And they RUN, not merely collect.** Collection is not execution, so ten of
   the `needs_corpus` modules were executed rather than counted, pointer bound
   at the same real landing checkout:

   ```
   196 passed, 20 skipped, 4 xfailed in 59.32s   (loadavg 18.16, nproc 32)
   ```

   On `main` those same ten modules yield zero executed tests: they are
   collection errors. The 20 skips carry the new sentence verbatim —

   > `VIBE_IC_BENCHMARK_DATA` names the published benchmark corpus and it was
   > READ — it publishes 0 cells under `ic/<design>/v<version>_<PDK>/`, so this
   > check has no published cell to examine. This is a MEASUREMENT of zero, not
   > 'I could not look', and it is not a pass: nothing was verified about any
   > cell. The pointer is correct; the corpus is empty.

   — which is the point: 196 tests that have nothing to do with a published cell
   now run, and the 20 that do are skipped over a **counted zero** rather than
   erroring over a configuration that was never broken.

### Targeted regression, both pointer states

| tree | pointer | result |
|---|---|---|
| `origin/main` | unset | 20 passed, 1 skipped |
| this branch | unset | 32 passed, 1 skipped |
| this branch | real landing corpus | 32 passed, 1 skipped |

20 + the 12 new cases = 32, and the skip count does not move. The default
no-pointer path — the one every developer and the current landing pytest run use
— is byte-for-byte the behaviour it had.

**THE LIMIT OF THIS CLAIM, stated rather than left for a reader to assume.** The
hermetic image was NOT run. What is measured is that every ingredient is
present: the arm binds the pointer, the pointer resolves to the canonical
publisher, the publisher has no cells, and that combination kills collection on
`main`. Whether the arm is red *today* depends on the arm's own mount and
selection, which this record did not exercise. It is an unlit fuse that has been
traced end to end, not an observed fire.

## The fix, and why it is not the loosening this module forbids

The obvious edit — return `None` whenever there are no cells — is precisely the
exploit `_published_corpus` was written to prevent, measured once as
`VIBE_IC_BENCHMARK_DATA=<empty dir> pytest -> 29 passed, 2 skipped`: a whole
corpus suite switched off by a mistyped path. **It is not taken.**

What is taken is a POSITIVE identification of the tree as the published corpus,
which no accident produces — the publishing contract at its root AND the `ic/`
root that cells live under:

```
set + not a corpus (missing path, empty dir, dead clone) -> raise.  UNCHANGED
set + IS the corpus + it carries cells                   -> the path. UNCHANGED
set + IS the corpus + its cell population is 0           -> skip, SAYING SO. NEW
```

The new row carries its own sentence, `MEASURED_EMPTY_REASON`, which states the
count and states that it is not a pass. It never borrows `SKIP_REASON`'s
"could not look", because the corpus *was* looked at. Both non-running states
remain non-running: **a skip is not a pass, and nothing is verified about any
cell either way.**

Git is deliberately NOT required. This helper walks the filesystem rather than
an index — unlike `programs/_corpus_location.not_a_checkout_reason`, whose
callers read `git ls-files` and must refuse a loose directory — so an archive
export of the corpus is readable here and refusing it would be wrong.

### What can still reach the refusal, asserted

Each of these is a test in
`test_measured_empty_corpus_is_not_a_broken_pointer.py`, and four of the twelve
are GREEN on unfixed `main` **by design**: they are the anti-loosening guards,
and a future widening of the new row is what turns them red.

| tree | outcome |
|---|---|
| path does not exist | raise |
| empty directory | raise |
| a real tree that is not the publisher (`datasets/`, `runs/`, a README) | raise |
| the contract, but no `ic/` root | raise |
| an `ic/` root, but no contract | raise |
| contract + `ic/`, zero cells | MEASURED_EMPTY, skip |
| contract + `ic/`, one cell | PRESENT, the path |

"Contract but no `ic/`" refusing is the honest outcome rather than a gap: a cell
is *defined* as `ic/<design>/v<version>_<PDK>/`, so a tree with no `ic/` cannot
be measured for cells at all, and calling it measured-empty would be a
manufactured measurement in the opposite direction.

## The red, and why an earlier draft's red was worthless

The headline test calls `corpus_root()` — which exists both before and after
this repair — so on unfixed `main` it fails with the real refusal:

```
E  Failed: a correct pointer at the published corpus was diagnosed as a broken
   pointer -- the remedy it prints is the action that produced it:
   VIBE_IC_BENCHMARK_DATA=... names a corpus with no published cell under
   ic/<design>/v<version>_<PDK>/ ...
```

The first draft built its fixtures from `C.CORPUS_CONTRACT` and went red on all
11 cases with `AttributeError: module '_published_corpus' has no attribute
'CORPUS_CONTRACT'`. That red proves only that a constant is new — it is the
"checker validates the thing NEXT to the claim" shape. The fixtures now
hand-spell `"PUBLISHING.md"` and one test ties the two spellings together.

Verified green: 20 passed on the fixed tree — the 12 new cases plus all 8
pre-existing guarantees in `test_published_corpus_helper.py`, none of which
moved.

## What this deliberately does not do

- **It does not touch the routed-DEF verdict.** That corpus is still empty, the
  gate still reports NOT CHECKED, and nothing here publishes anything to make it
  non-empty. An empty corpus stays rc 2 / NOT CHECKED and never becomes a pass.
- **The other named-and-not-taken item IS taken, and the reason I first gave for
  leaving it was wrong.** I wrote here that the summary string is *"parsed by
  `tools/gatekeeper-land.sh` and `tools/gatekeeper-verify-merge.sh` and read by
  25 test files"*, inherited from the earlier record and repeated without being
  checked. Measured: **neither shell script parses it** — every `conformant` hit
  in both is an unrelated comment about PRs — and of the 25 test files that
  contain the word, **2** mention the summary line, one of them as a fixture
  literal. The real blast radius is substring assertions in
  `test_issue967_empty_ic_unit_examined_nothing.py`, runnable in seconds.

  With the reach actually measured, the repair is in this branch:

  | tree | before | after |
  |---|---|---|
  | `146d665`, 4 published cells | `13/13 conformant, 0 nonconformant` | `… — over 4 published cell(s) and 9 IC-level root(s)` |
  | `3b58ccd42`, 0 published cells | `9/9 conformant, 0 nonconformant` | `… — over 0 published cell(s) and 9 IC-level root(s)` |

  Disclosure, not a verdict change: no gate that said PASS stops saying it, no rc
  moves, the fraction is byte-identical and the clause is appended after it. The
  zero is printed *especially* when it is zero — a clause that appeared only when
  there are cells would leave the empty corpus with exactly the silence being
  disclosed. Across the 15 test files that exercise this checker: 235 passed / 62
  skipped on the branch vs 230 / 62 on `main` (the +5 are the new cases), and the
  6 failures in `test_matrix_d3_outputs_produced.py` are the SAME test-ids on both
  trees — pre-existing, none introduced.
- **`benchmark evidence structure` reports NOT CHECKED on this branch's
  pre-push, and it does so identically on clean `main`.** Run on a clean
  `a4caccefe` worktree with the same arguments the hook uses, it prints
  `UNDETERMINED: --tree benchmark-data is not a directory`. The batch did not
  introduce it; the tree simply has no `benchmark-data/` since v1.10.56. Binding
  `VIBE_IC_BENCHMARK_DATA` at a clone — the action the gate's own message asks
  for — is what lets the push proceed, and that is also the configuration this
  record repairs the test helper for.

## For whoever lands this

**Nothing here touches a protected path, and that was checked rather than
assumed.** `REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`
carries `tools/ci/routed_def_corpus.py`, `tools/ci/_gate_dispatch.sh`,
`tools/ci/repo_hygiene_gates.sh`, `tools/ci/hermetic_candidate_runner.py` and
`tools/ci/benchmark_data_landing_checkout.py` — every file this record *reads*.
It does not carry either file this branch *edits*:

| edited | protected? |
|---|---|
| `programs/tests/_published_corpus.py` | no |
| `programs/benchmark_evidence_structure_check.py` | no |

So this lands from one candidate commit with no authority ceremony. That is not
an accident of drafting: the repair was deliberately placed at the consumer
rather than at `routed_def_corpus.py`, which is exactly why the earlier sibling
`fix/routed-def-corpus-empty-adjudication` could not land — it edited the
protected producer to change an absent corpus to rc 2, and #1764 later reached
the same distinction through the authorised route with rc 3.

**The absolute rule is re-proved on this branch, not merely left alone.** With
the pointer bound at the real publisher:

```
$ VIBE_IC_BENCHMARK_DATA=<clone @ 3b58ccd42> python3 tools/ci/routed_def_corpus.py --repo <this branch>
producer rc = 0
items on stdout = 0
[routed-def corpus] MEASURED EMPTY: git's index at <clone> was read under 'ic'
and it publishes no */*/phase3/stage3/pnr/routed.def. ... This is an EMPTY
POPULATION, not a clean one: no published cell was examined and nothing is
claimed about any. The per-cell gates go live again on the first cell published
with a routed DEF.
```

rc 0, 0 items, still NOT CHECKED, still blocking, and the row still names its own
restoration condition. The four dispatcher/empty-corpus pinning modules —
`test_issue1075_empty_corpus_leaves_a_gate`,
`test_empty_corpus_gate_keeps_the_array_invariant`,
`test_routed_def_corpus_dispatch`, `test_issue886_undeclared_gate_is_not_exempt`
— are **58 passed** on this branch (loadavg 16.24, nproc 32). An empty corpus did
not become a pass and cannot have.

## The hole the fourth state opened, found by attacking it rather than restating it

`_has_cells` walks the FILESYSTEM. So a corpus clone whose cells were deleted,
half-checked-out or never materialised is byte-identical to a corpus that
publishes none — and the first version of this repair called that a MEASUREMENT
of zero. It is not: it publishes cells you do not have.

Measured on a checkout of the publisher at `146d665` with `ic/*/v*` removed from
the working tree:

| | |
|---|---|
| cells on disk | **0** |
| cell files still tracked in git's index | **1384** |

| tree | verdict on that checkout |
|---|---|
| `origin/main` | raise — right outcome, wrong sentence (*"empty of cells"*) |
| `95a57f089` (this branch, before hardening) | `measured-empty`: *"IS the published corpus … publishes 0 cells"* |
| `173818697` (now) | raise, naming the index/tree disagreement |

That is the loosening this module exists to refuse, introduced by the commit that
was meant to tighten it — a skip where there should be a refusal. It was found by
asking what could satisfy `is_published_corpus` while the population claim was
false, not by re-reading the diff.

**The fix is #1764's distinction one level further in:** ask git's INDEX. Index
carries cells while the tree carries none → damaged checkout, raise and say
which. Index agrees there are none → genuinely measured empty.

**Git stays optional and the cross-check must not smuggle it back in.**
`_index_publishes_cells` returns `None` — not `False` — when git cannot be asked,
and `None` leaves the filesystem answer standing, so an archive export of the
corpus is still readable. `False` would be a claim about a population nobody
read. The pathspec is `:(glob)ic/*/v*/**`; without the glob magic a bare `*` in a
git pathspec matches `/` too and a cell-shaped directory three levels down would
count. Both properties are pinned.

**One of the new tests was wrong first.** It asserted that
`ic/<design>/verification/` must not count as a cell in the index — but
`_has_cells` accepts *any* directory whose name starts with `v`, so the
filesystem counts it too. Demanding strictness of one side would have
manufactured a tree/index disagreement out of nothing, and a disagreement is
exactly what now reads as a damaged checkout. The property is **agreement**, not
strictness.

The headline result is unchanged by the hardening: pointer at the real landing
checkout, `--collect-only` over the same 55 modules gives **1362 collected, 0
errors** (1357 + the 5 new cases), against 52 collected / 52 errors on `main`.

## LEDGER ROW: what became visible once collection stopped dying

Making the corpus readable makes tests run that never ran, and some of them fail.
Per the standing ruling — *a gate going NOT CHECKED → FAIL because it can finally
SEE a real corpus is PROGRESS; it lands with a ledger row, and the exception is
an instance the batch INTRODUCED* — here is the row, and the work establishing
which kind it is.

**The finding.** `tests/test_citation_routing_is_true.py` fails **4** cases with
the pointer bound at the real (zero-cell) landing checkout. The failures are
`assert C.main(["--root", str(repo)]) == 0` returning **2**, over a synthetic
repo the test builds in its own `tmp_path`. The test names its own `--root`;
`citation_routing_is_true_check` also consults `$VIBE_IC_BENCHMARK_DATA` through
`_corpus_location`, and the ambient pointer reaches a run that named its subject
explicitly. It is a **test-hermeticity gap**, not a corpus defect — the root
cause below the "rc 2 instead of 0" is not diagnosed here and is not claimed to
be.

**It is NOT introduced by this branch, and that is measured three ways:**

| control | main | this branch |
|---|---|---|
| the pinned 10 modules, **no pointer** | 201 passed, 17 skipped | 201 passed, 17 skipped — *identical* |
| `test_citation_routing_is_true.py`, pointer at a corpus **with 4 cells** (`146d665`, so main survives collection) | 3 failed, 15 passed | 3 failed, 15 passed — *identical* |
| does the failing program import either edited file? | — | **no** — `citation_routing_is_true_check` imports neither `tests/_published_corpus` nor `benchmark_evidence_structure_check` |

The first control shows the default configuration is untouched. The second is the
decisive one: bound at a corpus that main can also read, both trees produce the
same verdict, so the difference is the corpus, never the code. The third shows
there is no path by which this branch could reach that program at all.

**Why main shows nothing in the failing configuration.** Pointer at the real
zero-cell corpus, those same 10 modules on `main` give *10 errors during
collection, 0 tests run*. There is no main-side verdict to compare against —
which is the defect this branch repairs, and the reason the row below it was
never seen.

**Not fixed here, deliberately.** The fix is to make the check hermetic against
an ambient pointer when `--root` is given, which is a change to a program this
branch does not otherwise touch, in a seam (`_corpus_location.resolve`'s
named-vs-env precedence) whose whole purpose is announcing which tree won. That
deserves its own change and its own red, not a rider on this one.

**A measurement of mine that was void, and is corrected here.** An earlier count
in this record compared "10 needs_corpus modules" before and after the hardening
and got 196 → 302 passed. The file list came from `grep -rl needs_corpus | head
-10` and the *set changed under me*: this branch's own new test files mention
`needs_corpus` in their prose, so they entered the grep and displaced others from
the window. The integer was meaningless without the set it counted. Every figure
in the table above is over an explicitly pinned, identical file list.

### CORRECTION to the row above: it is not hermeticity, it is the same defect a third time

The row above calls this *"a test-hermeticity gap"* and says the root cause below
`rc 2` was not diagnosed. It has since been diagnosed, and the characterisation
was wrong. The program's own stderr:

```
note: VIBE_IC_BENCHMARK_DATA adds a corpus to scan -> /home/reyerchu/_matrix_benchmark_data
UNDETERMINED: VIBE_IC_BENCHMARK_DATA=… is a git checkout but tracks no
CITATION_ROUTING.txt at all. A corpus that was NAMED and carries none of this
gate's subject is a wrong pointer, not an absent corpus.
```

The pointer is not ambient leakage the gate failed to guard against — the gate
*deliberately* adds the named corpus to its scan and says so. What it then does
is call a **correct** pointer at the **real** published corpus a **wrong** one,
because that corpus genuinely carries zero of its subject. That is not a
hermeticity bug. It is this record's own subject, one gate further along:

| site | "named and carries none of my subject" | state |
|---|---|---|
| `tools/ci/routed_def_corpus.py` | fixed — rc 0 measured-empty vs rc 3 absent | #1764 |
| `programs/tests/_published_corpus.py` | fixed — MEASURED_EMPTY vs broken pointer | this branch |
| `programs/citation_routing_is_true_check.py` | **still says "a wrong pointer"** | open |

A corpus that was named, opened and read, and holds none of a gate's subject, has
been **measured**. It is not a misconfiguration. Three programs have now been
found asking that question and two have been repaired; the third gives the same
false diagnosis this record was written about.

**What the repair may NOT be.** Turning its `rc 2` into `rc 0` is forbidden and
would be the wrong fix anyway — an empty population must not become a pass. The
correct repair is the one `routed_def_corpus`'s own docstring describes for its
two refusals: *"BOTH states stay NOT CHECKED and BOTH stay blocking; only the
sentence each of them gets is different."* The rc does not move; the sentence
stops being false.

That is carried on its own branch, `next/citation-routing-named-corpus-is-not-wrong`,
because it edits a program this branch does not otherwise touch and it needs its
own red.

## The EMPTY row is load-bearing machinery, not an unattended red

Found while establishing whether the citation-routing rc 2 blocks a landing. It
answers a question the brief asks — *what would have to exist for this gate to
check anything* — on a side the landed adjudication does not cover, and it is a
mechanical reason BLOCKING must stay.

`hygiene_finding_delta.py` names the brief's row as a constant:

```python
ROUTED_DEF_CORPUS = "published cells carrying a routed DEF"
ROUTED_DEF_EMPTY_LABEL = (
    f'corpus "{ROUTED_DEF_CORPUS}" is EMPTY — nothing was checked over it')
```

— verbatim the sentence the brief quotes. `_corpus_transition` is documented as
*"the sole permitted EMPTY-to-expanded declaration addition"*, and to sanction a
corpus going from 0 items to N it REQUIRES, among other things:

- the base corpus be the exact structural EMPTY shape — `items=0`, `gates=1`,
  `expansion=EXPANDED`; anything else is refused;
- the base record register **exactly one** `ROUTED_DEF_EMPTY_LABEL` row as
  **unexempted NOT_CHECKED**;
- the base-only declarations be exactly that row — *"unrelated removals never
  transition"*;
- both arms and a parent-owned canonical manifest bind the same immutable
  benchmark commit;
- independent parent-owned execution receipts exist per gate label.

And the bootstrap is *"deliberately named rather than inferred from arbitrary
`items: 0 -> N` metadata"*, because inference *"would turn every newly declared
loop into a way around the exact declared-set comparison"*.

**So the row is a precondition of its own repair.** The brief asks whether the
declaration should change from BLOCKING to something honest. Beyond the
dispatcher forbidding an exemption on a population refusal, this is a second,
independent reason it must not: the sanctioned restoration path *reads* the
unexempted EMPTY row and refuses to proceed without exactly one of it. Exempting
or downgrading the row would not merely soften a red — it would break the only
machinery that can ever retire it.

It also extends the brief's restoration answer. The landed adjudication states
the PUBLISHING condition (one cell under
`ic/<ic>/v<ver>_<pdk>/phase3/stage3/pnr/routed.def` meeting `INDEX.md`'s bar).
This is the LANDING condition, and it is stricter than "publish a cell": the
transition is attested, not merely observed.

**READ, NOT EXERCISED.** Every statement here is from the source of
`hygiene_finding_delta.py` at `a4caccefe`. No transition was performed and none
could be — it requires a published cell, which is the thing that does not exist.
The four per-cell gate labels it expects
(`macro OBS not crossed`, `DRC PASS is not vacuous`,
`inner FAILs reach the verdict`, `new tool diagnostic id`) were cross-checked
against what `repo_hygiene_gates.sh` actually wires on `a4caccefe`, and they
match exactly, four and four.

*An earlier note of mine said three. That count came from a 906-commit-old
checkout where only three were wired; a fourth landed since. Re-read at main
before it reached a record — the same "which tree did this number come from"
error the rest of this document is about.*

## The brief's own premise, re-measured — and a stale figure in an unlanded record

The brief opens with *"of the ten gates that report NOT CHECKED on `origin/main`,
nine carry a dated exemption. One does not."* I had been carrying the exemption
arithmetic from an earlier record rather than taking it myself. Taken, at
`a4caccefe`, on 2026-08-22:

| | at `a4caccefe` (today's main) | at `81cd5321b` |
|---|---|---|
| `uncheckable_until` lines | **25** | 20 |
| dated `2026-11-30` | **3** | 9 |
| dated `2027-02-28` | **22** | 11 |
| expired (date ≤ today) | **0** | 0 |

**The conclusion is unchanged and stronger for having been re-taken.** All 25
attach to `run_tolerating_uncheckable` — 24 directly once intervening comment
lines are skipped, and one separated from its wrapper by a `gate_serial`
directive. **None** attaches to a plain blocking `run`, none to
`gate_dispatch_over`, and none has expired. Since `gate_dispatch_finish` fails
the run on an expired exemption, and since the dispatcher refuses an exemption on
a population refusal at all, the routed-DEF EMPTY row remains **the only
unexempted blocking refusal in the file**.

### CORRECTION: the stale figure is on MAIN, not in the unlanded branch

**My first version of this section named the wrong document, and the retraction
matters more than the finding.** It said
`origin/fix/jdefcorpus-routed-def-restoration-condition-v2` prints *"all 20 of
them"*. It does not — that string appears **zero** times in it, and its own
table, marked `[re-measured @ a4caccefe]`, reads:

| counted in `tools/ci/repo_hygiene_gates.sh` @ `a4caccefe` | n |
|---|---|
| `run_tolerating_uncheckable` call sites | 25 |
| `uncheckable_until <date> <why>` declarations | 25 |

which matches my own measurement exactly. **The unlanded branch is right.** I had
read the passage in a different file and attributed it to the branch, which is
the same "which tree did this come from" error this document is about, committed
by me, about a document about that error.

**Where it actually is:** `docs/findings/2026-08-21-routed-def-corpus-is-empty-adjudication.md`
— **landed on `main`**. It states *"all **20** of them"*, quotes
`grep -c '^[[:space:]]*uncheckable_until '` returning `20`, annotates
`run_tolerating_uncheckable x20  run x0  gate_dispatch_over x0`, and splits them
*"**9** dated 2026-11-30, **11** dated 2027-02-28"*.

**And it was wrong when it landed, not merely aged.** That distinction is the
whole finding, so it was measured rather than assumed. The file arrived in
`fed57f213` (2026-08-22 08:40 +0800). At that exact commit:

| | at `fed57f213`, the landing commit | at `a4caccefe`, now | as the doc prints |
|---|---|---|---|
| `uncheckable_until` | **25** | **25** | 20 |
| `2026-11-30` | **3** | **3** | 9 |
| `2027-02-28` | **22** | **22** | 11 |

Nineteen commits separate the two shas and none of the counts moved. The figure
never described the tree it landed in; it is `81cd5321b`'s value — the first
draft's base, 214 commits earlier — carried forward under a re-measurement
heading.

**The conclusion is unaffected and independently re-derived above:** all 25
attach to `run_tolerating_uncheckable`, none to a plain `run`, none expired, so
the routed-DEF EMPTY row remains the only unexempted blocking refusal. What is
wrong is the arithmetic printed beside a correct verdict — which is the more
dangerous shape, because a reader checking the sums finds them self-consistent
and stops.

**What should happen to it.** The newer record already carries the right numbers,
so the repair is to correct the landed file's three figures — 20 → 25, 9 → 3,
11 → 22 — and drop its "9-vs-9 coincidence" remark, which is moot at 3. That is
an edit to a landed document on `main`, which this branch may not make, so it is
recorded here rather than performed.

*Three passes were needed before my own count was right, and it is worth saying
how, because a one-pass `grep` beside a structured file is how the landed figure
got there. Pairing each exemption with the line immediately after it gave "20
`run_tolerating_uncheckable`, 5 `#`" — the wrapper is not always adjacent.
Skipping comments gave "24 + 1 `gate_serial`". Only the third pass was the
answer. My first pass produced the number 20 as well, from a different mistake
than the one that produced the landed 20.*
