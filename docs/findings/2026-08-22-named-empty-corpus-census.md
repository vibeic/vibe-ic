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
- **The sweep was not purely read-only, and that is a property of the method
  rather than of the gates.** Driving `cross_layer_reference_check` left
  `reports/phase1/cross_layer_reference_check.json` in the scanned tree — it is
  a producer as well as a checker, which the dispatcher models with its own
  `WROTE_CORPUS` state, so this is expected behaviour and not a finding. It is
  recorded because a census that describes itself as "run each gate and read
  what it says" should say that running one of them changed a tree. Nothing
  tracked was modified, and the artefact was removed.

- **Not wired as anything.** Per the standing ruling on wide-population sweeps,
  this is a CENSUS that records debt. It is not a gate, it is not blocking, and
  it exists so the next person starts from a measured bound instead of a guess.

## When the defect activated, and what it does on the landing path

**Dated.** Files named exactly `CITATION_ROUTING.txt` in the publishing
repository:

| corpus state | count |
|---|---|
| `146d665`, before the withdrawal | **3** |
| `bcf2f94`, the withdrawal itself | **0** |
| `3b58ccd42`, the publisher's tip today | **0** |

The withdrawal of 2026-08-20 19:28 +0800 took all three. Before it, this gate
found its subject and never reached the refusal; since it, every run reaches the
refusal and is told the pointer is wrong. **The sentence has been false for two
days**, and only became reachable then.

**A CORRECTION MADE MID-MEASUREMENT.** A first count said the tip tracks **1**
`CITATION_ROUTING.txt` against the local checkout's 0, and I briefly concluded
the whole finding was an artifact of a stale clone. It was not: `grep -c
CITATION_ROUTING.txt` matches `protocol_parity/INPUT_DOC_CITATION_ROUTING.txt`
as a substring. Counted by exact basename, both are 0 and the finding stands.
A substring match on a filename is the same error class as the roll-up read
without its rows.

**What the landing does with it, and the limit of this claim.** Run exactly as
`repo_hygiene_gates.sh:707` invokes it — `--root "$ROOT"
--corpus-may-be-absent` — with the pointer bound the way
`gatekeeper_review._published_corpus_binding` binds it (defaulting to
`$HOME/_matrix_benchmark_data`), the gate returns **rc 2 on both trees**: `run`
is a blocking wrapper and maps rc 2 to FAIL. The rc is **unchanged by the
repair** — only the sentence differs — so whatever the landing does with it
today, it does the same after.

Whether that rc 2 is blocking a landing *right now* is NOT established here. A
landing succeeded at 2026-08-22 11:46 +0800, after the withdrawal, so something
about the real landing path differs from this invocation — the hygiene set is
sharded and has a subset rule, neither of which was exercised. Running the set
costs ~3750s and was not run. **The reachability is measured; the consequence is
not.**

## Incidental, and outside this census's subject

`$HOME/_matrix_benchmark_data` — the checkout
`benchmark_data_landing_checkout._checkout_arg` falls back to, and the one this
census was measured against — is **43 commits behind** the publisher's tip
(`bcf2f94` vs `3b58ccd42`). Every count in this record was re-taken at the tip
and none of them moved, so nothing here depends on it. Whether a stale fallback
checkout matters to a landing depends on the `GATEKEEPER_BENCHMARK_DATA_SHA`
pinning protocol, which this record did not trace. Noted so it is not
rediscovered as new.

## For whoever lands these: two branches, no required order, one half unverifiable alone

The work sits on two branches. **Neither breaks the other and no ordering is
required**, but one half of this one cannot be *exercised* until the sibling
lands, and that is worth knowing before a reviewer reads a collection error as a
defect.

| | `next/corpus-pointer-measured-empty` | `next/citation-routing-named-corpus-is-not-wrong` |
|---|---|---|
| subject | `tests/_published_corpus` fourth state; roll-up cell count | `citation_routing_is_true_check` sentence; module hermeticity; this census |
| protected paths touched | none | none |
| lands standalone | yes | yes |

