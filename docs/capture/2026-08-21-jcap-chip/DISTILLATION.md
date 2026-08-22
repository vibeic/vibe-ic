# jcap-chip, distilled — the thirteen Bucket-A rules as programs that bite

agent `jdistchip` · branch **`capture/jdistchip-chip-path-rules`**, cut from
`81cd5321b` = `origin/main` = v1.11.68. **No version bump. Nothing pushed to
`main`. No baseline written.**

`RESULT.md` in this folder is the CAPTURE; this file is what happened when its
thirteen Bucket-A records were turned into enforcement.

## Outcome

All 13 Bucket-A rows now have both `programs/<rule_name>.py` and
`programs/tests/test_<rule_name>.py`. Twelve were written here; one was found
ALREADY IMPLEMENTED and its record repointed at the real enforcement.

| resolution | rule | note |
|---|---|---|
| already implemented | `emitted_script_portability_check` | `recoveries.json` was repointed from `emitted_script_paths_are_project_relative`. The existing program covers the same population and draws a SHARPER line: a finding is an absolute path INSIDE the run root, while a path outside it names the environment and must not be relativised. A near-duplicate was drafted, swept, and deleted rather than landed beside it. |
| written | the other twelve | one per record |

Every rule is **Bucket A**, including the three the brief flagged as possible
Bucket T. All three are plugin-side emitters: the antenna report is written by
plugin Python `write_text`; the stage stamp is emitted by plugin-generated tcl;
the power header and its session script are both plugin-authored. The tool
supplies numbers, the plugin composes the claims.

## Two true positives, found on first run

* `ip_catalog_reproduce_pull._git_clone_shallow` checked out the pinned commit
  best-effort, swallowed both calls and returned success regardless — so a
  reproducibility verdict about a PINNED COMMIT could be computed against
  whatever the default branch held, with nothing naming the compared revision.
* `_emit_antenna_report` emitted a RESOLVED subject block and, in the same
  write, a typed `Source:` path. Two source claims, one of which can never look
  wrong.

## The finding that outlived the brief: gates that fail open

Each of the twelve was then run against the scenario its RECORD describes, not
the fixture its implementation invites. **Ten gates failed OPEN** — each returning
rc=0 with the defect present — and **two failed CLOSED**, which is the rarer and
more embarrassing direction. All twelve are gates written to catch the very class
of defect they were committing.

The ten fail-open are the first ten rows below. The two fail-closed are the
eleventh row (a static literal scan declaring a WORKING axis unprovable, rc=1)
and, recorded further down, the disclosure check at FUNCTION granularity
reddening `_resolve_clock_spec`, which hands its provenance to the artefact by a
route a per-function rule cannot see. Counting the eleventh row among the
fail-open — as an earlier draft of this sentence did — would have been the same
error as the gates themselves: one label stretched over two different facts.

| gate | it passed on |
|---|---|
| `prepared_checkout_states_the_revision_it_holds` | its own headline case — a stale local ref resolves fine, so the upstream fallback was unreachable. Its test asserted `rc in (0,1,2)` and could not fail. |
| `local_clone_does_not_borrow_objects` | the borrowing option held in a list one assignment away |
| `printed_remedy_runs_as_printed` | the image reference held in a constant |
| `signoff_report_states_its_stage` | `# TODO: we should write STA_BASIS here one day` |
| `generated_values_state_whether_they_were_read_or_defaulted` | `# we deliberately ignore matched_key / source / line here` |
| `provenance_value_is_resolved_not_constant` | the typed path held in a constant |
| `measurement_only_artefact_is_not_a_verdict_source` | the disclaimer nested one level down |
| `pytest_aggregate_carries_its_runtime_identity` | `{"image": "unknown", "interpreter": "n/a"}` |
| `declared_basis_matches_the_session_inputs` | a corpus where NOT ONE pair declares a stage — a vacuous pass |
| `only_the_declaring_step_writes_its_output` | a shell writer beside a Python one |
| `every_required_metric_key_has_a_producer` | (opposite direction) declared a WORKING axis unprovable, because producers build metric names by format and no literal scan can see them |

Two of these deserve to be read twice. A comment ADMITTING a defect certified it
away, in two separate gates — the defect certifying itself. And a runtime stamp
reading `"unknown"` passed the gate whose entire purpose is to make an aggregate
name its runtime: the absence of an identity wearing the shape of one, which is
this capture's own seam turned back on the instrument.

