# The search publishes a stub's excuse as its verdict, over a space nothing emits

Three items from the sixty-point end-to-end run: **F-12**, **F-1**, **R11**. The
brief called them one fix in three steps, and they are: each is a program stating
something about the world that nothing checked.

    F-12   a stub's reason names a condition it never re-checks
    F-1    a program names an owner that does not exist
    R11    a program uses a library nobody declared, guarded by the wrong question

**Base:** `origin/main` @ `e36d81c0a` (v1.11.33), fetched 2026-08-21 09:39 +0800.
Cut fresh into `/home/reyerchu/_jsearch2/wt`; `git status --porcelain` was empty
at the cut and every measurement below is against that base.

**Branch:** `jsearch2/space-and-feasibility` — 3 commits, 17 files,
+3024 / -93.

Full before/after console transcript: `EVIDENCE.txt` beside this file.

---

## The headline the base tree hands you

Two facts measured on `origin/main`, before a line was written:

```
$ python3 programs/ppa_contract_check.py --contract <a contract this repo's own fixtures build>
AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
rc=1
```

```
$ python3 -c "from _ppa import search as S; print(S.stub_feasibility(S.Candidate({})).reason)"
feasibility lane not wired: _ppa/feasibility.py has not landed, ...
$ ls programs/_ppa/feasibility.py
programs/_ppa/feasibility.py
```

The first is a crash returning **rc=1**, which in this contract means *a finding
about a design*. **33 tests of this repository were red on this host for that one
reason** — and nothing in the suite said why.

The second is the sentence that went into sixty published manifests, printed
directly above proof that it is false on the same tree.

---

## F-12 — the search hard-wires the feasibility stub, and the stub's reason is false

### What was there

`ppa_search_run.py:243` was `ledger.evaluate_feasibility(None)`. `Ledger` accepts
an injected `FeasibilityFn`; the CLI had no flag to supply one. So **every
manifest a downloaded plugin could produce marked every candidate UNDETERMINED
and published an empty Pareto frontier**, and the toolchain block carried
`stub_feasibility`'s reason verbatim — a string literal asserting that
`_ppa/feasibility.py` had not landed. It landed at v1.11.26; the search landed at
v1.11.29.

### The second half is the one that generalises

A stub that names a condition — *"X has not landed"* — must **check that
condition at the moment it speaks, or not name one**. A hard-wired excuse that
outlives its cause is how a false sentence gets into a published record and stays
there. Both directions are now closed:

**Generation.** `stub_feasibility` measures the tree on every call and writes one
of two sentences. Neither is stored, so neither can rot:

| tree | what it says |
|---|---|
| module absent | `feasibility lane not wired: _ppa/feasibility.py has not landed on the tree that produced this record, …` |
| module present | `no feasibility function was supplied to this search: _ppa/feasibility.py IS present on this tree but this run did not consult it, …` |

The honest case keeps its diagnosis — the fix is not "delete the sentence".

**Audit.** `--verify` gains `STUB_REASON_CONTRADICTED_BY_TREE`. A manifest
publishing `<path>.py has not landed` about a file present on the auditing tree
is **rc=1**. Driven against the exact record that shipped sixty times:

```
[REFUSE] 3 finding(s): this manifest does not describe the run it claims.
  STUB_REASON_CONTRADICTED_BY_TREE: toolchain.feasibility_note publishes as fact
  that _ppa/feasibility.py has not landed, and _ppa/feasibility.py is present on
  the tree auditing this manifest (…/programs/_ppa/feasibility.py). A stub reason
  that names a condition must check that condition at the moment it speaks; this
  one outlived its cause and was published as a fact.
rc=1
```

It is **conservative by construction**: a claim naming a path that does *not*
resolve here yields nothing at all. A manifest published honestly against a tree
where the claim was true does not redden — asserted by
`test_a_claim_about_a_module_that_really_is_absent_is_not_a_finding`.

### The gate is now reachable