Measured with the pointer bound at the real empty corpus:

| what | this branch alone | with the sibling applied |
|---|---|---|
| `test_named_empty_corpus_is_not_a_wrong_pointer.py` | **5 passed** | 5 passed |
| `test_citation_routing_is_true.py` | **1 collection error** | **17 passed, 1 skipped** |

The new test file is independent by construction — it drives the program in a
subprocess and never imports the corpus helper. The hermeticity edit is not: that
module imports `_published_corpus`, and until the sibling's fourth state exists,
a bound pointer at a zero-cell corpus kills its import.

**That is not a regression this branch introduces.** The same module, in the same
configuration, fails collection identically on `origin/main` — the sibling is
what repairs it. So this branch is safe to land in any order; only the
verification of its hermeticity half waits.

## Closing the "is it blocking?" thread: the machinery is correct, and it says UNKNOWN

The earlier section left this open — *"the reachability is measured; the
consequence is not"* — and named the full hygiene set (~3750s) as the only way
to close it. That was right, and here is why, so the next reader does not walk
the same path again.

**The subtraction rule is real and pinned.** `hygiene_finding_delta` asks *"which
findings exist on the candidate that are not on the base?"*, so a failure present
on both arms is inherited and does not block. Measured, not read:
`test_an_inherited_finding_does_not_block` plus the whole of
`test_inherited_red_deadline.py` — **15 passed** on clean `main`. The
citation-routing rc 2 is identical on `main` and on this branch, so it is
inherited by construction.

**Inherited is not the same as unowned, and the repo already knows it.**
`test_inherited_red_deadline.py` exists because `flow-gate enforcement audit`
stayed red across *"nine days, 704 commits and 96 version-bearing landings"* and
every landing was correct to allow it. The deadline — `max_commits` in
`tools/ci/gate_red_since.json`, adjudicated by `gate_red_since_check` — *"already
existed and nothing ever opened it, because a row is voluntary and pure cost so
no row is ever written"*. The forcing function now lives in
`landing_merge_verdict`, deliberately outside the hygiene suite, because *"a
refusal wired inside the suite would be a gate in the suite, red on both arms
from its first landing, and subtracted by this very rule"*.

`tools/ci/gate_red_since.json` carries exactly **one** row today —
`flow-gate enforcement audit`. There is no row for `citation routing is true`.

**So the open question is well-formed, and it is conditional.** *If* the
citation-routing gate is red on both arms in a real landing, then it is an
inherited blocking red with no acknowledgement row and no deadline. The `if` is
what cannot be settled here: `gate_red_since_check` requires `--record`, a real
hygiene summary, and `landing_merge_verdict` refuses to guess without one —

> the inherited-red deadline was NOT evaluated … whether a gate red on both arms
> is owned by a live deadline is **UNKNOWN** here

**That is the correct behaviour and this probe found no defect in it.** Silence
there would be *"indistinguishable from 'every inherited red is owned'"*, and the
program says so in those words rather than defaulting to the comfortable answer.

**The exact invocation that would resolve it**, for whoever is authorised to
spend the run: produce hygiene summary records for `origin/main` and for the
candidate with `VIBE_IC_BENCHMARK_DATA` bound as
`gatekeeper_review._published_corpus_binding` binds it, then
`gate_red_since_check --record <candidate summary> --ledger
tools/ci/gate_red_since.json --repo <repo>`. If `citation routing is true`
appears red on both, it needs a row — or, better, the repair on this branch plus
whatever makes its subject present again.

## Re-taken at `ae78abb28` (v1.11.70): the population MOVED, the verdict did not

`main` advanced 673 commits from `a4caccefe` while this record was being written.
A census is a claim about a denominator, so the denominator was re-counted rather
than assumed — and it had changed.

