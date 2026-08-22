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
the fixture its implementation invites. **Ten fail-open defects and one
over-tight granularity error**, every one returning rc=0 with the defect
present, every one in a gate written to catch that very class of defect:

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

**None was findable by re-running verification**, because in every case the bug
WAS the pass, and verification looks for confirmation.

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
* Sweeps over this repository: ten rc=0, one rc=2, one rc=1.
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
