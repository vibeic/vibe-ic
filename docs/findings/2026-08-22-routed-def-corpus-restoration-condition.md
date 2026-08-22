# The routed-DEF corpus is empty, the publisher says so, and one publication is
# not enough to restore the gate

Second, independent adjudication of the one NOT CHECKED row on `origin/main`
that carries no exemption:

```
NOT CHECKED (rc 2, BLOCKING; no exemption):
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
[population: producer rc 0, 0 items]
```

Measured 2026-08-22 on a clean worktree of `origin/main` @ `81cd5321b`
(`PYTHONDONTWRITEBYTECODE=1`), and **RE-MEASURED end to end on 2026-08-22 on a
clean worktree of `origin/main` @ `a4caccefe` (v1.11.69), 214 commits later,
against the publishing repository at its live tip `3b58ccd42`.** Evidence
attaches to a sha, not to a branch name: this record was written against a base
that main has moved past, so every load-bearing claim below was taken again
rather than carried forward. Every passage carrying a re-taken measurement is
marked **[re-measured @ a4caccefe]** — deliberately not summarised as a count
here, because a hand-maintained number beside a growing list is the next thing
to drift. Most reproduce unchanged.

**Three claims moved, and each says so where it stands:** a count of mine that
was simply wrong (4 cells and 342 directories, not "5 cells, 388"), an item this
record FILED that has since been FIXED on main by #1764, and a sibling branch
that the same landing superseded on the merits.

**Two things are newly named and deliberately NOT taken**, each with its
reproduction and its reason, at the end of this record: a roll-up that reports
`9/9 conformant` over a corpus with zero published cells, and a test helper that
diagnoses a CORRECT pointer at the real corpus as a broken one — the #1764
defect surviving one layer down.

Nothing in the verdict moved. It reaches the same verdict as
`2026-08-22-routed-def-corpus-adjudication.md` by a different route — that
record read this repository's publishing programs; this one reads the
**publishing repository's own committed statement** — and it then contradicts
one load-bearing sentence in it.

## Verdict: (2), the corpus is legitimately empty

Not "the producer is wrong" (1) and not "the artefacts are under a name the
producer does not look at" (3). The artefacts were looked for where they are
supposed to be, and they are not anywhere.

## What was measured, at the publisher rather than at the producer

`routed_def_corpus._ORIGIN` names `https://github.com/vibeic/benchmark-data`.
That repository's tip on 2026-08-22 is `3b58ccd42`. Its complete recursive tree
(`GET /repos/vibeic/benchmark-data/git/trees/3b58ccd42?recursive=1`,
`truncated: false`):

| query over the published tip | result |
|---|---|
| blobs in the whole repository | 6929 |
| blobs whose name is `routed.def` | **0** |
| blobs whose name ends `.def`, anywhere, any depth | **0** |
| `v<version>_<PDK>` cell directories under `ic/` | **0** |
| designs under `ic/` | 9 |
| what remains under every one of those 9 `ic/<design>/` | `input/` only |

There is no routed DEF in the published corpus, at any path, under any name.
The population is zero at the source, not merely zero in this checkout.

**[re-measured @ a4caccefe]** The table above was originally read from GitHub's
tree API. It was taken again from a local clone — `git clone --filter=blob:none
--single-branch --branch main`, HEAD `3b58ccd42`, `git ls-tree -r --name-only` —
and every row reproduces: 6929 blobs, `grep -c 'routed\.def'` = **0**,
`grep -cE '\.def$'` = **0**, 9 designs under `ic/`. Two readers, two protocols,
same answer. `git ls-remote` confirms `refs/heads/main` is still `3b58ccd42`, so
the publisher has not moved since the first draft.

### And the row reproduces, on the landing path, exactly as reported

The producer's rc depends on whether a corpus was RESOLVED, and the two states
have different exit codes since #1764. So "rc 0, 0 items" is a claim about
which state the landing path is in, and it is checkable. Bound the way
`gatekeeper_review` binds it — `VIBE_IC_BENCHMARK_DATA` at a clone of the
publisher — and run the producer on a clean `a4caccefe` worktree:

```
$ VIBE_IC_BENCHMARK_DATA=<clone of benchmark-data @ 3b58ccd42> \
    python3 tools/ci/routed_def_corpus.py --repo <clean a4caccefe worktree>
producer rc = 0
items on stdout = 0
[routed-def corpus] MEASURED EMPTY: git's index at <clone> was read under 'ic'
and it publishes no */*/phase3/stage3/pnr/routed.def. This IS a measurement --
the corpus was opened and the population is 0 -- and it is NOT the same state
as a corpus that could not be found (rc 3).
```

`rc 0, 0 items` — the brief's population line, reproduced against the live
publisher. This is decisive for the verdict, and it is the reason (2) rather
than (3) is the answer: the corpus was **opened**, an index was **read**, and it
holds none. Had the artefacts merely been somewhere the producer does not look,
this would be a measurement of a tree that contains them. It is not. The tree
was measured, twice, by two readers, and it contains no `.def` file at all.

(For contrast, the same worktree with no pointer and no `benchmark-data/` exits
**3** — `NOT FOUND`, the absence of a measurement. That is a different row with
a different sentence, and it is not the row the brief quotes.)

## The publisher says so itself, in two committed files

This is the part the earlier adjudication infers and this one reads. The corpus
repository states its own state and its own contract:

`CELL_MATRIX.md`:

> **No cells are published.** The four that were here were withdrawn on
> 2026-08-20: two carried a passing verdict over an audit in which zero of 246
> registered gates had run, and one of those also carried a second,
> contradictory `FAIL` audit at a nested path the generator could not see.

`INDEX.md` carries the measurement the withdrawal was made on:

| cell | verdict | registered gates | actually passed |
|---|---|---|---|
| spm × sky130A | PASS_WITH_WAIVERS | 246 | 154 |
| spm × gf180mcuD | PASS_WITH_WAIVERS | 246 | 154 |
| u_hawaii_adc × sky130A | **PASS** | 246 | **0** |
| spm × ihp-sg13g2 | PASS_WITH_WAIVERS | *unset* | **0** |

So the answer to "why is the population zero" is not an inference about this
repository's programs. It is a dated decision, published in the repository that
would have to carry the artefact, for a reason that is better than the artefact
it removed: *a verdict is not evidence, `passed_gate_count` is*.

`ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def` — the single member
this loop ever had — belonged to the fourth row of that table.

## What would have to exist for this gate to check anything

Taken from the publisher's own numbered contract (`INDEX.md`, "Publishing a
result"), not from a reading of this repository's intent:

1. The run **actually happened**, in a real flow run, on the PDK named in the
   directory.
2. `passed_gate_count > 0`. A FAIL that ran is worth more there than a PASS
   that did not.
3. **Exactly one** `reports/audit/phase23_completion_audit.json`.
4. The directory is `v<plugin-version>_<PDK>`, matched by a regex whose
   mismatch is fatal.
5. The artefacts are committed, not a summary of them.

and — this repository's own requirement, which the contract above does not
state — the routed DEF at exactly

```
ic/<design>/v<version>_<PDK>/phase3/stage3/pnr/routed.def
```

because that is the only shape `routed_def_corpus._index_paths` counts: it
requires the path relative to `ic/` to have **exactly six components**, with
`parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`.

**[re-measured @ a4caccefe] — and the operator does not have to find this
document to learn it.** The sentence the producer itself prints beside the
blocking row, captured verbatim from the run above, already names the member
shape:

> scanned the env corpus at …/ic and its git index holds 0 routed DEF(s). **A
> member is `<design>/<version>/phase3/stage3/pnr/routed.def`.** This is an
> EMPTY POPULATION, not a clean one: no published cell was examined and nothing
> is claimed about any. The per-cell gates go live again on the first cell
> published with a routed DEF.

That is worth stating because it is the strongest single fact in favour of
leaving the declaration alone: the row that blocks says what it measured, says
that zero is not clean, names the exact path that would end it, and does not
overstate what a first publication buys beyond its own loop. Nothing about the
gate's own reporting is dishonest. The gap this record closes is one directory
level BELOW that sentence — that a cell can be published carrying that exact
filename and still not be counted — and it is closed in the publish path, where
it belongs, not by rewording a row that is already true.

## The sentence this record contradicts

The earlier adjudication closes with:

> The moment one such cell lands in the corpus repository and the pointer is
> bound, this loop expands to a real population.

That premise is not safe, and the published corpus is where it fails. Every
directory in the published tree that holds a `stage3/pnr` stage, today:

| files | directory |
|---|---|
| 11 | `protocol_parity/espi/phase3/stage3/pnr` |
| 10 | `protocol_parity/interlaken/phase3/.phase3_held/stage3/pnr` |
| 11 | `protocol_parity/lpc/phase3/`**`phase3`**`/stage3/pnr` |
| 11 | `protocol_parity/mdio/phase3/stage3/pnr` |
| 12 | `protocol_parity/sgmii/phase3/stage3/pnr` |

Three of the five are canonical. One is a deliberate hold. **One is a doubled
directory**, and it is not a one-off inside that cell — the same cell doubles
its phase-2 stage too:

| stage entries under `protocol_parity/lpc/` | vs `protocol_parity/espi/` |
|---|---|
| `phase2/`**`phase2`**`/` — 12 files | `phase2/stage1/` 6, `phase2/stage2/` 6 |
| `phase3/`**`phase3`**`/` — 28 files | `phase3/stage3/` 98, `phase3/reports/` 2 |

`<design>/<version>/phase3/phase3/stage3/pnr/routed.def` is **seven** components
relative to `ic/`, not six. The producer does not count it, exits 0, and prints
nothing on stdout — which is byte-for-byte the population an empty corpus
produces. A cell published in that shape leaves the row saying
`is EMPTY — nothing was checked over it` while a routed DEF is published, and
nothing anywhere would say otherwise.

This is not a hypothetical shape, and it is not an inference about the producer
either. Run against two synthetic corpus checkouts that differ only in that one
directory:

| corpus contains | producer rc | items on stdout |
|---|---|---|
| `ic/demo/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def` | 0 | **1** |
| `ic/demo/v9.9.9_openpdkx/phase3/`**`phase3`**`/stage3/pnr/routed.def` | 0 | **0** |
| no routed DEF at all | 0 | **0** |

Rows two and three are the same bytes. Nothing downstream can tell the blocking
row's *stated* reason (`is EMPTY`) from the unstated one (*a routed DEF is
published where I cannot count it*).

`test_routed_def_population_is_depth_exact.py` pins all three. The pin is not
vacuous: mutating a **copy** of the producer from `len(parts) == 6` /
`parts[2:]` to `len(parts) >= 6` / `parts[-4:]` gives 2 failed / 1 passed, while
the identical harness over a byte-identical copy gives 3 passed — so the colour
is the mutation and not the scaffold.

**[re-measured @ a4caccefe]** #1764 rewrote this producer between the two
measurements, so the mutation was rebuilt against the current file and run
again. Same result: **control (byte-identical copy) 3 passed; mutated 2 failed,
1 passed** — the two that fail are `test_one_directory_deeper_is_not_counted`
and `test_a_published_routed_def_at_the_wrong_depth_is_indistinguishable_from_none`,
which is the pair that carries the finding. On the unmutated branch tree the
file is 3 passed. The tracked producer was not touched: it is a protected
authority path and both arms are copies outside the worktree
(`git status --porcelain` empty; sha256 `6c8f9fa9…` at `a4caccefe`, which is a
different file from the `d04b8215…` measured at `81cd5321b` — that is #1764,
and it is why re-running this was not optional).

**And it is the same defect class the withdrawal was made for.** `u_hawaii_adc`
was withdrawn because its run wrote a second audit at `reports/`**`reports`**`/audit/…`
— one directory too deep — saying FAIL, 3.5 s before the PASS the public page
displayed. `INDEX.md` turns that into rule 3 and adds the instruction:

> Check for a nested `reports/reports/` before committing.

That instruction names one spelling of the bug. The corpus contains three
directories with that shape and **not one of them is the spelling the
instruction names**:

| same-name nesting, published corpus @ `3b58ccd42` | files |
|---|---|
| `protocol_parity/lpc/phase2/phase2` | 12 |
| `protocol_parity/lpc/phase3/phase3` | 28 |
| `protocol_parity/usb_pd/reports/phase3/phase3` | 24 |

Measured before this change, **no program in this repository detected any of
them**: `grep -rn 'reports/reports'` over `programs/` and `tools/` returned
nothing, and there was no general nested-duplicate detector either.

### The third one is the withdrawal, reproduced

`protocol_parity/usb_pd` is not merely misshapen. Four report names exist at
BOTH `reports/phase3/` and `reports/phase3/phase3/`, and **three of the four
differ in content**:

| report | outer (what consumers read) | inner (one directory deeper) |
|---|---|---|
| `foundry_handoff_audit.json` | `"verdict": "SKIP"`, `found: []`, both required files **missing** | `"verdict": "PASS"`, both **found** |
| `si_crosstalk.json` | no SPEF, structural screen, `max_crosstalk_noise: 0.0` | real SPEF, `max_crosstalk_noise: 1791.87` of 1800 mV, 500 coupling-dominated nets |
| `si_crosstalk.rpt` | differs | differs |
| `gds_size.json` | identical | identical |

The two copies are not two writes of one run: their own `chip_gds` /`spef`
fields name **different source trees** (`vibe-ic/benchmark_phase1/usb_pd/…`
against `AI_IC_design/_usb_pd_phase3_stage/…`, the second in a repository that
has since been retired). One published cell therefore carries two runs' answers
to the same question, at two depths, and every consumer reads exactly one of
them.

That is the `u_hawaii_adc` shape — a second, contradictory verdict one directory
too deep — still committed, in a different design, two days after the cell that
carried it was withdrawn for exactly that and the instruction to check for it
was written down. It is why the rule below is a program and not another line in
a contract.

**[re-measured @ a4caccefe]** Every cell of the table above was taken again
from a full checkout of `benchmark-data` @ `3b58ccd42` (the first draft read
them through the tree/contents API) and every one reproduces: four names at
both depths, `cmp` says three DIFFER and `gds_size.json` is IDENTICAL;
`foundry_handoff_audit.json` is `verdict=SKIP` with 0 found / 2 missing outside
and `verdict=PASS` with 2 found / 0 missing inside; `si_crosstalk.json` is
`max_crosstalk_noise` **0.0** with no SPEF outside and **1791.87** with a real
SPEF inside, whose recorded source tree is the retired repository. The two
quoted publisher sentences were read from the same checkout at
`CELL_MATRIX.md:23-26` and `INDEX.md:88`.

## Decision: BLOCKING stays, and it buys no exemption

Unchanged from the earlier adjudication, and for the same two reasons, both of
which this record's measurements strengthen rather than alter:

**Not an exemption.** `_gate_dispatch.sh` mode 2 refuses one by construction —
*"a dispatcher-owned population refusal … cannot consume an uncheckable
exemption — an unknown denominator must remain blocking"*. It is also the wrong
instrument on the facts: the population is zero because a publisher deliberately
removed four cells that were not evidence. A dated tolerance would restore
exactly the silence that removal ended.

**Not a declaration change.** This row is the only statement on `main` that
post-route geometry is checked over nothing at all. An advisory row would still
be advisory on the day the corpus refills — it would stop blocking precisely
when it regains the ability to find something.

**So: neither instrument. The declaration is already the honest one.** What was
missing is not a change to the gate but a written restoration condition, and the
condition the earlier record wrote is incomplete: it names what must be
published and omits the shape it must be published in.

### Why THIS row is the unexempted one, structurally rather than by accident

**[re-measured @ a4caccefe]** The brief's framing — nine exempted NOT CHECKED
rows and one that is not — is not a property of one run. It falls out of the
wiring, and that is checkable without running the 3750-second suite:

| counted in `tools/ci/repo_hygiene_gates.sh` @ `a4caccefe` | n |
|---|---|
| `run_tolerating_uncheckable` call sites (gates allowed to report NOT CHECKED) | 25 |
| `uncheckable_until <date> <why>` declarations | 25 |
| `gate_dispatch_over` call sites (loop-driven corpora) | **1** |
| of those, opting into `GATE_DISPATCH_ATTEST_POPULATION=1` | **1** |

The 25/25 is exact and the dispatcher enforces it: a
`run_tolerating_uncheckable` without an adjacent `uncheckable_until` is a wiring
error, and so is an `uncheckable_until` on a plain `run`. So every gate that may
answer NOT CHECKED carries a dated reason — by construction, not by diligence.