**None of the TEN was findable by re-running verification**, because in each of
those the bug WAS the pass, and verification looks for confirmation. The two
fail-closed ones are the opposite: they announce themselves, and both were found
within minutes of being written. That asymmetry is the argument for building the
record's scenario rather than the implementation's fixture — the failures that
announce themselves need no such discipline, and they are not the dangerous ones.

## The rule that generalises

`only_the_declaring_step_writes_its_output` documented its DATA-FLOW limit from
the start, and that limit was never mistaken for coverage. It did NOT document
its LANGUAGE limit, and that is precisely the one that bit.

> A gate's undisclosed boundary is the one that bites.

Every blind spot above lived in the gap between what a gate CHECKED and what it
CLAIMED — the same defect class as an artefact that cannot say what it measured,
one level up. All twelve now state their boundaries, and
`programs/tests/test_chip_path_rules_rc_contract.py` pins the family contract:
a crashing scan is rc=2 and says so, a bad invocation is rc=3, an empty
population is rc=2 with zero finding lines. It is proven able to fail.

## State at hand-off

* 216 tests across the thirteen test files; 97 across the ratchets a new program
  trips; D1 program-test-coverage PASS over 1250 programs; D2 PASS; shipped-path
  portability rc=0; 53 d9 tests pass with no pinned count disturbed.
* Sweeps over this repository: NINE rc=0, TWO rc=1, one rc=2. (It was ten/one/one
  until `every_required_metric_key_has_a_producer` was corrected — see below.
  The TREE did not change; the instrument did.)
* On two real published run cells the twelve produce **zero** findings; the ones
  with nothing to say answer NOT CHECKED rather than PASS.

### What is NOT settled, and needs an owner

1. **Six flow-declared outputs have two independent writers.** Verified
   pair-by-pair by AST as genuinely independent, not delegation. Which write
   survives is execution order, so the same tree can grade either way. This is
   why `only_the_declaring_step_writes_its_output` exits 1 on this repository —
   a statement about the REPOSITORY, not about any run — and it must not be
   wired as a blocking gate until these are resolved.

   **One of the six needs no judgement.** Resolved against the declaring step's
   own `programs:` key, which is where the flow names a PRODUCER (gate clauses
   name VERIFIERS and must not be read as ownership):

   | declared output | step | flow-declared producer | verdict |
   |---|---|---|---|
   | `reports/spare_cell_coverage.json` | 18 | `spare_cell_coverage_check` | **owner is declared**; `phase3_one_shot_runner` is the interloper |
   | `L21_POWER_INTENT.json` | D1 | — | flow declares no producer |
   | `eco_log.json` | 32 | — | flow declares no producer |
   | `no_eco_needed.flag` | 32 | — | flow declares no producer |
   | `extraction_coverage_report.json` | D1 | — | flow declares no producer |
   | `extraction_coverage_report.md` | D1 | — | flow declares no producer |

   **CORRECTION to the sentence that first stood here.** I wrote that the other
   five are "declared by steps that name no producer at all", and that an output
   the flow requires but names nobody for is how two writers arrive. That was
   wrong, and it was wrong the same way my first pass at this table was: I read
   ONE key and treated its absence as absence of the fact.

   The flow declares producers through THREE mechanisms, and measured across all
   197 declared outputs:

   | producer declared via | outputs |
   |---|--:|
   | `programs:` | 137 |
   | `skills:` (skill-driven steps, e.g. D1 with 18 skills) | 55 |
   | `mcp_tools:` (steps 21 and 37, e.g. `eda_pnr`, `eda_gds`) | 5 |
   | **none** | **0** |

   So every declared output DOES have a declared producer. The other five
   dual-writer paths are declared by steps whose producer is a SKILL (D1, 32),
   which is why no `programs:` entry names them — not because nobody is
   responsible. What a person still has to decide for those five is narrower and
   more ordinary: which of two Python modules should be the one that writes an
   output whose declared producer is a skill.
2. **`clock_tree.rpt` is declared sign-off evidence and carries no stage stamp**,
   and the stamp has exactly two values. A report written after CTS and before
   routing can answer neither honestly. Closing it needs a third value in the
   stamp's vocabulary, not a stamp chosen at random. Disclosed on every run.
