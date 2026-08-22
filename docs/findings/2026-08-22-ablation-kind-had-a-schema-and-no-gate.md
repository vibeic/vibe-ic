# The ablation document kind had a schema and no gate

Lane `next/ppa-ablation-kind-has-a-gate-that-runs`, cut from `origin/main`
(a4caccefe, v1.11.69). Not folded into any assembly: it is a change to
`tools/ci/repo_hygiene_gates.sh`, and the batchbig assembly measured against
this same main deliberately does not touch that file.

## The hole, measured rather than asserted

`schemas/ppa/ablation.v1.schema.json` exists because a within-project
comparison was filed as `vibeic.ppa.comparison.v2` — the kind whose entire
claim is a comparison against an opponent this project did **not** tune — and
`ppa_head_to_head_check` refused it `BASELINE_TUNED_BY_US`. The record was
honest; the document kind was the lie. Adding the kind was the right repair.

What shipped with it. `git grep -l 'vibeic\.ppa\.ablation\.v1' origin/main`
returns SIX files, and not one of them applies the schema to anything:

| file | what it is |
|---|---|
| `schemas/ppa/ablation.v1.schema.json` | the schema itself |
| `ppa-crosslayer/records/ablations/ablation_pnr_only_vs_crosslayer.json` | the one record |
| `…refusal_that_caused_it.json` | the refusal kept beside it as evidence |
| `ppa-gate-audit/RESULT.md` | the write-up that proposed the kind |
| `programs/tests/test_ablation_is_not_a_head_to_head.py` | one pytest, one hardcoded path |
| `tools/ci/repo_hygiene_gates.sh` | the word `ablation`, inside an exemption string |

Two more files mention the word without the kind, and both were checked rather
than assumed: `module_port_audit.py` uses it in a comment about an unrelated
measurement, and `ppa-crosslayer/tools/head_to_head.py` prints "WITHIN-PROJECT
ABLATION; file it as one" — a producer-side message, and nothing invokes that
tool (`git grep -ln head_to_head.py` over `*.sh` `*.py` `*.yml` returns nothing).

So a **second** ablation filed into `records/ablations/` tomorrow was validated
by nothing that runs. That is not a cosmetic gap. The three head-to-head rows in
the dispatcher refuse a comparison whose baseline this project tuned; this kind
is where such a document legitimately goes — and with no gate behind it, it is
also where an illegitimate one could go to escape those conditions. The schema
closes that from the other side (`tuned_by_this_project: const true` on every
arm), but **a schema nothing applies refuses nothing.**

## What landed

`programs/ppa_ablation_check.py` applies the schema to every document that
DECLARES the kind, anywhere under the corpus, through the same `_ppa_corpus`
seam the other record gates use. One dispatcher row, aimed at `ppa-crosslayer`,
where the kind lives.

It does **not** restate the schema's clauses in Python — two copies drift — and
it invents none. `isolates` is not in the schema's `required`, so a missing one
is a NOTE and not a finding: a gate that enforces more than the document it
cites turns a rule nobody agreed to into a load-bearing one. The one thing it
adds is a label: when the failing clause is `tuned_by_this_project`, the output
says so and names `comparison.v2`, because "some shape rule failed" and "a
head-to-head is hiding in this kind" are not the same sentence to a reader.

## The reds

Every property below was proven to go red without the code that holds it.

| # | mutation | verdict |
|---|---|---|
| 0 | the dispatcher row absent | CAUGHT — `assert []`, 17 passed |
| 1 | an empty corpus returns rc 0 | CAUGHT — 2 failed |
| 2 | the schema is never applied | CAUGHT — 4 failed |
| 3 | the refusal stops naming the clause | CAUGHT — 1 failed |
| 4 | two population sources accepted | CAUGHT — 1 failed |
| 5 | no mode returns rc 2 instead of rc 3 | CAUGHT — 1 failed |
| 6 | selection by a name hint, not the declaration | **NOT CAUGHT** — see below |
| 7 | an unreadable file is silently dropped | CAUGHT — 2 failed |
| 8 | the row reverted to strict `run` | CAUGHT — 1 failed |
| 9 | the exemption removed from the row | CAUGHT — 1 failed |

**Mutation 6 is the one worth reading.** Replacing the declared-schema test with
a substring test over the document's first bytes passed all eighteen tests. The
reason is the shape this repository keeps finding: every fixture put
`"schema": "vibeic.ppa.ablation.v1"` first, so a selector reading the WORD and
one reading the DECLARATION agreed on every one of them. The file was checking
the thing next to its claim. Two tests now separate them — a document NAMED for
the kind that declares another must not be selected, and one with no hint but
the declaration must be. Re-run with the same mutation: CAUGHT.

## Two defects the repository's own machinery found in this lane

Neither was found by reading the diff.