| like-for-like scope (`programs/*.py`, `tools/ci/*.py`) | n |
|---|---|
| corpus-resolving files at `a4caccefe` | 28 |
| corpus-resolving files at `ae78abb28` | **30** |
| removed | 0 |

The original 28 reproduces exactly at its own sha, so the number was right and is
now out of date — which is the whole reason it was re-taken. The two additions:

- `explicit_argument_outranks_the_environment_pointer.py`
- `content_pinned_authority_verified_only_at_merge.py`

**Neither carries the defect.** Checked both ways rather than by reading intent:
neither contains a pointer-blaming refusal (`grep` for *"wrong pointer"* / *"is a
broken configuration"* → 0 in both), and both were driven against the real empty
corpus — the first exits 0 stating its denominator (*"examined 6 in-scope
corpus-pointer reader(s)"*), the second exits 0. **30 of 30 counted, 20 driven,
still exactly one defective site.**

*A run of mine that was not a result: the second program first reported
`ModuleNotFoundError: No module named '_atomic_artefact'` because I had copied it
to `/tmp`, which breaks its sibling imports. That is a measurement of my
invocation, not of the program. Re-run in place, with `--root`, it exits 0.*

### The new gate does not supersede this branch, and it says why itself

`explicit_argument_outranks_the_environment_pointer` is aimed at the same seam,
so the question is live. It enforces one thing: *"a site that reads the corpus
pointer and can redirect its subject with it MUST say so on its output."*
`citation_routing_is_true_check` already announced (`note: … adds a corpus to
scan`) before this branch and still does; what this branch repairs is the
**content of the refusal**, which that rule does not reach.

It also declines, explicitly, to arbitrate a **live contract split** it
documents: `_corpus_location` holds that *"the pointer replaces a missing corpus;
it does not replace a present one"*, while three consumers deliberately hold the
opposite (*"THE POINTER WINS OVER THE PATH, ANNOUNCED (#1710)"*). That split is
useful context for this branch's hermeticity change — which takes neither side,
and instead says that a unit test naming its own `--root` is not the place the
question gets decided.

### Neither branch introduces an instance under either new gate

Run against clean `main` and both branches:

| gate | `main` | `next/corpus-pointer-measured-empty` | this branch |
|---|---|---|---|
| `explicit_argument_outranks_the_environment_pointer` | **PASS**, 6 in-scope readers, 2 disclosed | **PASS**, identical | **PASS**, identical |
| `content_pinned_authority_verified_only_at_merge` | rc 0 | rc 0 | rc 0 |

The second gate's WARN count is 12 on `main` and 11 on both branches — lower,
because the branches sit on the older base where one fewer authority file
differs. Nothing is introduced by either branch under either rule.

## Incidental, measured, and deliberately NOT filed as a defect

`programs/hygiene_gate_profile.json` is a committed record of a past sweep. Its
own header says `declared: 74`; a live `repo_hygiene_gates.sh --list` at
`a4caccefe` declares **93**. Compared label by label:

| | n |
|---|---|
| gates declared live but absent from the profile | **25** |
| gates in the profile but no longer declared | **6** |

**Why this is not filed as a defect, checked rather than assumed.** Both readers
consume the profile for SHARD TIMING, not as a claim about how many gates exist:
`gate_host_independence_check` passes it to `plan(driveable, profile, jobs)`, and
`repo_hygiene_parallel` establishes its denominator by running
`--list --summary-json` LIVE and refuses if that fails — *"could not establish the
hygiene denominator"*. So the stale `74` is never believed by anything; a gate
with no profile entry simply contributes no timing hint.

The consequence is therefore shard balance, not correctness: 25 of 93 gates are
planned without a measured duration, and 6 rows describe gates that no longer
exist. That is worth someone re-rendering the profile, and it is worth nobody
treating it as a false verdict.

It is recorded because a committed record whose headline figure is 19 short of
the truth is the shape this repository keeps repairing, and the next reader who
greps `declared` will find `74` — as I did, mid-measurement, and had to go and
check what consumed it before I could say whether it mattered.