3. **The corpus-pointer contract split is untouched.** `_corpus_location` says
   the pointer replaces a MISSING corpus only; three consumers deliberately say
   the opposite. This lane enforces only the half both sides already do — the
   announcement — and pins that neutrality with a test.

## Ruling F13 — four rules that shared a name with another lane

An independent verifier found four programs existing under the SAME filename on
this branch and on the matrix lane's, as independent rewrites (360-529 lines
differing each), with different CLIs and — on two of them — OPPOSITE verdicts
about the same tree. The split was a policy difference, not a bug in either lane:
a WIDE population with an inventory of recorded waivers, versus a NARROW
population with no inventory.

The ruling, which is the owner's and is recorded here rather than argued:

* **The four filenames are the GATES, and the gate is the refusing one.** An
  instrument that cannot go red on a real defect is not a gate, and a gate that
  is green because its own inventory absorbed the findings is the shape this
  whole capture exists to remove. These four are unchanged.
* **The other lane's work becomes a CENSUS** under its own names, keeping its
  inventories, wired to nothing blocking. A census over 1273 modules is more
  informative than a gate over 2; letting it stand in for the gate is what is
  refused.
* **`phase3_one_shot_runner`'s typed `Source:` path** — the repair stands. The
  verifier reproduced it as a true positive by reverting it. A defect with a
  reproduced red gets fixed, not inventoried.
* **`reports/spare_cell_coverage.json` stays a LIVE FAIL**, and the other lane's
  reason for not repairing it was upheld: "fixing the clobber alone would turn
  the cell green while leaving the real gap invisible." That earns a LEDGER ROW,
  not a waiver — which of the two writers is the declaring producer is a
  flow-ownership decision, decided in the open, with the gate red until it is.
  This is why `only_the_declaring_step_writes_its_output` exits 1 here BY DESIGN.
* **The checker whose filename began with `test_` was renamed** to
  `pytest_aggregate_carries_its_runtime_identity`. pytest collected it as a test
  module, and — worse — several of its own sibling gates exclude `test_*` from
  their populations, so the checker was invisible to the family it belongs to.

  **The class is closed, not just the instance.** Counted afterwards: shipped
  programs at `programs/` top level whose basename begins with `test_` — **0 on
  this branch and 0 in the composed tree**. So no other checker is hiding from
  the gates behind the collection prefix, and the exclusion those gates apply is
  now exactly what it claims to be: it skips tests, not programs.

### Composing with the census lane — measured, and the landing recipe

Trial-merged against `jdistmat/matrix-distil` @ `bebd9c1e1` in a throwaway tree
and discarded; nothing was pushed and no add/add conflict was hand-merged.

**The eight add/add conflicts are gone.** After the ruling's renames — these four
filenames to the gates, the other lane's to `<rule>_census.py` — the four gates
and the four censuses coexist.

Which implementation survives at each of the four filenames was then checked by
BLOB HASH rather than inferred from the CLI shape, because "it takes a positional
path so it must be the gate" is a proxy and this is the one thing the ruling
turns on:

    composed blob == this lane's blob, for all four programs AND all four tests

so the ruling is satisfied byte-for-byte, with the census beside each. The gates still refuse correctly in composition:
`only_the_declaring_step_writes_its_output` rc=1, the other three rc=0.

**Four conflicts remain and NONE may be hand-merged.** All four are generated
counter files:

    vibe-ic-marketplace/README.md
    vibe-ic-marketplace/plugins/vibe-ic/README.md
    programs/INDEX.md
    programs/PROGRAM_INVENTORY.json

Composed truth is on NEITHER side, measured:

    | population           | this lane | census lane | composed |
    |----------------------|----------:|------------:|---------:|
    | programs_top_level   |      1250 |        1254 |     1266 |
    | programs_catalogued  |      1176 |        1180 |     1192 |
    | test_files           |      2740 |        2743 |     2756 |

Taking either side, or splitting the hunks, lands a count that is wrong by
construction. **The resolution is to REGENERATE, in three steps, all of which are
load-bearing:**