**1. The gate wrote its own declared report non-atomically.**
`atomic_artifact_write_check` tracks the SET, not just the count, and named it
the moment it was parsed: `[FAIL] 1 program(s) newly write a declared report
destination without _atomic_artefact: ppa_ablation_check.py:246`, rc 1. Both
writes now go through `_atomic_artefact.write_text`. Nothing was added to
`_atomic_artefact_residual.json`: the green is bought by converting, not by
widening the register, and `grep -c ppa_ablation_check` over that file is 0.

A note on how that red was nearly missed: the first reading of it was
`... | tail -3; echo rc=$?`, which printed 0 — the exit code of `tail`. The
gate's verdict is on stderr and is rc 1. A wrapper that borrows `$?` from a
pipeline answers a question nobody asked.

**2. The row was wired strict, and a bound landing would have failed on it.**
The gate passes today, so `run` looked right. Measured:

    $ GATEKEEPER_BENCHMARK_DATA_SHA=... VIBE_IC_BENCHMARK_DATA=<clone> \
        ppa_ablation_check --corpus <repo>/ppa-crosslayer
    note: GATEKEEPER_BENCHMARK_DATA_SHA binds the landing corpus; forcing
          VIBE_IC_BENCHMARK_DATA=<clone> and refusing any candidate-local
          .../ppa-crosslayer shadow.
    VACUOUS: ... 0 ablation record(s) selected ... rc=2

A landing that binds a corpus redirects this row away from the named root, by
design. An rc 2 there is a fact about the landing environment, not about any
record, and failing a landing for it is a gate answering a question nobody
asked. rc 2 now arrives as NOT CHECKED; rc 1 still fails.

**3. And then the exemption was left off, which certified nothing.**
The second wiring was `run_tolerating_uncheckable` with NO `uncheckable_until`,
reasoning that rc 2 is not expected here so an undeclared row stays louder in
the roll-up. `_gate_dispatch.sh` refuses that outright:

    gate_dispatch: WIRING ERROR — "PPA ablation records (within-project)" is
    wired with run_tolerating_uncheckable, so it can report NOT_CHECKED, but no
    `uncheckable_until <YYYY-MM-DD> <why>` line precedes it — tolerance has to
    be bought, not defaulted into
    ... the set was not correctly declared, so this run certifies NOTHING

Measured cost: a 71-file regression over every test that drives the hygiene
script went **2 failed on main → 11 failed on this lane**, and all NINE new reds
were that one missing line. With the exemption declared those nine files are
209 passed, 5 skipped, rc 0.

The routed-DEF row that prints "BLOCKING; no exemption" is not a
counter-example, and checking it is what corrected the reasoning: it uses the
structural-refusal wrapper, a different mode, whose rc 2 is the only truthful
outcome it has.

The exemption is evidence rather than a date. It states that the gate DECIDES
and PASSES over this repository today, names the measured way rc 2 is reachable,
and says a record that IS read and does not hold is rc 1 and still fails. The
test that pinned "no exemption" is REWRITTEN, not deleted, to pin the rule that
survived.

## What this lane does not claim

- It does not tighten the schema. `isolates` stays optional.
- It does not touch any published record, any baseline, any exemption date or
  `gate_red_since.json`.
- It does not bump the plugin version.
- It is not folded into `land/batchbig-assembled`: that branch is measured, and
  adding an unmeasured commit to a measured branch is the failure this night was
  about.

## The regression, base against head

71 test files — every file in `programs/tests/` that reads
`tools/ci/repo_hygiene_gates.sh` — on two checkouts of the same depth, base at
`origin/main` (a4caccefe) and head at this lane. The base list drops the one
head-only file, so 70 files are compared and the 71st is reported separately.

| | base (a4caccefe) | head (this lane) |
|---|---|---|
| failed | 2 | 2 |
| passed | 1411 | 1434 |
| skipped | 18 | 18 |
| errors | 0 | 0 |
| wall | 1348 s | 1177 s |

**NEW RED: none. FIXED: none.** The two failures are the same two ids on both
arms and are pre-existing on main:

    test_gate_red_since_rows.py::test_the_bound_is_what_refuses_and_not_some_other_clause
    test_v1_9_63_issue693_repo_process_family_wiring.py::test_the_checker_population_covers_checker_shaped_names

The +23 passed is accounted for exactly rather than waved at: 22 are this lane's
own test file, and the twenty-third is a parametrised case in
`test_rc2_over_a_nonempty_population_names_the_artefact.py`, which collects 35
on base and 36 on head — the new gate becomes one more subject of that rule, and
it passes it. Measured with `--collect-only` per file on both trees; every other
one of the 70 collects identically.

An earlier head arm reported 11 failed and 2 errors. Both are named rather than
buried: the 9 extra failures were the missing `uncheckable_until` described
above and are gone; the 2 errors were `checker_execution_wiring_audit.py` timing
out on a 30 s subprocess budget at load ~20, and the file is 8 passed twice in
isolation at load 17. Two earlier head arms were discarded outright because the
tree was edited under them — an arm measured against a tree that changed
mid-run is not a measurement.