`--feasibility-policy PATH` adjudicates every trial that RAN with the shipped
hard gate against the required views and limits that document declares. It
**discriminates**, which is the part an empty frontier could never show:

| candidate | evidence | verdict | frontier |
|---|---|---|---|
| `state_encoding=binary` | nine axes clean | `ELIGIBLE`, nine terms `PASS` | **included** |
| `state_encoding=gray` | same set, `physical.drc.violations: 7` | `INELIGIBLE`, `drc: FAIL` | excluded `NOT_ELIGIBLE` |

`included_count` goes from 0 to 1 on the same fixture. The exclusion code is
`NOT_ELIGIBLE`, not `FEASIBILITY_UNDETERMINED` — *"we checked and it fails"* and
*"we never checked"* still do not share a code, and a test asserts it.

Nine axes, and any one of them refuses: parametrised over setup slack, LVS
verdict, antenna count and equivalence verdict, so a gate that only ever noticed
DRC — the ORFS `num_drc` mistake this lane exists to avoid — would not pass.

### Three decisions worth naming

**The bridge is a third module.** `_ppa/search.py` says in its own docstring that
it does not decide feasibility. A search module that could reach into the
promotion gate is a search module that could grade its own homework, so
`_ppa/search_feasibility.py` imports both and neither imports it.

**The stub stays the default.** A search that has not been told what views a
promotion verdict must cover cannot decide one, and a default view set would
credit a one-corner run as signoff. A policy declaring no view returns
UNDETERMINED for every candidate, and says so.

**A policy that could not be READ is rc=2, never a fall-through to the stub.**
Falling back there would publish a stub verdict under a manifest saying a policy
was applied — the same class of defect as the one being fixed.

**No waiver travels the bridge.** A waiver is a named owner accepting *one*
violation on *one* run; a point in a search space is not a run. The candidate
document carries `metrics` and nothing else, asserted by a spy test. This is also
why no existing gate clause had to be relaxed: `AXIS_WAIVED` is unreachable on
this path, so `audit_manifest`'s `ELIGIBLE_ON_A_PARTIAL_VECTOR` clause is
untouched.

---

## F-1 — no program emits the PnR search space, and the one that exists excludes it

### What was there

`crosslayer_search_space.py` withheld eight place-and-route levers with:

> *"these are the place-and-route knobs the PnR-only search already owns"*

Measured on the base tree: **there is no PnR-only search.** The only two files
naming those levers are the one that excludes them and the runner itself. So a
downloaded plugin had no space document for the knobs its own runner exposes, and
the sentence named an owner a reader could not find. The end-to-end run
hand-authored a space — which is the part that matters: the published record
cited a space nothing could re-emit.

### `ppa_pnr_search_space.py`

Emits a space in `crosslayer_search_space.py`'s output shape, so
`_ppa.search.values_from_space` reads it unchanged. **Nothing in it is asserted
about the flow. It is measured against the runner, twice over:**

**Admission** is read from `phase3_one_shot_runner.py`'s own argparse surface
(AST, 0.16 s, no import). A lever is admitted only when a flag that applies it is
really on the CLI, cited `path:line` — a citation asserted against the file's
actual bytes by test. On this tree:

| lever | verdict | flag |
|---|---|---|
| `placement_density` | EXPOSED | `--util` @ `phase3_one_shot_runner.py:40136` |
| `die_geometry` | EXPOSED | `--die-um` @ `:40132` |
| `spare_cell_density` | EXPOSED | `--spare-density` @ `:40159` |
| `core_utilisation`, `core_aspect_ratio`, `cell_padding`, `cts_cluster_size`, `cts_cluster_diameter`, `routing_layer_adjust`, `clock_period` | NOT_EXPOSED | none of the flags looked for |

The seven refusals are **published**, each naming the flags searched for.
"This flow cannot search cell padding" is a fact a reader of a search record
needs, and an absent row does not state it.