1. take either side to clear the conflict;
2. run `programs/gen_program_inventory.py` and `tools/gen_programs_index.py`;
3. update the stated counts in the two bound READMEs **by key, driven by the
   drift test's own output** — never from a hand-written list of old values.

   Run `test_program_inventory_no_drift.py`, and it names every stale figure
   exactly:

       plugins/vibe-ic/README.md:222: states 1176 for programs_catalogued,
                                      tree has 1177

   Apply those pairs. MEASURED, and this is why the step reads this way: fixing
   them from a hand-maintained list of the counts I had seen before missed
   `programs_helpers_and_shims` (74 -> 75) entirely, because that population had
   never appeared in any table I had written down, and the drift test stayed red
   until the test's own output drove the edit. A list of what you remember is not
   a list of what is stated.

Step 3 is easy to skip and does not fail quietly — omitting it on a real trial
merge left three `test_program_inventory_no_drift.py` failures
(`README.md:17,42,365,467 states 1250 ... tree has 1266`). With all three steps:
0 unresolved conflicts and 23/23 drift tests passing on the composed tree.

**THIS LANE'S GATES ARE UNAFFECTED BY THE COMPOSITION.** All twelve return
exactly what they return here — nine rc=0, `only_the_declaring_step_writes_its_
output` rc=1, `pytest_aggregate_carries_its_runtime_identity` rc=2 — over the
combined source, which now includes the census lane's four new programs and their
tests. 236 of this lane's tests pass in the composed tree. So the four censuses
introduce no finding in the gates, and the gates introduce none in the censuses'
population.

### One composed failure, and it is NOT a composition artefact

Running the repo's own ratchets over the composed tree turned up two failures in
`test_issue1082_atomic_write_gate.py`. Measured on each branch ALONE:

    this lane @ 1252a5a11         atomic_artifact_write_check  rc=0
    census lane @ bebd9c1e1       atomic_artifact_write_check  rc=1
    composed                      atomic_artifact_write_check  rc=1

    census lane alone: 1254 programs parsed, 529 write their declared report
                       destination NON-atomically, residual baseline 515

So it does not arise from composing. It is pre-existing on the census lane's
branch and simply carries into the merge, with the SAME 16 unregistered
offenders in both — four `*_census.py` and twelve other programs of that lane
(`population_guard_asserts_equality_not_a_floor.py`,
`invocation_proved_by_parse_not_by_text.py`, and ten more). **None is from this
lane**, and this lane's twelve gates are not among them.

**CORRECTION — I asserted a remedy from a test's NAME and it was wrong.** I
first wrote that registering the sixteen "would be refused by the ratchet's own
test". Tested by actually doing it: adding all sixteen to
`_atomic_artefact_residual.json` makes BOTH the plain gate and `--strict` return
0. Registering is permitted by the instrument.

What the instrument enforces, at `atomic_artifact_write_check.py:274`, is

    if args.strict and len(current) > len(baseline):

— the current offender count against the count IN THE COMMITTED BASELINE. Edit
the baseline in the same change and both numbers move together, so the guard
cannot see it. Its own docstring says the residual "may only ever shrink" and the
baseline file says "this list may only get shorter", and neither is what the code
checks.

So the accurate statement is: **the instrument permits what its own contract
forbids.** By policy the sixteen should be converted to
`_atomic_artefact.write_text/write_json` — which is what the baseline's
`how_to_shrink` field says — and registering them is available but is debt
written down, not a fix. Which of the two the census lane takes is theirs to
decide; what this note must not do is tell them the instrument forbids something
it allows.

That gap is worth its own attention, and it is the same shape as everything else
in this file: a guard whose check and whose claim are not the same thing. It is
not repaired here — `atomic_artifact_write_check.py` belongs to neither lane.

Recorded here, not repaired here: they are another lane's programs, and ruling
F13 gave this lane one item. Stated so the batch assembler meets it as a known,
attributed item with a named remedy rather than as a surprise at merge time.

**Everything else in the composed tree holds:** D1 program-test-coverage PASS
over all 1266 composed programs (the four censuses all carry tests), D2 PASS,
131 of 133 ratchet/census tests pass, and this lane's twelve gates return exactly
their branch verdicts.

### Auditing this record for the failure it keeps describing

Three times in this lane I asserted a fact from a name or a docstring and was
wrong: `gate:` clauses read as ownership, `programs:` read as the only producer
declaration, and a ratchet's remedy read from its test's name. That is the same
failure the ten fail-open gates had — checking one thing, claiming another — so
the remaining claims in this record that DIRECT SOMEONE'S WORK were tested rather
than left standing on prose. Both survived.

