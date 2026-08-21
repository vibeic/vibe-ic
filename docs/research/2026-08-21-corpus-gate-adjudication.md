# Adjudication: the two corpus gates

Owner ruling, 2026-08-21: *"adjudicate them, do not renew. A deadline that gets
extended each time it arrives is not a deadline, it is a comment. For each of
the two, write the verdict down: either it is a real finding about the design
and it stays red until fixed, or its population is genuinely empty and it must
report rc=2 NOT CHECKED with the measured population count in the message.
Renewal is not one of the options."*

Both verdicts are **real finding, stays red until fixed**. Neither row is
renewed; both remain expired and both therefore refuse a landing.

## FIRST, THE OPTION THAT DID NOT APPLY — AND IT IS ALREADY BUILT

The ruling's second branch is already implemented in both gates, and correctly.
Driven with an empty population:

```
$ l_doc_field_producer_check.py --corpus <empty dir> --corpus-may-be-absent
UNDETERMINED: … holds no L-doc this gate can read (0 of them carry a `fields`
object), so 0 document(s) were scanned against 18 field(s) read by checkers.
A zero denominator cannot say whether a field has a producer …
rc=2

$ evidence_citation_resolves_check.py --corpus <empty dir> --corpus-may-be-absent
UNDETERMINED: … this gate enumerated 0 file(s) it can read there (no .md, no
.json), so 0 citation(s) were checked. Nothing enumerated is 'I found nothing
to read' …
rc=2
```

rc 2, with the measured population count in the message, in both. So the
question is only whether the populations are empty here. **They are not**, and
that is measured, so the first branch is the one that applies.

## VERDICT 1 — `L-doc field producer`: REAL FINDING

Population, measured: **48 L-docs** under the published corpus, **18 fields**
read by checkers. Not empty by any margin.

Three fields are read and never produced:

| field | readers | present in | populated in |
|---|---:|---:|---:|
| `floorplan_hints` | 1 | 4 docs | **0** |
| `power_budget_uw` | 1 | 4 docs | **0** |
| `sdc_constraints_path` | 1 | 4 docs | **0** |

The single reader of all three is **`l19_pdk_floorplan_contract_check`**. The
consumer sees an empty value and an empty value is indistinguishable from a
clean one — the vacuous-pass shape this repo removes from gates one at a time.
It is a finding about the design, not about the corpus being absent: the
documents exist, they carry the key, and nothing ever fills it.

**It reaches further than its own gate.** `power_budget_uw` is also read by
`area_total_vs_budget_check` and `power_total_vs_budget_check` — and
`area_total_vs_budget_check` is one of the two AUDIT_ONLY programs that redden
`flow-gate enforcement audit`. So the chain is: a field with no producer feeds a
budget check that declares no intent, and nothing blocks at either end. Two of
the eight rows are the same defect seen from two directions.

The fix is either the L-docs populate the three fields or
`l19_pdk_floorplan_contract_check` declares them optional and says so. Both are
decisions about the contract; neither is a grace period. **Stays red.**

## VERDICT 2 — `evidence citation resolves`: REAL FINDING, AND ONE QUARTER OF IT WAS THE GATE'S OWN DEFECT

Population, measured: **149 contributing documents** of 1037 files enumerated,
**105 citations** checked. Not empty.

Two findings, adjudicated separately.

**(a) 113 baseline entries now RESOLVE.** Real. The debt was paid and the
baseline was not shrunk, so it has become a standing waiver for citations that
are no longer broken. Mechanical to clear and it must be cleared.

**(b) 4 NEW dangling citations — of which 3 are real and 1 was ours.** Checked
one at a time:

| citation | verdict |
|---|---|
| `END_TO_END_CAMPAIGN.md::benchmark-data/evaluation/cvdp/CVDP_CAMPAIGN_FOLLOWUP.md` | real — absent everywhere |
| `METHODOLOGY.md::sha256/BENCHMARK_VERIFICATION_REPORT.md` | real — absent everywhere |
| `METHODOLOGY.md::sha256/RESULT.md` | real — absent everywhere |
| `OSS_EDA_FORK_ROADMAP.md::tools/vibeic-eda/FIX_STATUS.md` | **NOT dangling** — this repo ships that file |