**A value** is round-tripped through the runner's *own* normaliser. This catches
a defect I did not expect to find:

```
$ ppa_pnr_search_space.py --values placement_density=0.3,1.5
[REFUSE] placement_density=1.5: phase3_one_shot_runner.py._normalize_util()
  would apply 0.015, not '1.5' — --util=1.5 > 1: … interpreting 1.5 as a
  percentage … A candidate naming a value the runner does not use is a candidate
  whose knobs do not describe its run.
rc=1
```

`--util 1.5` is **not an error** in the runner — it is read as 1.5 % and becomes
`0.015`. Two candidates differing only there are the same run wearing two names,
and the manifest publishes the knob, not the value. Same for `--spare-density
0.5 → 0.2` (ceiling) and `-1 → 0.0` (floor). The positive control is the same
fixture: `0.3,0.45,1.0` is accepted, so "it refuses everything" cannot pass for
"it discriminates".

### It invents no value

Which values to try is a decision about a design and a machine budget. A program
that made it would be choosing what the search should *try first* while claiming
to describe what *may be searched*. So an admitted lever's domain is prose — the
search records it `NOT_ENUMERABLE` and says plainly it did not vary the lever —
until a caller supplies values, which are recorded as **the caller's**.

### End to end, which is the whole point

```
$ ppa_pnr_search_space.py --json space.json \
      --values placement_density=0.30,0.20,0.40 \
      --values die_geometry=auto,210x210 \
      --values spare_cell_density=0.02,0.00,0.05
$ ppa_search_run.py space.json --max-trials 60 --max-full-pnr-trials 60
proposed 18   distinct points 18   space_digest sha256:ef6f9e18627e9e04…
```

Baseline first, and it is the runner's own defaults — `_ppa.search.propose` takes
the first value on every axis, so a caller listing defaults first gets the
default run as the reference point rather than a lucky draw. Asserted by test.

### And the sentence in the other program

`crosslayer_search_space.py` now **checks for the owner as it writes the
sentence**, and lists the owner's own lever names rather than a remembered copy —
so a name here that the owner never emits (the state this pair was in) cannot
occur. With the owner absent it says the levers are **UNOWNED**, not delegated.
That is F-12's rule applied to F-1, and it is why the two are one fix.

---

## R11 — `jsonschema` is used and not declared

### Reproduced first, and it is worse than the brief describes