**"The stamp has exactly two values, so a post-CTS report can answer neither."**
Exercised `_sta_basis.declared_basis` directly:

    "# STA_BASIS: POST_ROUTE_SPEF"     -> 'POST_ROUTE'
    "# STA_BASIS: POST_ROUTE_NO_SPEF"  -> 'POST_ROUTE'
    "# STA_BASIS: PRE_LAYOUT_ESTIMATE" -> 'PRE_LAYOUT'
    "# STA_BASIS: POST_CTS"            -> None
    "# STA_BASIS: anything_else"       -> None

CONFIRMED. `POST_CTS` is not merely absent from the vocabulary, it normalises to
`None` — indistinguishable from an unstamped report. So `clock_tree.rpt` genuinely
cannot answer, and "closing it needs a third value in the stamp's vocabulary" is
right.

**"The corpus-pointer contract split is real."** This is why
`explicit_argument_outranks_the_environment_pointer` enforces only the
announcement and arbitrates nothing, so it had better be true. Built a fixture
with a named directory that EXISTS and a pointer aimed elsewhere, and RAN all
four sides:

    _corpus_location.resolve(named EXISTS)   -> named     (pointer does NOT win)
    _corpus_location.resolve(named MISSING)  -> pointed   (pointer fills a gap)

    benchmark_evidence_structure_check --tree <named>
        note: VIBE_IC_BENCHMARK_DATA overrides --tree <named> -> <pointed>
    tracked_symlink_portability_check <named>
        note: VIBE_IC_BENCHMARK_DATA overrides <named> -> <pointed>
    tracked_symlink_target_present_check --subdir <named>
        note: VIBE_IC_BENCHMARK_DATA overrides --subdir <named> -> <pointed>

CONFIRMED on all four. The resolver holds one rule and all three consumers hold
the opposite, with a PRESENT named location — behaviour, not comments. The
neutrality is warranted.

One caution recorded from doing it: the first attempt passed `--tree` to all
three and two printed nothing. That was the WRONG FLAG, not agreement — they take
a positional root and `--subdir`. A non-result from a wrong invocation is not
evidence, which is the same trap as the rest of this file.

### The live FAIL is deterministic — the ledger row has a stable subject

Ruling F13 keeps `reports/spare_cell_coverage.json` red and opens a ledger row
rather than a waiver, so the gate stays red until the ownership question is
decided in the open. A ledger row is only worth anything if the thing it names
does not move, and this repository has form here: a nested-outcome bound test in
another lane passes below load ~10 and fails above it, so "it was red" can be a
statement about the machine.

Six consecutive runs of `only_the_declaring_step_writes_its_output` over this
tree, at load 6.05 / 8.88 / 7.86:

    rc=1 every run, 6 findings every run, finding set sha identical (200f1f446857)

The set, which is what the ledger row is about:

    phase1/generated_docs/L21_POWER_INTENT.json
    phase3/stage3/eco/eco_log.json
    phase3/stage3/eco/no_eco_needed.flag
    reports/phase1/extraction_coverage_report.json
    reports/phase1/extraction_coverage_report.md
    reports/spare_cell_coverage.json

So the red is a property of the tree, not of the host or the run. Of these six,
one — `reports/spare_cell_coverage.json` — already has its owner named by the
flow (step 18, `programs: [spare_cell_coverage_check]`), and the other five are
declared by steps whose producer is a SKILL, so the decision there is which of
two Python modules writes an output a skill declares.

### A note on the brief itself: `git clean -xdfq` on a SHARED checkout

The brief for this lane said "Clean tree: `git clean -xdfq`". This lane declined
it — `~/vibe-ic` held 126 untracked files that were not this lane's to delete —
and worked in throwaway worktrees cut from `origin/main` instead.

Partway through the session those 126 files were deleted from `~/vibe-ic` by
something outside this lane: all affected directories carry one mtime,
2026-08-22 10:52:42, and `HEAD` never moved. Cause unproven; the likeliest is a
sibling lane obeying the same sentence literally in the same checkout.

**The damage was low and the lesson is not.** Of the 130 paths identified, ALL are
tracked on `origin/main` — they were ordinary newer content sitting in a worktree
whose branch (`fix/1444`, an old commit) does not carry them, which is exactly why
git called them untracked. `git checkout origin/main -- tools vibe-ic-marketplace`
restores them.