The fourth was the gate reporting its own scope as the document's defect, which
is the failure #1044 is about and precisely what the gate's `outside` class
exists to prevent. `_resolves_outside_the_scan_root` walked up from the scan
root, and its comment read *"benchmark-data/ic -> benchmark-data -> repo root"*
— true while the published cells lived inside this repository. **`c5d7f2d00`
made the corpus a sibling of the repo rather than a child**, so the walk now
arrives at `$HOME` and `/`. The disclosed OUT OF SCOPE count had fallen from the
7 measured when that comment was written to 2, which was the visible half of
the same loss.

Fixed here: the repository is located from where the PROGRAM ships rather than
inferred from where the corpus sits. OUT OF SCOPE 2 → 3, dangling 4 → 3. The
gate is **still red** on the three real ones and on (a). **Stays red.**

Note that the same commit that reddened both gates is the one that broke the
scope predicate. That is not a coincidence to explain away — it is the shape of
a corpus relocation whose consumers were not all moved with it.

## A THIRD THING, FOUND WHILE ADJUDICATING, WHICH MATTERS MORE THAN EITHER

**The acknowledgement ledger bought a green.**

`tools/ci/gate_red_since.json` gained its first rows yesterday. One of them
reads, in its `why`:

> closed_loop_edge_check, ppa_pr_scope_check and slot_pad_budget_check are
> consulted by no automatic verdict, so the tree looks identical whether they
> would pass or fail.

`gate_is_wired_check` enumerates its wiring sources with `tools/ci/*`. It read
that sentence, found all three names, and counted them **wired**. `unwired` fell
61 → 58 and the gate turned **PASS**. Isolated to that one file, on an otherwise
clean tree at `6dfe15a32`:

```
clean 6dfe15a32                          unwired: 61   [FAIL]
clean 6dfe15a32 + gate_red_since.json    unwired: 58   [PASS]
clean 6dfe15a32 + RESULT_ROWS.md         unwired: 61   [FAIL]
```

The ledger's own `_doc` promises *"there is nothing a row can silence and no
green a row can buy"*. It was exactly wrong, and in the worst possible
direction: **the acknowledgement silenced the finding it acknowledged**, so the
more honestly a row described its red, the more certainly it hid it. Had this
shipped, writing the eight rows would have closed one of the eight reds by
describing it.

The gate already holds this rule one level in — `executable_text` strips
comments and docstrings because "a comment naming a gate is not a caller", with
a measured case where believing one would have hidden a gate that runs nowhere.
A register of red gates is the same thing. `_NOT_A_RUNNER` now excludes the
ledger, named from `gate_red_since_check.LEDGER_REL` so a move cannot leave the
exclusion pointing at nothing, and `test_ledger_is_not_a_runner.py` pins both
directions — the ledger is not read, and everything else under `tools/ci/` still
is, because for several gates that directory holds the only caller there is.

## ONE MEASUREMENT THAT CHANGES WHAT A ROW MEANS

The red set depends on whether the published corpus is bound:

```
corpus UNBOUND   85 declared,  8 FAIL, 10 NOT_CHECKED
corpus BOUND     88 declared,  9 FAIL, 12 NOT_CHECKED
```

Binding it adds four per-cell gates and removes one empty-corpus gate. A row is
therefore true against a stated corpus state, not absolutely — and a host that
binds the corpus will see a ninth red (`an argued direction is pinned`) that has
no row. That is not an argument for a ninth row written blind; it is an argument
for the landing path to state which corpus it measured against, which the
hygiene record already does.

---

# ADDENDUM — the third corpus gate, `published-evidence index honest`

Adjudicated 2026-08-22, on the same terms as the two above. It was the one red I
reported as "not mine and it has no row", and leaving it named-but-unmeasured
was not an answer.