| arm | `origin/main` behaviour |
|---|---|
| `jsonschema` **absent** | `[CANNOT CHECK]` PPA-C-010, **rc=2**. Honest — and the contract's shape is never checked on a fresh install, so the flow does not complete. |
| `jsonschema` **3.2.0** (this host's system package) | `import jsonschema` **succeeds**. The shipped schemas declare draft 2020-12; `Draft202012Validator` arrived in 4.0. The guard caught `ImportError` only → uncaught **AttributeError**, **rc=1**. |

The second is a crash publishing itself as a design finding, on a host that *has*
the library. It is why **"declare it" alone is not the fix**: a declaration does
not change what happens to somebody who already has the version their
distribution ships. So: **both**.

### Declared

`_ppa/schema_validation.PREFERRED` is the single machine-readable statement —
distribution, minimum version, why, and the install line. Every message that asks
a user to install something is *built from it*, so advice cannot drift from need.
And `jsonschema` is now imported in **exactly one place**, enforced by
`test_jsonschema_is_imported_in_exactly_one_place`. A new caller either inherits
the version probe and the fallback, or reddens.

### Bundled

`_ppa/jsonschema_bundled.py` implements the keyword set the ten shipped schemas
use — *measured*: 29 keywords, 7 types — plus the symmetric partners of what they
use, because implementing `minimum` and refusing `maximum` is an edge nobody
could predict.

**The rule that makes a hand-written validator safe is that it refuses.** A
re-implementation that quietly ignores a keyword reports clean over a rule it
never applied, which is this package's own defect reappearing in the tool that
removes it. `unsupported()` walks the schema **eagerly** — a keyword on a branch
a passing instance never takes would otherwise never be reached — and any
construct it cannot apply is UNDETERMINED with the construct named, its JSON
pointer given, and the real library offered as the remedy. It never skips one
keyword and checks the others.

### The differential arm

Correctness is not "it passes my own fixtures". Both engines were run over the
same corpus and required to agree case by case:

```
schemas: 10   documents compared: 4510   DISAGREEMENTS: 0
```

against `jsonschema` **4.26.0**, over all ten shipped schemas × systematically
mutated real documents (every JSON path of a real contract and its embedded run
manifest × delete/null/0/-1/1.5/true/false/""/long-string/[]/{}/digest/status,
seeded `20260821`). The arm ships as a test; on this host six 2020-12 schemas skip
for want of a reference, and `test_at_least_one_pair_was_compared` asserts the arm
is not entirely vacuous rather than leaving it to be assumed. With
`PYTHONPATH` pointing at a 4.26.0 install: **167 passed, 0 skipped**.

### Measured after

| arm | behaviour |
|---|---|
| `jsonschema` 3.2.0 | `[PASS]` **rc=0**, shape validated by the bundled engine, which is *named in the notes* |
| `jsonschema` absent | `[PASS]` **rc=0**, same |
| `jsonschema` absent, **broken contract** | `[FAIL] PPA-C-010: … 'not-a-sha' does not match '^sha256:[0-9a-f]{64}$'` + `Additional properties are not allowed`, **rc=1** |

The third row is the one that matters: the fallback **discriminates** with no
library on the host at all.

### Six test modules that were skipping the question

`test_ppa_contract.py`, `test_ppa_metrics_schema_agreement.py`,
`test_ppa_search_run_cli.py`, `test_ppa_feasibility.py`, `test_ppa_report_gen.py`
and `test_ppa_timing.py` opened with `pytest.importorskip("jsonschema")` — the
wrong question twice over. On a 3.2.0 host the import *succeeded* and every test
then died on the missing class, so the honest skip they documented never
happened; on a bare host they skipped, which meant schemas this repository ships
were checked only where somebody happened to have the right library. They now
resolve the engine. That is **strictly stronger** — they run in more environments
than before — and the skip arm survives for the case where no engine can apply a
schema at all.

---

## The whole chain, on a host with NO `jsonschema` at all

This is the owner's standard stated as a command sequence: download the plugin,
run it, the PPA flow completes. Driven with the library blocked at the import
hook (`BARE_HOST.txt`):

```
### 0. confirm the host really has no jsonschema
ImportError: No module named 'jsonschema'

### 1. emit the PnR search space (F-1)            rc=0   3 levers admitted
### 3. run the search WITH the real gate (F-12)   rc=0
### 5. audit the manifest                          rc=0
### 6. the contract gate                           rc=0   [PASS]
```

and step 4, which is the one to read twice:

```
   {"placement_density": "0.20", "spare_cell_density": "0.00"}   ELIGIBLE     area=7250.0
   {"placement_density": "0.20", "spare_cell_density": "0.02"}   ELIGIBLE     area=7400.0
   {"placement_density": "0.30", "spare_cell_density": "0.00"}   INELIGIBLE   area=6900.0
   {"placement_density": "0.30", "spare_cell_density": "0.02"}   ELIGIBLE     area=7100.0
   frontier: 3 comparable at 'post_route_extracted'
   excluded  NOT_ELIGIBLE
```

**The smallest area is the infeasible one.** 6900 µm² wins on the objective and
carries two sign-off DRC violations, and the gate refuses it by name. That is
the whole reason the feasibility lane is separate from the search penalty — and
it is exactly the discrimination the hard-wired stub could not perform: under the
stub all four came back UNDETERMINED and the frontier was empty, which is safe
and says nothing. Three of these four points are now comparable and the fourth is
excluded for a stated, measured reason.

None of the three steps could run on this host before this branch: step 1 had no
producer, step 3 had no flag, and step 6 crashed with an AttributeError.

---

## A/B by TEST ID

Base `e36d81c0a` vs `HEAD`, same 99 test files, **serial** (`-p no:randomly`, no
`-n`), same host, base arm first. Full ID lists in `AB_base_ids.txt` /
`AB_head_ids.txt`.

<!--AB_TABLE-->

---

## Mutation arms — every fix, reverted, reddens a named test

| # | reverted | reddens |
|---|---|---|
| **F-12 a** | `stub_feasibility` back to the hard-wired literal | `test_the_stub_reason_does_not_claim_an_unlanded_module_that_is_present` (+2) |
| **F-12 b** | remove the `STUB_REASON_CONTRADICTED_BY_TREE` clause | `test_the_sixty_manifests_are_rc1_with_a_named_finding`, `test_a_false_claim_in_a_candidate_reason_is_also_caught` |
| **F-12 c** | re-hard-wire `evaluate_feasibility(None)` | `test_a_violating_candidate_is_ineligible_and_the_axis_is_named` (+6) |
| **F-1 a** | stop asking the runner what it would do with a value | `test_a_value_the_runner_would_change_is_refused` ×3 |
| **F-1 b** | publish a space instead of refusing when the runner has no CLI | `test_a_runner_that_parses_to_no_cli_is_rc2_not_an_all_refused_space` |
| **F-1 c** | admit a lever with no flag citation | 13 tests incl. `test_every_admitted_lever_cites_the_flag_that_applies_it` |
| **F-1 d** | revert the crosslayer reason to the un-checked literal | `test_the_crosslayer_exclusion_reason_names_an_owner_that_exists` (+1) |
| **R11 a** | bundled engine ignores an unimplemented keyword | `test_an_unimplemented_construct_is_named_not_ignored` (+4) |
| **R11 b** | make the unsupported walk lazy (top level only) | `test_an_unimplemented_construct_NESTED_DEEP_is_still_caught` |
| **R11 c** | revert to import-and-attribute | `test_an_old_library_names_the_version_and_the_remedy` |
| **R11 d** | remove the bundled fallback (i.e. the "declare only" fix) | **16 tests** — reproduces the original reds |

Every arm was restored and re-run green immediately after. **R11 d** is worth
reading twice: it is direct evidence that declaring the dependency without
bundling it would not have fixed this host.

---

## Positive / negative / vacuous, per new checker

| checker | positive | negative | vacuous |
|---|---|---|---|
| `ppa_pnr_search_space` | a space is emitted and drives `ppa_search_run` | a value the runner would change → rc=1; a lever with no flag → rc=1 | absent / unparseable runner → **rc=2** `[CANNOT CHECK]`; a runner parsing to **no CLI at all** → rc=2, because that is far likelier a surface the program failed to read than a runner with no flags |
| `ppa_pnr_search_space --verify` | a space it emitted verifies clean | admitted-via-a-flag-that-is-gone → rc=1; refused-though-the-flag-exists → rc=1 | absent / unreadable space → rc=2 |
| `STUB_REASON_CONTRADICTED_BY_TREE` | today's manifests verify clean | the sixty-manifest sentence → rc=1 | a claim about a path that does not resolve here → **no finding**, and no pass claimed either |
| `--feasibility-policy` | clean candidate ELIGIBLE, nine terms PASS | one dirty axis anywhere → INELIGIBLE, axis named | absent / empty / unparseable / non-object policy → rc=2, never a silent stub |
| `_ppa.schema_validation` | every shipped schema resolves to an engine | a bad digest is refused with no library at all | an unimplemented construct → **no engine**, reason says "this is not the schema passing" |

---

## What I could NOT settle

**The full `programs/tests` suite was not run on this host, deliberately.** It is
2707 files and the brief records it at load 276 with zero free memory. I started
one, saw the load climb, killed it by recorded PID, and scoped the A/B to the 99
files that touch anything I changed — every `test_ppa_*`, `test_crosslayer_*`, and
every corpus-sweeping gate test found by grepping for `rglob("*.py")`-style
sweeps. **Files outside those 99 are NOT_MEASURED by me.**

**The differential arm cannot fully self-verify on a host with an old
`jsonschema`.** On this host six 2020-12 schemas skip. I proved agreement by
installing 4.26.0 into `/tmp` and re-running (0 disagreements over 4510
documents), but that install is not part of the branch — the shipped test tells
you honestly that it compared fewer pairs when the reference is old.

**`--die-um` values are not checkable.** It takes `auto` or a physical `WxH`, and
the runner has no pure normaliser for it, so `values_checked_against_runner`
records `checked: false` with that reason. A caller can put a die size in the
space that the runner will later reject. I did not invent a geometry validator; a
chip-agnostic program has no basis for one.

**`core_utilisation` is refused as NOT_EXPOSED, and it is more subtle than that.**
The runner *does* have a die-sizing utilisation target — `_AUTO_DIE_TARGET_UTIL`,
a module constant, deliberately decoupled from the placement `--util`. It is not
on the CLI, so no search can move it, which is what the space says. Exposing it
is a runner change and out of this brief's scope.

**I did not touch the other nine PnR levers' absence.** The space now *reports*
that this flow cannot search cell padding, CTS clustering, routing-layer derate
or clock period. Making it able to is runner work.

**The wider undeclared-dependency class is untouched.** Censusing non-stdlib
imports across shipped programs (excluding tests) after the fix:

```
  45  yaml            e.g. _class_template_resolve.py:57
  15  pya             e.g. asap7_finfet_lvs.py:85
   4  openpyxl        e.g. doc_extract.py:185
   3  systemrdl       3  pytesseract   3  PIL   2  anthropic
   1  jsonschema      _ppa/schema_validation.py:133   <- the only one, now
```

`jsonschema` is down to one site. **`yaml` at 45 sites is the same defect at
larger scale** and I did not touch it — see the lander section.

---

## REQUESTS TO THE LANDER

**1 — Assign the version.** I did not bump it, per the constraint.

**2 — `yaml` is R11 at fifteen times the scale (45 sites, undeclared).** It is
not in the standard library. Every one of those programs behaves on a bare
install the way `ppa_contract_check` did before this branch, and none of them has
a bundled fallback. `openpyxl`, `systemrdl`, `pytesseract`, `PIL`, `docx`, `xlrd`
and `pptx` are the same class in the document-ingest lane. The pattern this
branch establishes — one declaration, one import site, a bundled or refusing
fallback — transfers directly; a `yaml` lane is a separate piece of work and
wants its own brief.

**3 — Consider whether `PREFERRED` belongs in a file a human reads too.** I
deliberately did not add a `requirements.txt`: nothing in this repo reads one, and
a declaration nothing reads is the shape of the problem, not the fix. If the
plugin grows an install path that consumes a manifest, `PREFERRED` is the thing to
generate it from.

**4 — F-12's rule is worth generalising past this one sentence.** *A published
reason that names a checkable condition must check it.* Two instances were found
by this brief (`stub_feasibility`, `pnr_exclusion_reason`) and both were false on
the tree that shipped them. `unlanded_claims_contradicted_by_tree` currently
matches one phrasing, `<path>.py has not landed`, and only inside a search
manifest. A repo-wide census of "reason strings that assert something about
another file" would likely find more; I did not run one, and I would not want the
matcher widened without one — a pattern-based rule with no corpus behind it is
how a checker starts firing on quotations.

**5 — `--die-um` wants a normaliser in the runner**, even a trivial one that
parses `auto | WxH` and returns what it will use. Then the value round-trip in
`ppa_pnr_search_space` covers all three levers instead of two, and the silent
re-read defect it caught for `--util` cannot exist for geometry either.