Two things are worth carrying forward:

* **The instruction is unsafe as written when several lanes share one checkout.**
  `git clean -xdfq` deletes whatever any other lane happens to be holding. It
  should either name a throwaway tree, or say "work in a worktree you created".
  A brief that tells N agents to clean one shared directory is a race, and the
  only reason it cost nothing here is that the casualties happened to be
  recoverable from a remote.

* **"Untracked" is not "yours", and it is not "junk".** On a checkout parked at an
  old commit, most untracked files are simply the future. Reading the word as
  permission to delete is the same error this whole file is about: acting on a
  label instead of on the thing it labels.

### RE-MEASURED against main at v1.11.69 — the earlier numbers had a shelf life

Everything above about composition was measured against `origin/main` @
`81cd5321b`, the base this branch was cut from. **Main has since moved 214
commits to `a4caccefe` (v1.11.69)** — a different batch landed, the PPA gate
audit; none of this branch's work is on it. Re-measured against the new base:

| | vs old main `81cd5321b` | vs new main `a4caccefe` |
|---|---|---|
| conflicts | 4, all generated counters | **4, same four files** |
| the three-step regeneration recipe | verified | **still applies unchanged** |
| this lane's twelve gates | 10 rc=0, 1 rc=1, 1 rc=2 | **identical** (both figures predate the metric-gate correction; now 9 / 2 / 1) |
| `only_the_declaring_step` finding set | 6 paths, sha `200f1f446857` | **6 paths, sha `200f1f446857`** |

So main's 214 new commits trip none of these gates, and the LEDGER ROW STILL
NAMES THE RIGHT PATHS — byte-identical finding set across a 214-commit move of
the base. The red is a property of those six declared outputs, not of a
particular main.

The composed COUNTS do move, and they are the one thing above that should not be
quoted from the older table: against v1.11.69 the composed inventory is
1252 / 1177 / 2760, not the 1266 / 1192 / 2756 measured against the census lane
on the old base. That is exactly why the recipe REGENERATES rather than picking a
side — the right number is whatever the generators say at assembly time, and any
number written down here is only true of the base it was measured against.

**The branch is verified current against `a4caccefe` (v1.11.69) on every axis:**
4 conflicts (the same four counter files), 0 unresolved after the recipe, D1
program-test-coverage PASS over 1252 composed programs, D2 PASS, 23/23 inventory
drift, 216 of this lane's tests passing, and the twelve gates returning their
branch verdicts with `only_the_declaring_step`'s six-path finding set
byte-identical.

### The census lane's gate disagreed with mine, and mine was wrong

Their branch moved to `f55027d18` and added `gate_proof_vocabulary_has_a_producer`,
which BLOCKS and says the `drv` axis is unprovable. My
`every_required_metric_key_has_a_producer` said PASS on the same tree. One of us
had to be wrong; measuring it showed it was me, twice over.

**1. The consumer was counted as its own producer.** My gate credited any JSON row
carrying `"metric": <key>`. The feasibility checker writes its OWN report listing
every proof name it looked for, including the ones it could not find:

    {"metric": "timing.drv.violations", "state": "NO_RECORD",
     "reason": "no record in this candidate names this metric"}

205+ record files carry the drv names for exactly that reason. Crediting them made
the adjudicator its own evidence — the defect this rule exists to catch,
committed by the rule.

**2. My two gates contradicted each other.** After fixing (1) the axis still
passed, on canonical `vibeic.ppa.metric.v1` records with `status: NOT_MEASURED` —
61 files. Meanwhile my sibling gate,
`measurement_only_artefact_is_not_a_verdict_source`, refuses a NOT_MEASURED record
as verdict evidence BY NAME. Same family, same records, opposite treatment, and
the flattering one winning. Now consistent.

**The corrected verdict, counted exactly:**

    equivalence.verdict          MEASURED 0    NOT_MEASURED 370
    reliability.em.violations    MEASURED 0    NOT_MEASURED 370
    reliability.em.worst_ratio   MEASURED 0
    physical.drc.violations      MEASURED 227
    timing.setup.wns_ns          MEASURED 485

So `em` and `equivalence` have no measured evidence in any published run, and this
gate now exits 1 — a second true positive, reached independently of the other
lane and by a different route.

