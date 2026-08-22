# CENSUS: how many gates call a correct pointer at an empty corpus "wrong"?

I found the third instance of this defect **by accident** — a test failed while I
was measuring something else. That is not a population, it is an anecdote, so
this bounds it: every program in the repository that resolves the published
corpus, run against the real one, and read.

Measured 2026-08-22 on a clean `origin/main` @ `a4caccefe`, pointer bound at the
cron-owned landing checkout `~/_matrix_benchmark_data` — a real clone of
`vibeic/benchmark-data` at `bcf2f94 "withdraw all four published cells"`, which
carries `PUBLISHING.md`, 9 designs under `ic/`, and **0** published cells.

## The defect being counted

Not "refuses over an empty corpus" — that is correct and required. The defect is
**a refusal that blames the reader's configuration for a configuration that is
correct**: the pointer is right, the clone succeeded, and the corpus genuinely
carries none of that gate's subject. `tools/ci/routed_def_corpus.py` was repaired
for it by #1764; `programs/tests/_published_corpus.py` on the sibling branch.

## Method, and the two confounds it hit first

28 files reference `VIBE_IC_BENCHMARK_DATA` or `_corpus_location`. Of those, 11
are gates that could be driven end-to-end and read.

**Confound 1 — `rc 2` is also argparse's usage-error code.** The first sweep ran
every candidate as `<prog> --root <repo>` and reported a tidy column of `rc=2`.
Six of those were `error: unrecognized arguments: --root`. The census was
measuring argument parsing and would have read as a repository-wide finding. The
sweep now tries each program's actual interface and records which invocation
produced the verdict.

**Confound 2 — a subcommand interface looked like a probed program.**
`l4_systemrdl_export` takes `export|gap-tab|audit-corpus|…`, so the positional
form returned `invalid choice` — another argparse 2. It had not been probed at
all. Re-run as `audit-corpus --root`, the invocation `repo_hygiene_gates.sh`
itself uses.

## Result

| gate | verdict over the real empty corpus | honest? |
|---|---|---|
| `citation_routing_is_true_check` | `UNDETERMINED … is a wrong pointer` | **NO — the defect** |
| `tracked_symlink_portability_check` | rc 0 `[PASS]`, after `0 tracked symlink(s) under <corpus>` | yes — denominator stated |
| `tracked_symlink_target_present_check` | rc 0 `[PASS] … over 6928 tracked path(s) carrying 0 symlink(s)` | yes — real denominator |
| `l4_systemrdl_export audit-corpus` | rc 0 `[PASS] every register/field key …` | yes — see below |
| `published_record_staleness_check` | `VACUOUS_PASS: … 1276 JSON file(s) enumerated … Nothing was compared` | yes — names itself vacuous |
| `step_internal_fail_bubble_up_check` | `PASS: 1 report(s) examined` | yes |
| `cross_layer_reference_check` | `[SKIP] no phase1/generated_docs` | yes |
| `benchmark_evidence_index` | `NO_CORPUS` | yes |
| `benchmark_evidence_structure_check` | rc 1 over the repo root | yes (its own subject) |
| `evidence_citation_resolves_check` | rc 1 over the repo root | yes (its own subject) |
| `l_doc_field_producer_check` | rc 1 over the repo root | yes (its own subject) |

**Exactly one** site, and it is the one already repaired on this branch.

### A false finding I nearly filed, and why it was false

`l4_systemrdl_export audit-corpus` exits **0** printing *"every register/field key
in the published corpus has a recorded disposition"* over a corpus with zero
published cells. That reads like the `9/9 conformant` shape — a PASS sentence
about the corpus with no population beside it — and I began writing it up as a
fourth site.

It is not. The full output states its denominator two lines above the verdict:

```
  root /home/reyerchu/_matrix_benchmark_data: 174 on disk, 174 published
  L4 documents scanned : 174 of 174 published (0 unreadable)
  register keys seen   : 37
  field keys seen      : 14
  disposition rows     : 60
```

The corpus has no *cells*; it still carries **174** L4 documents. The PASS is a
real measurement over a real population. I reacted to the last line of the output
instead of reading the output — which is the same mistake as reading a roll-up
and not the rows, one seat over.

## Second pass: the gap this census named about itself, closed

The first version stopped at 11 of 28 and said so. The seven it skipped as
"not uniformly invocable" included the six PPA gates, which do take `--corpus
DIR` and are exactly the shape that could carry the defect. Driven:

| gate | verdict over the real empty corpus |
|---|---|
| `ppa_contract_check --corpus` | rc **2** — `5322 JSON file(s) opened … 0 published candidate(s)` |
| `ppa_feasibility_check --corpus` | rc **2** — same denominator |
| `ppa_head_to_head_check --corpus` | rc **2** — `0 head-to-head record(s) found in 5322 JSON document(s) scanned` |
| `ppa_pareto_check --corpus` | rc **2** — same denominator |
| `ppa_measurement_check --corpus` | rc **2** — same denominator |
| `ppa_problem_integrity_check --corpus` | rc **2** — same denominator |
| `matrix_mutation_ledger --census` | rc 0 — `replay mode: witness (25 pair(s) re-executed per run)` |

Every one opened the corpus, counted what it found, and **refused** — the
population is in the sentence, and none of them blames the pointer. This is the
doctrine working, and it is worth recording as the positive control the rest of
the census is read against: a repository where the correct shape is common is a
repository where the one exception is a defect rather than a convention.

Two of them also answer the confound that tripped this sweep twice:
`ppa_measurement_check` and `ppa_problem_integrity_check` return **rc 3** for a
bad invocation and say so in the message — `rc=3 (bad invocation, NOT …)` — so a
usage error can never be read as a verdict. That is the property whose absence
made the first sweep report argparse errors as findings.

**18 of 28 driven end-to-end. Still exactly one defective site.**

## What this census does NOT establish

- **It is not a proof of absence.** 18 of 28 were driven end-to-end. The
  remaining 10 are: five protected landing-infrastructure programs
  (`benchmark_data_landing_checkout`, `hermetic_candidate_runner`,
  `hermetic_landing_arm_receipt`, `protected_landing_transition`,
  `routed_def_corpus` — the last already repaired by #1764), two test modules,
  two shared modules with no standalone entry point (`_corpus_location`,
  `_ppa_corpus`), and `gatekeeper_review`, which drives the whole hygiene set and
  is not runnable at this hour. A site among those would not appear here.
- **One corpus, one shape.** Every row is the population of *this* corpus today.
  A gate whose subject is absent for a different reason could answer differently.
- **Not wired as anything.** Per the standing ruling on wide-population sweeps,
  this is a CENSUS that records debt. It is not a gate, it is not blocking, and
  it exists so the next person starts from a measured bound instead of a guess.