The single `gate_dispatch_over` call site is the routed-DEF corpus, and it is
the only one in the file that opts into the process-attested population mode.
That mode is the one thing an exemption cannot reach
(`_gate_dispatch.sh:668-669`: *"a dispatcher-owned population refusal … cannot
consume an uncheckable exemption — an unknown denominator must remain
blocking"*).

So the row is not the one nobody got around to exempting. **It is the only row
in the suite that is structurally inexemptible**, and it is that because the
thing it reports is a missing denominator rather than a missing tool. That is
the strongest available argument that the declaration is already correct: the
mechanism was chosen for this case, and this is the case.

## What is fixed here, and what is only filed

**Fixed (this branch):** `benchmark_evidence_structure_check.py` gains a
`NESTED_DUPLICATE` nonconformance. A cell whose run tree contains a directory
nested directly inside a same-named parent is refused at publish time. It is a
new refusal on an unprotected checker that `benchmark_evidence_publish.py`
already runs before staging and `gatekeeper-land.sh` already runs over the tree,
so it needs no new wiring, and it is strictly tightening — it can turn no red
green.

**[re-measured @ a4caccefe] — and the reach of "no new wiring" stated exactly.**
The wiring is there: `benchmark_evidence_publish.py:1800` invokes the checker,
and `gatekeeper-land.sh:456` runs
`benchmark_evidence_structure_check.py --tree benchmark-data
--corpus-may-be-absent`. The pre-push hook no longer runs it at all — it says so
itself ("BENCHMARK EVIDENCE IS A LANDING CONCERN — AND IT ALREADY RUNS THERE"),
so landing is the only path, which is the right one.

That landing invocation names the IN-REPO path, and there is no in-repo
`benchmark-data/` on `main` any more, so what it actually does was measured
rather than assumed:

| landing invocation, verbatim | what it scanned |
|---|---|
| pointer unset | `NO_CORPUS … NOTHING WAS SCANNED and nothing is claimed`, rc 0 |
| pointer bound at a clone | follows it, enumerates the 9 IC units, rc 0 |

So the rule runs on the published corpus exactly when the corpus is bound —
which is the landing path's normal state, since `gatekeeper_review` binds it
before the gates run, and is why the routed-DEF row reads MEASURED EMPTY rather
than NOT FOUND. The unbound rc 0 is not a hole this change should close:
`--corpus-may-be-absent` is the argued opt-in for a gate whose rc 0 IS a green
row, and it is the same distinction #1764 drew from the other side. Stated here
so nobody reads "no new wiring" as "runs unconditionally". It closes the gap between "a cell is published" and "the routed-DEF loop
can see it", which is what makes the restoration condition above true rather
than hopeful.

The red, with the same test file on both arms — **[re-measured @ a4caccefe]**,
against `origin/main`'s checker at the current tip rather than the old one:

| arm | result |
|---|---|
| final tests vs `origin/main` @ `a4caccefe`'s checker (byte-identical copy) | **6 failed**, 1 passed |
| final tests vs the fixed checker | **7 passed** |

Unchanged from the first measurement. The six that go red are
`test_the_rule_reports_a_verdict_on_a_clean_cell`,
`test_the_withdrawal_shape_is_refused`,
`test_the_shape_that_makes_the_routed_def_corpus_look_empty_is_refused`,
`test_every_offender_is_named_not_just_the_first`,
`test_the_finding_is_machine_readable` and
`test_an_empty_nested_duplicate_still_counts`.

The 1 that passes on the red arm is the negative control — the canonical cell,
which carries `phase3/` and `reports/phase3/` in one tree, must not be refused.
It is written first so that a rule matching the NAME rather than the ADJACENCY
is caught by a test instead of by a reviewer.

And the rule is measured rather than argued — **[re-measured @ a4caccefe],
this time by running both checkers over the real published tree rather than
over a fixture.** The last commit of `vibeic/benchmark-data` that carried
published cells is `146d665` (the parent of `bcf2f94`, "withdraw all four
published cells"). Checked out whole and handed to `--tree`:

| arm | result over `benchmark-data` @ `146d665` |
|---|---|
| `origin/main`'s checker @ `a4caccefe` | **13/13 conformant, 0 nonconformant, rc 0** |
| this branch's checker | **12/13 conformant, 1 nonconformant, rc 1** |

The 13 units are 9 `ic/<IC>/` layout units and 4 cells. The one unit the arms
disagree about is `ic/u_hawaii_adc/v1.9.86_sky130A`, named for
`reports/reports`, and it is **the cell the publisher withdrew two days later
for exactly that defect**. Read the other way round, which is the sentence that
matters: *`origin/main`'s structure gate prints `[PASS] … verdict=PASS` over the
cell whose second, contradictory audit says FAIL.*

Across the four cells' **342** distinct directories there is exactly **one**
same-name nesting, and it is that one. One true positive, 341 clean
directories, zero false positives, on real published artefacts.

**Correction.** The figure in the first draft of this record was "5 cells, 388
distinct directories, 387 clean". Both numbers are wrong: `146d665` publishes
**4** cells (`spm` × three PDKs, `u_hawaii_adc` × one) spanning **342**
directories. The one-hit result is unchanged; only my count of what it was
measured over was.

Targeted regression, **[re-measured @ a4caccefe]** and this time as an A/B
rather than a single arm. The set is every test file under `programs/tests/`
naming `benchmark_evidence_structure_check`, `NESTED_DUPLICATE` or
`check_folder` — 16 files. Load 75–106 on 32 cores, so the elapsed figures below
are not comparable to anything and are recorded only to say the runs completed.

| arm | result |
|---|---|
| this branch, all 16 files | **240 passed, 62 skipped, 6 failed** (318 s) |
| `origin/main`, the file carrying all 6 | **52 passed, 61 skipped, 6 failed** (298 s) |
| both arms, the 6 failing node ids alone | 6 failed / 6 failed, **identical failure set, identical assertion text** |

The 6 are `test_matrix_d3_outputs_produced::test_d3_required_outputs_are_produced`
at `step15/17/19/20/30/32`, and they are **pre-existing reds on `origin/main`**,
not introduced here. The subset rule this repo lands on — the candidate's
failures must be a subset of the base's — is satisfied with an empty difference.
The claim is not "they look unrelated": the same six node ids were run alone on
a clean `origin/main` worktree and on this branch, and both the set and the
assertion text `diff` clean.

They also are not a coincidence of subject. Each asserts
`assert not cites, _corpus_skip_would_hide(sid, cites)` — the guard that, when
the corpus is absent, REFUSES by name a record citing a run root no host can
answer instead of letting it skip. So they are a second, independent
consequence of the same corpus move this whole record is about, and the repo's
answer to it there is the same as the answer here: refuse loudly, do not soften.

`size_policy_drift_check.py`, which probes `check_folder` as its decision entry
point, exits 0 on both arms with **byte-identical output** (`diff` clean).

### And it does NOT reach the three instances above. Measured, not assumed.

**[re-measured @ a4caccefe]** — and no longer on a synthetic root. Both checkers
run over the LIVE published tree, `benchmark-data` @ `3b58ccd42`, the one the
landing path actually binds:

| arm | result over the live published tree |
|---|---|
| `origin/main`'s checker | 9/9 conformant, 0 nonconformant, rc 0 |
| this branch's checker | 9/9 conformant, 0 nonconformant, rc 0 |

Byte-identical output. Nine units, all of them `ic/<IC>/` layout units, **no
cell units at all** (every cell was withdrawn), and the string
`protocol_parity` does not occur once in either arm's output — grep count 0.
`_discover_evidence_folders` keeps a child only under `ic/<IC>/`, verified in
its own source at `benchmark_evidence_structure_check.py:878-890`.

So on today's corpus the new rule fires on nothing and changes nothing, which
is the correct and unexciting result: it is a PUBLISH-TIME refusal for a shape
nothing currently publishes, and it earns its place by what it refuses next
rather than by what it reds now.

So this rule covers the population the routed-DEF loop actually draws from —
`ic/<design>/v<version>_<PDK>/` — and covers nothing else. The three
`protocol_parity/` instances that made the shape credible remain uncaught, in
the corpus repository, today. Catching them needs `_discover_evidence_folders`
to enumerate a second tree, which changes what the structure gate reports over
the whole corpus and would land three live FAILs on a tree `gatekeeper-land.sh`
walks. That is a decision about the structure gate's scope, not a side effect of
adjudicating one blocking row, so it is **named here and not taken**.

The honest summary of the fix is therefore narrower than "the nested-duplicate
bug is fixed": a cell can no longer be PUBLISHED into the routed-DEF corpus in a
shape that corpus cannot see. The instances already published elsewhere are
untouched.

**Filed here, and FIXED ON MAIN SINCE — by someone else, and better.**
**[re-measured @ a4caccefe]** The first draft filed this: `routed_def_corpus.py`
hardcodes `may_be_absent=True`, so "a corpus was read and holds no routed DEF"
and "no corpus was supplied at all" reach the dispatcher as the same rc 0 /
0 items. It was filed rather than fixed because that file is line 71 of
`REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`
(**still line 71 today**), and `_match_state` raises *"protected tuple matches
neither authorised atomic state"* for a candidate that edits it outside a
base-authorised PREPARE → ACTIVATE pair.

That transition happened. `ef0399606` ("routed-def corpus: an ABSENT corpus and
a MEASURED-EMPTY one shared one row (#1764)") landed the distinction, and it is
live at `a4caccefe`:

```
rc 0  the index WAS read and it publishes no routed DEF   -- a measurement
rc 3  no corpus was resolved, so nothing was opened       -- no measurement
rc 2  somebody said where the corpus is and was wrong     -- UNDETERMINED
```

Measured on a clean `a4caccefe` worktree: with no pointer and no
`benchmark-data/`, the producer exits **3** and prints `NOT FOUND (rc 3)`. Note
what did NOT change — the call still passes `may_be_absent=True`; what changed
is that the NO_CORPUS branch now leaves with its own code instead of borrowing
rc 0. The filed item is CLOSED, and this record no longer asks anyone to
act on it.

**A note for whoever lands this: two sibling branches are now DEAD, and one
of them because it WON.** **[re-measured @ a4caccefe]**

`origin/fix/routed-def-corpus-empty-adjudication` @ `6ec94ef2c` reaches the same
verdict about the corpus and then edits `tools/ci/routed_def_corpus.py` directly
to make an absent corpus exit **rc 2**. The first draft of this record said that
candidate could not land, because it changes protected bytes with no manifest
change. That is still true of the commit — and it no longer matters, because its
FINDING landed on main through the authorised route as `ef0399606` (#1764),
which gave the absent corpus **rc 3** rather than rc 2 and argued for the
difference in the producer's own docstring:

> reversing it would have made an absent corpus borrow the FAILED PRODUCER row
> instead, which is a second wrong sentence rather than the missing one

So the sibling is superseded on the merits, not merely blocked on mechanics: the
distinction it asked for exists, under a better exit code than the one it
proposed. **Do not land it. Nothing is lost by closing it** — bundled at
`refs/backup/jdef/empty-adjudication` before this record was written.

`origin/fix/jdefcorpus-routed-def-restoration-condition` @ `0df1dd533` is THIS
record's first draft, based on `81cd5321b`, 214 commits behind. It is superseded
by the branch you are reading, which is the same net change cherry-picked onto
`a4caccefe` — verified identical modulo blob hashes — plus these corrections.
**Land this one; close that one.** Bundled at
`refs/backup/jdef/restoration-condition`.

Neither branch touches a protected path.
`benchmark_evidence_structure_check.py` does not appear in
`REQUIRED_AUTHORITY_PATHS` at all — checked at `a4caccefe` — so this change is
landable from one candidate commit.

## Named and NOT taken: the same shape, one gate over

Running both checkers over the live corpus (above) turned up something that is
not this row and is worth writing down where the next reader will find it.

Over `benchmark-data` @ `3b58ccd42` — a corpus with **zero published cells** —
`benchmark_evidence_structure_check --tree` prints:

```
benchmark_evidence_structure_check: 9/9 conformant, 0 nonconformant
```

rc 0. Its own `USAGE` calls that invocation *"validate every published cell in a
tree (the CI shape)"*, and `gatekeeper-land.sh` runs it on the landing path. The
nine units are all IC-level layout units; the number of published cells examined
is **0** and appears nowhere in that line.

The per-unit rows are not wrong — each says `IC-level layout: 1 published entry
examined, all allowed`, which is true and is the #967 disclosure working. Nor is
the machine-readable output wrong: `--json` carries a `kind` field per unit, and
it separates them exactly.

| tree | `kind` histogram from `--json` | printed line |
|---|---|---|
| `3b58ccd42` (today) | `{ic-root: 9}` | `9/9 conformant, 0 nonconformant` |
| `146d665` (pre-withdrawal) | `{ic-root: 9, cell: 4}` | `13/13 conformant, 0 nonconformant` |

Both lines are true. Neither states the cell count, and the two trees differ by
*every published cell in the repository*. A reader of the CI log gets the same
sentence shape from a corpus with four cells and from a corpus with none — which
is the sentence this whole record is about, one gate over.

**Not taken tonight, and the reason is not that it is small.** The remedy is
small and the mechanism already exists: `main()` builds a `tail` string for
exactly this purpose (#967, for skipped units) and a kind-split clause belongs
there. What stops it is blast radius I cannot measure at this hour — that
summary line is read by 25 test files under `programs/tests/` and parsed by both
`tools/gatekeeper-land.sh` and `tools/gatekeeper-verify-merge.sh`, and the suite
that would tell me whether an added clause breaks any of them is the one this
work is not allowed to run. Changing a string the landing path parses, without
being able to run the landing path, is how a fix becomes an outage.

So it is measured, named, and left. It is a disclosure defect, not a false
verdict: no gate says PASS over something it failed, and nothing here is
weakened by leaving it.

## Named and NOT taken, second: a correct pointer is diagnosed as a broken one

Found while running the A/B above, by doing the one thing the repository's own
error message tells an operator to do.

`tests/_published_corpus.py::corpus_root` decides what
`$VIBE_IC_BENCHMARK_DATA` means for **56** test modules. Its docstring sets out
the case analysis, and the case analysis is deliberate — it exists because
`VIBE_IC_BENCHMARK_DATA=<empty dir> pytest` once produced *"29 passed, 2
skipped"*, i.e. a mistyped path turned a whole corpus suite green:

> Nobody set the pointer and the repo has no cells → None. Honest.
> Somebody SET the pointer and it holds no cells → raise. **They named a corpus.
> The name is wrong, or the clone failed, or the CI step that was meant to fetch
> it did nothing.**

Three causes, and on 2026-08-20 a fourth appeared that is none of them: the
pointer is right, the clone succeeded, the fetch worked, and **the corpus
genuinely holds zero cells because the publisher withdrew all four**. Measured
— pointer bound at a real `git clone` of `vibeic/benchmark-data` at its live tip
`3b58ccd42`:

```
E   _published_corpus.CorpusPointerBroken: VIBE_IC_BENCHMARK_DATA=… names a
    corpus with no published cell under ic/<design>/v<version>_<PDK>/ (the path
    exists but is empty of cells). This is NOT the same as having no corpus:
    you said where it is. Unset VIBE_IC_BENCHMARK_DATA to run these checks as
    skipped, or point it at a clone of vibeic/benchmark-data.
1 error in 2.25s
```

The module names three causes, all three false; and it closes by advising the
reader to *point it at a clone of `vibeic/benchmark-data`* — which is exactly
what was done. **The remedy it prints is the action that produced the error.**

This is the same defect as the one #1764 fixed for the producer — *an absent
corpus and a measured-empty one are not the same state* — surviving one layer
down, in the test helper, where nobody looked for it.

**Reach, measured rather than assumed, because it decides how urgent this is.**
It is **not** on the landing path today. `gatekeeper_review._published_corpus_binding`
adds the pointer to the environment of the *hygiene set* only
(`gatekeeper_review.py:1345-1355`, inside the `hygiene_summary_` scope) — which
is why the routed-DEF row reads `producer rc 0` at all — and pytest runs without
it, so those 56 modules SKIP rather than error. What this hits is a human or an
agent who sets the pointer, which is what the message above tells them to do,
and what the sibling check `evidence_citation_resolves_check.py` documents in
its own USAGE.

**Not taken, and the reason is the opposite of the usual one.** The obvious edit
— return `None` for the zero-cell case — is a LOOSENING, and it is the precise
loosening this module was written to prevent: it would turn 56 modules from
ERROR to green-by-skip and reinstate the "29 passed, 2 skipped" defect its
docstring records. The correct fix is a FOURTH state, mirroring #1764: separate
*"this path is not a corpus"* (broken → raise) from *"this IS the published
corpus and its cell population is zero"* (measured → skip, loudly, stating the
measurement). That needs a decision about what identifies a genuine corpus
clone, and it changes collection behaviour for 56 modules — with no way to run
the suite that would tell me whether it did. **Measured, named, and left**, with
its evidence, so the next person starts from a reproduction instead of a
suspicion.

## What this deliberately does not do

It does not publish anything to make the corpus non-empty, and it does not widen
the producer's population rule so that the doubled shape would count. Widening
would make the row green over a run tree whose own layout is the defect that
withdrew a cell. The population rule is right; the publish path is what should
refuse to produce a shape it cannot see.