**And the wording was an overclaim.** It said "STRUCTURALLY UNPROVABLE … on any
design, forever" — a claim about all possible runs, from a corpus. This gate is
EMPIRICAL: it can say what the runs it can see did. It now says exactly that, and
names `gate_proof_vocabulary_has_a_producer` as the instrument for the source-level
question. The two are complementary, not rivals, and the disagreement was worth
more than either verdict.

One caution from doing it: I nearly dismissed my own finding because a grep
reported "408 MEASURED rows" for `reliability.em.violations`. It was counting
`NOT_MEASURED`, which contains `MEASURED`. Fourth substring trap of this lane, and
the first that would have reversed a correct conclusion.

The second live FAIL is deterministic too, checked the same way as the first:
four consecutive runs, the same two axes, finding-set sha `daa3f10510bb`.

    axis 'em'          IS NOT PROVEN BY ANY RUN IN THIS CORPUS
    axis 'equivalence' IS NOT PROVEN BY ANY RUN IN THIS CORPUS

Re-verified against both current tips: rc=1 against main `a4caccefe` (v1.11.69)
and rc=1 against the census lane `f55027d18`, so the verdict is a property of the
published records rather than of which branch it is composed with.

**The sweep tally is now nine rc=0, two rc=1, one rc=2.** Both reds are true
positives with stable subjects; the rc=2 is a repository correctly reporting that
it is not a run tree.

### A measurement that contradicts the census lane's BLOCKING gate — for the assembler

`gate_proof_vocabulary_has_a_producer` (census lane, `f55027d18`) blocks with
rc=1 and states:

> ONE axis has NOT ONE of its proof names produced: `drv` … The drv axis is
> structurally unprovable — no run of this flow can produce the evidence it
> proves from, on any design, ever.

**The published records contradict the conclusion.** Counting canonical
`vibeic.ppa.metric.v1` records under `ppa-crosslayer/` and `ppa-e2e/`, by key:

    timing.drv.violations             MEASURED   0    NOT_MEASURED 122
    timing.drv.max_tran_violations    MEASURED  63    NOT_MEASURED   0
    timing.drv.max_cap_violations     MEASURED  63    NOT_MEASURED   0
    timing.drv.max_fanout_violations  MEASURED  63    NOT_MEASURED   0

in `drv_records.json` and `candidates.json`. **Provenance checked before relying
on it**, because a count that overrides another lane's blocking gate has to be
better evidenced than the claim it overrides: the 63 MEASURED rows are spread
across **21 distinct trial directories** under `ppa-crosslayer/records/trials/`
(p04, w03, z14, u04, u01, …), and each is a canonical record citing its source
artefact by path and hash —

    {"schema": "vibeic.ppa.metric.v1",
     "metric": "timing.drv.max_tran_violations", "status": "MEASURED",
     "scope":  {"stage": "post_route", "tool": "opensta", "check": "drv"},
     "source": {"path": ".../phase3/stage3/sta/sta_spef_multicorner.rpt",
                "sha256": "sha256:7e4e6a1221e3a4c4…", "tool": "opensta"}}

So these are real runs attributing the measurement to OpenSTA multicorner SPEF
reports — 21 independent trials × 3 keys = 63 — not fixtures written to satisfy a
test. The `drv` axis is an OR of ANDs —
group 1 is `[violations]`, group 2 is `[max_tran AND max_cap AND max_fanout]` —
and **group 2 is fully measured, 63 times**. Real runs prove this axis.

**Both halves can be true, and that is the point.** Their gate asks a SOURCE
question and its premise is correct: no module declares those literals, which I
verified independently. The error is the step from "no literal is declared" to
"no run can ever produce it" — the names are built dynamically, and 63 records
exist that the source scan cannot see.

That is the same error this lane made and fixed. `every_required_metric_key_has_
a_producer` was written as a static literal scan, declared the drv axis
unprovable, and was rewritten to be EMPIRICAL for exactly this reason — the
producers build names by format (`_ppa/timing.py:651`). After that rewrite this
lane's gate does NOT flag drv, and flags `em` and `equivalence` instead, which
have 0 MEASURED against 370 NOT_MEASURED apiece.