## VERDICT: A REAL FINDING, AND NO ROW IS POSSIBLE FOR IT

**Real.** With the corpus bound, the committed index disagrees with the index
regenerated from the walked corpus: rows for `sha256/`, `ibex/`, `subservient/`,
`caravel_user_project/` and `opentitan_aes/` cells are listed as `UNSTATED …
record only`, and regeneration produces *"None — the corpus was walked and no
published cell falls into this classification."* The cells are all still present;
what changed is their measured state. That is a published index claiming a
classification the evidence no longer supports, which is the same "reads as true
and is not" class the rest of this document is about.

**And no row is possible.** Not because it is unimportant — because `since` is
undefined for it:

* the file that must change is `ic/INDEX.md`, and it lives **only** in
  `vibeic/benchmark-data`, which is its own git repository (`146d665`). This
  repo tracks a different `INDEX.md` (`programs/INDEX.md`);
* so no commit in **this** repo made it red, and
  `gate_red_since.git_age(since)` is `git rev-list --count <sha>..HEAD` **in
  this repo**. There is no commit here to name.

That is the same argument that fixed the grace at 0 for an unacknowledged red:
the clock is commits in this repository, and where there is no first-red commit
here, only 0 and infinity are computable. Writing a row with a plausible-looking
`since` would be inventing the number that sets the deadline — the one thing the
whole mechanism exists to prevent.

## WHAT WAS FIXED HERE, BECAUSE IT WAS ACTIONABLE

The gate printed `Fix: re-run with --write and commit the result.` That
sentence was written when the index lived in this repository. It now can live in
the corpus clone — the code that formats the path twelve lines above already
knows this and prints an absolute path for exactly that case — while the gate
itself is run from vibe-ic. A reader who follows the remedy commits in the wrong
repository, finds nothing to commit, and is left with a red gate over a correct
tree.

It now names the repository:

    Fix: re-run with --write, then commit /…/benchmark-data/ic/INDEX.md in the
    corpus clone that owns it — NOT this repository, which does not track that
    file.

A printed remedy is executed, not read; naming the wrong place and failing to
run are the same defect to whoever tries it. Pinned by
`test_evidence_index_remedy_names_its_repo.py`, including that it does not name
the path twice — which the first version of this fix did.

## ONE THING FOR THE OWNER, MEASURED AND NOT ACTED ON

> **SHARPENED 2026-08-22 — I described the symptom, and the cause is one level
> down.** I wrote below that the three gates "do not agree about what an absent
> corpus means". They do not disagree about that. They disagree about **where
> the corpus is**, and the rc difference follows from it.
>
> vibe-ic#1710 introduced ONE seam for that question, `_corpus_location.resolve`,
> which follows `$VIBE_IC_BENCHMARK_DATA` only when the named path carries no
> corpus and announces either way. Two of the three adopted it:
>
> ```
> l_doc_field_producer_check         imports _corpus_location
> evidence_citation_resolves_check   imports _corpus_location
> benchmark_evidence_index           does NOT — its own CORPUS_ENV and
>                                    IC_SUBDIR = "benchmark-data/ic"
> ```
>
> So with the environment UNSET, on this host:
>
> ```
> l_doc_field_producer_check         -> /home/reyerchu/benchmark-data/ic
> evidence_citation_resolves_check   -> /home/reyerchu/benchmark-data/ic
> benchmark_evidence_index           -> NO_CORPUS
> ```
>
> Two gates read a corpus that is sitting right there and the third declares
> there is none — because the third only ever looks INSIDE the repo
> (`<repo>/benchmark-data/ic`) plus the env var, which is exactly the assumption
> `c5d7f2d00` invalidated when the cells moved out. Its `rc=0` is not a lax
> reading of "absent"; it is a correct reading of a question asked in the wrong
> place, and its own docstring records `NO_CORPUS (rc=0)` as intended, decided
> in isolation from the seam its siblings adopted.
>
> **The fix is therefore not the rc.** It is routing this gate through
> `_corpus_location` like the other two, after which it finds the corpus and
> returns the real verdict — which is FAIL, as the bound measurement below
> already shows. That has the same blast radius as the rc change and is the
> owner's for the same reason, but it is a different change with a different
> justification, and picking the rc would have treated the symptom.