**What the assembler needs to know:** a gate that BLOCKS is asserting the drv
axis can never be measured, and 63 published records measure it. This is not a
composition conflict and not a merge problem — it is a factual disagreement about
the tree, decidable by counting, and the count is above. Not repaired here: it is
another lane's program and this lane has no standing to edit it.

**The gate was then run properly, because I had only inferred that it blocks.**
An earlier attempt passed it a positional path and got rc=3 — a BAD INVOCATION,
not a verdict, and this file has already recorded twice that a non-result from a
wrong flag proves nothing. It takes `--root`. Correctly invoked:

    feasibility axes: 9   emitting modules: 18   names they declare: 110
    [FAIL] 1 axis/axes prove from names nobody produces:
       drv:  timing.drv.violations
             timing.drv.max_tran_violations
             timing.drv.max_cap_violations
             timing.drv.max_fanout_violations
    rc=1

rc=1 **on their branch alone and in the composed tree**, so it will block the
batch, and it flags all four names exactly as its docstring says. The count above
stands unamended: three of those four are carried MEASURED by 63 canonical
records across 21 trials with OpenSTA provenance.

One near-miss worth recording, since it would have put a false correction in
front of the assembler: reading that output with `head -8` showed only
`timing.drv.violations`, and I began writing a note saying their gate's real
finding was narrower than its docstring. It was not — the list was simply cut off.
Truncation is not absence, which is the same mistake as every other one in this
file, and the second time in two turns that a display artefact nearly reversed a
correct conclusion.

### The drv dispute is RESOLVED: the producer exists, outside the scanned scope

Chasing the last possibility — that the 63 records were historical, emitted by a
producer since removed, in which case their gate would be right about the tree and
MY gate would be crediting dead artefacts — found the producer alive:

    ppa-crosslayer/tools/drv_records.py:73
        _CHECKS = (("timing.drv.max_tran_violations", "max_slew",  "set_max_transition"),
                   ("timing.drv.max_cap_violations",  "max_capacitance", "set_max_capacitance"),
                   ("timing.drv.max_fanout_violations","max_fanout","set_max_fanout"))

    ppa-crosslayer/tools/drv_records.py:156
        r = {"schema": "vibeic.ppa.metric.v1", "metric": metric,
             "status": "MEASURED" if value is not None else "NOT_MEASURED", ...}

It declares all three names explicitly, emits canonical records, hashes its source
artefact, and is the origin of the 63 MEASURED rows across 21 trials.

**So the FAIL is a SCOPE artefact.** Their gate counts "18 emitting modules" — the
plugin's `programs/` — and this producer lives under `ppa-crosslayer/tools/`,
outside the directory it scans. Its premise is true of its scan root and false of
the repository. Nobody misread anything; the population boundary excluded a real
member, silently.

That is the same defect this lane fixed in itself twice: the `test_*` exclusion
that hid a checker from its own family, and the Python-only writer scan that could
not see a shell writer. **A gate's undisclosed boundary is the one that bites** —
stated earlier in this file about my own gates, and it turns out to be the whole
of this dispute.

**For the assembler:** the drv axis is provable, by a live producer, with 63
records to show for it. The remedy is a scope question — either the gate widens to
the trees that actually emit metric records, or it states that it speaks only for
`programs/` and stops concluding "on any design, ever" from that. Still another
lane's program; still not repaired here.

### The same lesson, applied to my own gate an hour later

Having diagnosed the other lane's FAIL as a verdict claiming more than its check
established, the obvious next question was whether mine did too. It did.

`every_required_metric_key_has_a_producer` ended its FAIL with

    "an axis proves from a metric nothing emits"

and that is FALSE of what it finds. Both flagged axes HAVE live producers —
`_ppa/signoff.py` (inside the plugin) and `ppa-e2e/tools/signoff_records.py`
declare `reliability.em.violations` and `equivalence.verdict` by name. What is
true is that no run ever MEASURED them: 0 MEASURED against 370 NOT_MEASURED each.

The filename asks a WIRING question. The finding is about EVIDENCE. The verdict
line now says evidence, and says explicitly that a producer may exist and never
have measured it.

Three gates in this repository, in one day, whose verdict line named something
other than what the check established — two of mine and one of another lane's.
That is not a coincidence and it is not carelessness; it is what happens when a
rule is named for its intent and then implemented against what is measurable. The
name is a hypothesis about the check. It has to be re-read against the code every
time the check changes, and none of the three was.