## WITHDRAWN TWICE, AND THE THIRD MEASUREMENT INVERTS THE FINDING

I published two things here that were artefacts of how I drove the instrument,
and the correction is worth more than either.

**First** I printed a table of exit codes and said the three
`--corpus-may-be-absent` gates "disagree about what an absent corpus means".
That table compared different outcomes of `_corpus_location`'s four-way contract
(env-set-and-unreadable is rc 2; nothing-anywhere-with-opt-in is rc 0), because I
drove the siblings with `--corpus <empty dir>` and the third with no pointer at
all. Rebuilt to be even-handed it inverted. **Withdrawn.**

**Then** I said the surviving finding was that `benchmark_evidence_index` never
adopted the shared seam, and that the fix was one import. Measured with one
variable — env unset, no arguments — the three did differ:

    l_doc_field_producer_check         -> /home/reyerchu/benchmark-data/ic
    evidence_citation_resolves_check   -> /home/reyerchu/benchmark-data/ic
    benchmark_evidence_index           -> NO_CORPUS

**That was still my host.** Run from a checkout with no `benchmark-data` above
it, ALL THREE report NO_CORPUS:

    checkout under /home/reyerchu (…/benchmark-data is a sibling)   l_doc rc 1  evidence rc 1  index rc 0
    checkout under /tmp/… (nothing above it)                        l_doc rc 0  evidence rc 0  index rc 0

The difference was never a disagreement about the seam. `_corpus_location.resolve`
does not walk parents at all. The CALLERS do:

    named = next((b / "benchmark-data/ic" for b in here.parents
                  if (b / "benchmark-data/ic").is_dir()), …)

`here` is the PROGRAM file, so that walk climbs out of the repository and into
`$HOME`. Eight programs do it, including both siblings.
`benchmark_evidence_index` is anchored on `repo_root / IC_SUBDIR` and does not —
which makes it the **host-independent** one of the three, and my proposed "fix"
would have spread the defect rather than cured it. It is not made.

## AND THIS CORRECTS TWO OF MY OWN EIGHT ROWS

`L-doc field producer` and `evidence citation resolves` are **rc 1 FAIL** on a
checkout that has a corpus above it and **rc 0 PASS** on one that does not. Both
measured, same commit, same tree.

So their red is **host-determined, not commit-determined**, and `c5d7f2d00` is
where that happened: before it the corpus was INSIDE the repo, so these gates
were a function of the commit; moving it out made them a function of the commit
AND of what sits above the checkout. Nothing noticed — including me, when I gave
them rows with a bisected `since` as though the repo had gone red.

The bisection was not wrong; it was measured in worktrees that all sat under
`/home/reyerchu`, so it correctly dates the red **for a host that can reach a
corpus**. What it does not do is what the other six rows do, which is date a
property of this repository's history.

Both rows are therefore annotated rather than deleted: they state a CONDITION,
not a deadline, and they must not be read as blocking a corpus-less landing host.
That is the same standard that denied `published-evidence index honest` a row —
if a gate's truth depends on an external repository's state, a clock counting
commits here cannot describe it. Applying that standard to a finding of my own
that had already shipped is the only way it means anything.

**Not changed here, deliberately.** Returning rc 2 would make it NOT_CHECKED on
every unbound host, and it is dispatched with a plain blocking `run`, under which
rc 2 is a FAIL — so flipping it reddens main for everyone until it is either
re-dispatched as `run_tolerating_uncheckable` with a dated `uncheckable_until`,
or the corpus is bound on the landing path. That is a wiring decision with a
blast radius, and it is the owner's, in the same way the deadline's was. The
measurement is here so it can be made with the number in front of you.
