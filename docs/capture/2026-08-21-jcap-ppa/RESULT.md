# The PPA cluster, DISTILLED — 47 records, and the twenty-one already-program claims of which twenty hold

The twenty-odd lanes that converged on the measurement layer all captured. None
distilled. This lane turns that cluster into records the next blind run can be
gated by, and it is honest about the largest single finding: **eleven of the
eighteen end-to-end findings are already enforced by a shipped program or a
general census test, and were fixed between the run that found them and this
tree.** Add the smaller `jsonschema` item, which is not one of the eighteen, and
four more classes drawn from the six lane records, and the count is
**11 + 1 + 6 = 18** claims examined — of which **seventeen hold and one, F-2, is
disproven by execution**: its guard's predicate is satisfied by a production
fallback and cannot fail. Those sixteen produced no record; duplicating them would be
worse than skipping them.

Two of the eighteen were marked *conditional* rather than clean, and one of those
two, F-2, was later disproven outright. The brief's test
for a landed fix — can the class recur in a module nobody has touched? — is
really a question about whether the guard's population is DISCOVERED or
DECLARED, and theirs is declared. Both are flagged in the table and folded into
**A-3**.

Tree distilled against: `origin/main` @ `a00f53f20`, plugin **v1.11.66**; then
merged up to `a4caccefe`, plugin **v1.11.69** (main moved twice under this branch: 30 commits, then 214). What that re-pin does and does not
claim, precisely: the live gate figures, both quoted pytest figures and every
record/table tally WERE re-run on the merged tree, and one of each was wrong
(619 gates, `18 passed`, two `26`s), as were the near-duplicate figures. The
**corpus-sweep figures — both in the table below and inside the record
narratives — are dated to the base** and were not re-derived, because each needs the
exact screen that produced it and a guessed screen returns a confident wrong
number — which is the failure `A-27` records. The drift is bounded instead: of
1238 plugin `.py` files, main changed **12** (six new programs, six tests) and
none is in the PPA layer, so no swept population moved by more than six. Main moved 30 commits under this branch while it was open,
and one of them (`506ff68c1`) landed this bundle's own earlier snapshot at the
canonical path — so this branch UPDATES that bundle rather than adding a second
copy, and the fourteen records it carried are a subset of those here.
Sources: `ppa-e2e/FINDINGS.md` (F-1..F-18), `ppa-e2e/RESULT.md` (13 requests),
`ppa-crosslayer/RESULT.md` (10 requests), and six lane records in
`/tmp/capture_lanes/`.

    python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py \
        --records docs/capture/2026-08-21-jcap-ppa/recoveries.json --out-dir docs/capture/2026-08-21-jcap-ppa/candidates

Accepted with no refusal and no unrouted record.

## Contents

- [Count per bucket](#count-per-bucket)
- [The rule for each of the eighteen](#the-rule-for-each-of-the-eighteen)
- [The eighteen, and what is true on this tree](#the-eighteen-and-what-is-true-on-this-tree)
- [The three the brief named — they are one shape, and the shape is already a program](#the-three-the-brief-named--they-are-one-shape-and-the-shape-is-already-a-program)
- [The 47 records](#the-47-records)
- [One change outside the capture bundle](#one-change-outside-the-capture-bundle)
- [Where each record came from](#where-each-record-came-from)
- [The one thing I could not settle — now settled, and it did not go where I expected](#the-one-thing-i-could-not-settle--now-settled-and-it-did-not-go-where-i-expected)
- [What remains open](#what-remains-open)
- [The "could not settle" seam, read out and closed](#the-could-not-settle-seam-read-out-and-closed)
- [Input coverage — every named source now read](#input-coverage--every-named-source-now-read)
- [Landing readiness — measured base against head, not asserted](#landing-readiness--measured-base-against-head-not-asserted)
- [Buildability — the deliverable's stated purpose, checked](#buildability--the-deliverables-stated-purpose-checked)
- [No near-duplicates — and the first number I published from a broken instrument](#no-near-duplicates--and-the-first-number-i-published-from-a-broken-instrument)
- [The ALREADY-PROGRAM claims — can the guards they name actually fail?](#the-already-program-claims--can-the-guards-they-name-actually-fail)
- [The brief's own requirements, audited against the finished records](#the-briefs-own-requirements-audited-against-the-finished-records)
- [The same question, asked of the records, and where the tooling stops](#the-same-question-asked-of-the-records-and-where-the-tooling-stops)
- [Three check NAMES promised more than their predicates deliver](#three-check-names-promised-more-than-their-predicates-deliver)
- [The verifier audited as an artefact, not used as one](#the-verifier-audited-as-an-artefact-not-used-as-one)
- [Does any commit describe a change it does not carry?](#does-any-commit-describe-a-change-it-does-not-carry)
- [How often the instrument was the problem](#how-often-the-instrument-was-the-problem)
- [Every blockage in this report, measured](#every-blockage-in-this-report-measured)
- [The ten requests in the cross-layer source, mapped](#the-ten-requests-in-the-cross-layer-source-mapped)
- [How much to trust each figure in this report](#how-much-to-trust-each-figure-in-this-report)
- [Re-measuring the older sweeps, and what it cost to try](#re-measuring-the-older-sweeps-and-what-it-cost-to-try)
- [The one claim class that keyword screens cannot audit](#the-one-claim-class-that-keyword-screens-cannot-audit)
- [A record closed on main while this branch was open](#a-record-closed-on-main-while-this-branch-was-open)
- [Re-checked against main's 214 commits](#re-checked-against-mains-214-commits)
- [The honest sentences, checked verbatim against the records](#the-honest-sentences-checked-verbatim-against-the-records)
- [Traceability — a sketch must lead back to its narrative](#traceability--a-sketch-must-lead-back-to-its-narrative)
- [The verification is a command, not a paragraph](#the-verification-is-a-command-not-a-paragraph)
- [A dangling reference the whole verifier walked past](#a-dangling-reference-the-whole-verifier-walked-past)
- [Emission is reproducible, and the one thing that moves is the one that should](#emission-is-reproducible-and-the-one-thing-that-moves-is-the-one-that-should)
- [Three checks the verifier was missing, two of which could not have failed](#three-checks-the-verifier-was-missing-two-of-which-could-not-have-failed)
- [Was every commit green? Replayed, and the answer is one](#was-every-commit-green-replayed-and-the-answer-is-one)
- [This bundle moved, and it was the merge that said so](#this-bundle-moved-and-it-was-the-merge-that-said-so)
- [A shipped record's evidence was a source screen, and it was wrong](#a-shipped-records-evidence-was-a-source-screen-and-it-was-wrong)
- [Where two of these rules fire NEXT, now that this layer closed them](#where-two-of-these-rules-fire-next-now-that-this-layer-closed-them)
- [Four classes checked this pass and deliberately NOT recorded](#four-classes-checked-this-pass-and-deliberately-not-recorded)
- [The records quote numbers and mostly do not quote the command](#the-records-quote-numbers-and-mostly-do-not-quote-the-command)
- [Six refusals, one principle: two absences compare EQUAL](#six-refusals-one-principle-two-absences-compare-equal)
- [Summary](#summary)
- [Next](#next)

## Count per bucket

| bucket | n | |
|---|---:|---|
| **T** | 1 | forked place-and-route tool faults after its own route completes |
| **A** | 44 | deterministic rules — the default, and every one names its predicate |
| **B** | **0** | see below: no candidate survived the "name the undecidable decision" test |
| **C** | 2 | one where the plumbing is the work; one DEMOTED FROM A by its own sweep |
| **D** | **0** | see below: nothing met the honest-discard bar |

**Why zero Bucket B.** Every candidate that first read as "needs judgment"
reduced, when the exact input was named, to a set difference over two tables
that already exist in the tree, a regex over a path, or a distinct-value count
over a manifest. Bucket B is where a rule goes when a program cannot decide it
from the input it would see; none of these is that.

**Why zero Bucket D.** The one candidate that looked non-generalizable — a
post-layout equivalence run that returns a tool error — is not discardable: a
fresh user hits it on the first routed design. It is not in this record set
because I could not establish from the evidence whether the fault is the forked
tool's or the invocation's, and a Bucket-T record needs that answer. Stated as
an open item at the end rather than filed as a discard.

---

## The rule for each of the eighteen

The brief asks first for the RULE that would have caught each finding — including
the ones already fixed, because *"the class can recur in a module nobody has
touched yet"* and a rule is what lets someone recognise it there. Status is the
next section; this one is the rules, one line each, stated so they name a class
rather than a symptom.

| F | the rule that would have caught it | where it stands |
|---|---|---|
| 1 | A deferral must name a resolvable owner: a document that excludes items because another producer owns them may not name a producer that does not exist. | program |
| 2 | An option that names a plug-in point must drive every plug-in that exists, or state per plug-in why it cannot — one blanket refusal for five different situations answers none of them. | program (census over a literal, **A-3**) |
| 3 | Every measurement name a gate proves from must be emitted by some producer, or the axis is unanswerable and the gate is decorative. | **A-1** — 1 of 9 still unprovable |
| 4 | A producer's envelope must be one the declared consumer reads; the check belongs to the pair, never to either side. | program (one direction, **A-3**) |
| 5 | A metric's declared unit must equal the unit its own name requires — two files of one lane may not hold opposite rules. | program |
| 6 | An artefact a consumer stages from a stamp must carry the stamp, and the emitters that write it must be enumerable so none is missed. | program |
| 7 | A generated document may claim only what its session's own inputs support; and an axis identical across arms that differ was not measured downstream of the lever. | **A-8**, **C-1** |
| 8 | Every key a comparison requires of an axis must be emitted by that axis's producer, and never as a null. | **A-2** — power short one key |
| 9 | Two records under one identity are a conflict only if they disagree; agreement is corroboration, and identical bytes are a parser defect. | program |
| 10 | De-duplicate by CONTENT, not by path; and a metric emitted once per member of a set needs a scope key naming the member. | program |
| 11 | A required-view list must be per axis: one unmeasured row on a shared list poisons every axis on it. | program |
| 12 | An artefact that varies with the implementation may not sit in the identity that must match; and a published claim that a named artefact is absent must be rechecked against the tree. | program, **A-7** |
| 13 | Same rule as 12's first clause, stated for the contract: the measurement CONFIGURATION is the identity, never the measurement's output. | program |
| 14 | Nothing that enters a hash identity may carry a path that differs between runs of the same configuration. | program **for emitted scripts**; the same class is LIVE for records — **A-17** |
| 15 | An axis must prove from the names its evidence actually prints, or declare itself unprovable — not from a name no artefact emits. | program |
| 16 | A proof must name the artefact the downstream consumer consumed; a proof about an upstream intermediate does not satisfy an axis scoped to the final one. | program — and the tool error behind it is **settled**: the step's own setup, not the tool, which is where **A-15** came from |
| 17 | A verdict token read from an artefact must be matched against a CLOSED enum, and a token outside it is not-measured with the token quoted — never a pass, never the nearest neighbour. | program |
| 18 | Where a schema offers two ways to state a check, the consumer must accept both; a verdict-valued check may not be required to produce a count. | program |

Two smaller ones carry rules too: an optional dependency must be bundled, and the
present-but-too-old arm needs a version matrix (**C-2**), and a runtime output path must
not resolve inside the installed product (**A-6**).

## The eighteen, and what is true on this tree

Eleven are ALREADY-PROGRAM. For each, the program or census test that enforces
it now — checked by reading it, not by trusting the fix note.

| F | already enforced by | general over |
|---|---|---|
| F-1 no owner for the excluded levers | `crosslayer_search_space.py` emits `UNOWNED` when the named owner does not resolve; `tests/test_ppa_pnr_search_space.py:340,362` has both arms | any deferral; the owner is resolved from the tree |
| F-2 `--backend` drove nothing | the driver seam in `_ppa/backends/__init__.py` (`extract_records` / `NO_DRIVER_REASON`); `test_ppa_producer_consumer_agreement.py::test_every_backend_is_drivable_or_says_WHY_NOT` | **NO — and this one was DISPROVEN by execution, not merely qualified.** The guard asserts each backend is drivable or raises with a reason of at least 40 characters. But `driver_for` synthesises a fallback reason when the module declares none, and the fallback is far longer than 40 characters — so the predicate is satisfied by construction for every backend and the guard cannot fail. Proven: deleting `NO_DRIVER_REASON` outright from the `opensta` backend (whole assignment, mutation re-parsed with `ast.parse` to confirm it is still valid Python) leaves the suite at **0 failed, 0 errors**. The separate literal-5-tuple limitation still stands on top of that. See **A-3** |
| F-4 producers emit envelopes the consumer refuses | `_ppa/metrics.py:963-965` registers all three carriers; `test_ppa_producer_consumer_agreement.py` §2 walks the whole envelope namespace | **in one direction.** Every REGISTERED carrier is checked to read; that every PRODUCER's envelope is registered is asserted over three literals. See **A-3** |
| F-5 declared unit vs required unit | `_ppa/area.py:188` moved to the name-derived unit; same test file §1 walks the whole area registry | every area metric, added or existing |
| F-9 two readings of one metric under one scope | `_ppa/metrics.py:582-676` separates corroboration from conflict; `test_ppa_second_record_identity.py`, 12 tests | any second record under one identity |
| F-10 every timing row emitted twice | `_ppa/timing.discover_reports` de-duplicates by CONTENT; `test_ppa_layer_timing_view_dedup.py` | any mirrored artefact tree; `path_ordinal` covers F-10b |
| F-11 `required_views` is global | `_ppa/feasibility.required_views_by_axis`; `test_ppa_feasibility_views_and_slack.py`, 6 tests | per-axis, including the empty-list and unknown-key cases |
| F-13 no rule for the `analysis` identity | `docs/PPA_INTERFACES.md` §3 states it in bold; `PPA-C-016` names the misfiled artefacts | any hash identity over an emitted artefact |
| F-14 absolute host paths in emitted scripts | `programs/emitted_script_portability_check.py` — a shipped gate, `26 of 34` on the run that produced it | every emitted analysis deck |
| F-15 no artefact prints a hold `wns` | `_ppa/feasibility.py:227-228` — the hold axis proves from the worst-slack name too | both timing axes, both proof groups |
| F-18 a count is demanded where the schema allows a status | `_ppa/benchmark.py` `CHECK_CLEAN` / `VERDICT_CLEAN`; `test_ppa_verdict_and_scope_shapes.py` | every floor check, verdict-valued or count-valued |
| (smaller) `jsonschema` not a dependency | `_ppa/jsonschema_bundled.py` — bundled, so a stock host is covered | and it names the too-old case the import guard missed |

Nine more classes, drawn from the six lane records rather than from the 18, are
also ALREADY-PROGRAM. Each was a candidate record until I opened the program:

| class | already enforced by |
|---|---|
| a PASS must say how much it looked at | `programs/gate_discloses_denominator_check.py` — a shipped gate over a 493-program population, with four measured walking bugs in its own header |
| a gate that read NOTHING must not exit 0 | `programs/gate_zero_denominator_refuses_check.py` — and its header states exactly why the first gate does not imply it, which is the distinction I would otherwise have re-derived |
| a bad invocation is 3, and asking for `--help` is not a bad invocation | `programs/_ppa/cli_exit.py` reads the exit code rather than catching the type; `test_ppa_layer_exit_contract.py` carries BOTH arms — the two are one defect from opposite sides, so a suite testing one manufactures the other. **The repo-wide form of this landed while this branch was open** and is worth the lander's attention: `programs/_gate_usage_exit.py` gives new gates an rc 3 because rc 2 already means VACUOUS, and `programs/_gate_invocation.py` recovers the distinction for the 1232 programs that predate it by reading the callee's error protocol out of its stderr. Their own measurement is the population: of 241 registered structural gates, **39 never got past argument parsing and every one was recorded as a benign input-missing skip**. I hit this live in this lane — the backlog sanitiser answered rc 2 to a missing `--file` and I read it as a content verdict before checking. `classify_not_invocable` was run on that exact invocation and named it, with a genuine content FAIL and a clean PASS as controls returning None |
| a present-but-empty population is never a pass | `tests/test_ppa_layer_vacuous_population.py` — the right question, on 8 of 19 programs; the coverage gap is recorded under **A-3**, not as a class of its own |
| a lever that deletes a design property is priced, and the axis refuses | `programs/ppa_eco_spare_records.py` producing the evidence, `ECO_AXIS = "eco_readiness"` in `_ppa/feasibility.py` refusing on it, and two gates on the flow's own spare-cell artefact. **Landed on main DURING this lane** — see the withdrawn `A-18` |
| a published run's inputs are declared by DIGEST, so identity survives the path | the trial contracts' `evidence_manifest` — **525 of 525** artefacts carry a content digest beside path, role and byte count. Demonstrated working: the published baseline was recovered by hash after its source project ceased to exist on this host. Found late, in the one source section this lane had not read |
| a shared ABSENCE is not a shared value, so records with no measured identity are not grouped together | `programs/ppa_contract_check.py` clause `PPA-C-007` — an identity that is NOT_MEASURED is CANNOT CHECK, never a pass, and the corpus mode refuses to key on it rather than comparing two runs on the strength of a shared blank. **Driven, not cited**: a contract declaring one identity as NOT_MEASURED returns four UNDETERMINED `PPA-C-007` rows naming each absent identity. The sibling gate states the matching exclusion out loud — a contract with no identities is dropped from the conflict scan, *because a silent exclusion is a denominator nobody can see* |
| an EMPTY value is not a value, because two empties compare equal | `programs/_ppa/metrics.py` `validate` — a verdict metric whose value is the empty string is refused `VERDICT_SENTINEL`, *"two of them compare EQUAL, so two circuits nobody compared would read as agreeing"*. **Driven, and two-directional**: the empty string is refused, a NUMBER carrying `unit: verdict` is refused `VERDICT_NOT_A_STRING` (*"a verdict encoded as a number is a number downstream"*), and a real verdict string trips neither. A different enforcement point and a different operation from `PPA-C-007` above — that one refuses GROUPING on an absent identity, this one refuses COMPARING on an absent value |
| a lever TRIED AND LOST is a measurement; one quietly dropped is not | `programs/_ppa/search.py` `audit_manifest` clause `LEDGER_TRUNCATED` — a manifest whose proposed-trial count exceeds the trials it publishes is refused with *"Publish every trial, not the best one."* **Driven, with the control inside the measurement**: two calls differing ONLY in the proposed count — the honest one does not raise it, the truncated one does. A sibling clause `RAN_COUNT_DISAGREES` covers the same gap from the ran side |

Three more are fixed on this tree but their guard is the fix itself, and the
CLASS is what this lane recorded instead:

| F | fixed by | record written for the class |
|---|---|---|
| F-6 sign-off reports carry no basis stamp | the multi-corner emitters stamp it (`phase3_one_shot_runner.py:34476, 35159`) | the STAMPING half is fixed. Its second clause — the emitters must be enumerable so none is missed — is **NOT**: 16 stamp sites, no test enumerating them. That is **A-3**'s class, recorded there as its seventh instance; **C-1** covers only the header rule |
| F-7 power measured before place-and-route | `_emit_power_report(basis=...)` derives every header line from what it linked | **A-8** (the invariance, which is the stronger evidence) and **C-1** (the header rule) |
| F-12 the search hard-wires the stub, and the stub's reason is false | `--feasibility-policy` plus `STUB_REASON_CONTRADICTED_BY_TREE` | **A-7**, generalised off that one string |

Four are LIVE on this tree, measured today:

| F | measured now | record |
|---|---|---|
| F-3 axes with no producer | 8 of 9 gained one (`_ppa/signoff.py`, 8 metric names). **`drv` still has none** — all four of its proof names are produced by nothing anywhere in the tree | **A-1** |
| F-8 power scope short of its required keys | process / voltage / temperature now filled from the liberty stem; **`mode` still absent**, so the comparison still refuses on both arms | **A-2** |
| F-17 the reliability report supports no count | the READER is now honest (a verdict outside the enum maps to not-measured with the token quoted) and a ratio proof was added; the axis is still undetermined on a default run | **A-28** — its own rule, which had been folded into A-1 and is a different thing |
| (smaller) a relative output path plants a file in the installed tree | reproduced below | **A-6** |

---

## The three the brief named — they are one shape, and the shape is already a program

*A producer emitting an envelope its own consumer refuses (F-4); a declared unit
and a required unit that disagree while each side is self-consistent (F-5); one
metric read twice under one scope (F-9).*

They are one shape: **two authors reading one interface differently, invisible
from inside either module.** A single rule does cover all three, and it landed
before this lane started —
`tests/test_ppa_producer_consumer_agreement.py`, whose own header states the
design decision that makes it a rule rather than three pins:

> This file is what makes them, and it is a CENSUS rather than a list of
> examples on purpose. … The tests below walk the whole registry and the whole
> envelope namespace instead, so a NEW metric or a NEW envelope is covered the
> day it is added rather than the day somebody writes a test for it.

So the three are ALREADY-PROGRAM and no record duplicates them. **What is NOT
covered is the same shape one table over**, and that is where two of this
lane's records went:

* the census walks the metric-name registry and the envelope namespace. It does
  not walk the **proof vocabulary of the gate** against the **emission
  vocabulary of the producers** — which is why an axis with zero producers
  survives it (**A-1**);
* nor the **required-scope key set** against the **emitted scope key set** —
  which is why a producer one key short survives it (**A-2**).

Both are set differences over tables that already exist. Neither needs a fixture.

And one level up from all three sits **A-13**: the reason a per-module suite
cannot see any of them is that a contract relation leaves no import edge, so
neither the module graph nor a per-module test can reach the pair. That is the
asymmetry the brief calls the richest material, as a rule.

---

## The 47 records

Every one carries the command and the number. The two questions the skill exists
for are answered per record: **(o)** would it have fired on the original defect,
**(d)** would it fire on a different instance of the class.

### A-1 · gate proof vocabulary has a producer · `ppa.feasibility`

The predicate, run from the registries rather than from a text scan — the four
producer tables unioned (8 sign-off + 4 power + 14 area + 8 timing, the last
EXPANDED from three format strings) and diffed against the nine axes:

    setup 2/3   hold 2/3   drv 0/4  <-- no producer for any proof name
    drc   1/1   lvs  1/2   antenna 1/1   ir 2/2   em 2/2   equivalence 1/1

    axes structurally unprovable: 1 of 9
      drv: max_cap / max_fanout / max_tran / violations — all four unproduced

Three further axes carry a proof name nothing emits and survive only because a
sibling proof group covers them; that is why the check must report per proof
name, not per axis. My first pass used a crude literal scan and I flagged it as
unreliable — the registry union **agrees with it on the headline**, so the
finding never depended on the weak method, but the partial rows are only visible
this way. Expanding the timing names from format strings is itself the evidence
for the record's demand that the timing module gain a declared table.

1 of 9 axes has no producer for any name in any proof group. **Nothing in the
tree asserts that an axis has one.** The nearest thing is
`test_ppa_signoff_records.py:445-451`, which lists that axis among the ones its
own producer does not cover — a statement that is correct about that producer
and says nothing about the tree, which is precisely the blind spot: every
producer can be right about itself while the union of them leaves an axis
unanswerable.
**(o)** yes — on the run that produced F-3 it was seven axes, not one.
**(d)** yes — the check is a set difference over registries, so an axis or a
proof name added tomorrow is covered the day it lands.

### A-2 · required scope keys are emitted by their producer · `ppa.head_to_head`

Measured first-hand on this tree by building the producer's real records and
diffing their scope against the consumer's table:

    records built            4
    scope keys emitted       activity_basis group liberty process scenario
                             stage temperature_c tool voltage_v
    REQUIRED_SCOPE[power]    activity_basis mode process stage temperature_c
                             voltage_v
    satisfied                5 of 6        MISSING: mode

The cross-layer lane's independent observation of the consequence:
`h2h_B` refuses `rc=2 SCOPE_INCOMPLETE`, naming that key, on both arms, before
any value is compared.

**The arm I had left open is now closed, and it went the other way.** I first
tried the timing axis with a text screen, which reported five required keys
missing. The screen was wrong; read from the module's own declaration instead:

    timing _SCOPE_KEYS (always present)  check clock mode process rc_corner
                                         stage temperature_c voltage_v
    REQUIRED_SCOPE[timing_wns_ns]        check mode process rc_corner stage
                                         temperature_c voltage_v
    satisfied                            7 of 7

So the required-scope gap is **power-only** on this tree, and the timing producer
is a **working reference implementation of the rule A-2 asks for** — including
the harder half: the keys are always PRESENT, and
`test_every_row_carries_all_eight_scope_keys` refuses an undeclared EXTRA as
well, on the stated ground that a key nobody declared makes a record
incomparable to every other record.

That also explains why the cross-layer lane hit `SCOPE_SENTINEL` on timing rather
than `SCOPE_INCOMPLETE`: timing's failure mode is a key that is present and
**null**. Between the two producers, both clauses of A-2 are evidenced —
one is short a key, the other has written a null one — and the record now says
the check owes three distinct verdicts: absent, present-and-null, and
undeclared-extra.
**(o)** yes — it was four keys then and it is one now; the predicate is the same.
**(d)** yes, and in the other direction too: the record's second clause refuses
a required key present with a null value, which is the failure the same lane hit
on a different axis (`SCOPE_SENTINEL`, `rc_corner: null` on the governing corner).

### A-3 · population guard asserts equality not a floor · `benchmark.verify_claim_done`

Measured on this tree, this morning:

    discovered by the glob `programs/ppa_*.py`        : 19
    declared in the vacuous-invocation table          : 15
    declared in the internal-error table              : 15
    undeclared in BOTH: ppa_agent_context_build.py, ppa_diagnostic_router.py,
                        ppa_pr_scope_check.py, ppa_signoff_records.py
    the guard: `assert len(PPA_PROGRAMS) >= 14`        : PASSES

The floor was written on a night when 14 and 14 were the same number. It now
passes over a population of 19 with 4 holes in it, and its own message still
reads "the fourteen shipped programs".

**The same defect sits on SIX tables in this layer, not one** — and two of the
six are inside the census the repository built to fix this class, which is where
it is hardest to see, because the file's subject is the rule it breaks. Only the
first was known when I wrote the record; the other five came from asking the
question once per table.

    two invocation tables            15 of 19 programs declared
    present-but-empty input table     8 of 19 programs reached
    producer trio in the census       3 named by hand
    backend tuple                     a literal 5-tuple; the package is importable
    envelope-producer direction       3 literals

Two of them, measured here:

    present-but-empty input cases declared : 8   (`range(8)`)
    programs those 8 cases reach          : 8 of 19
    NEVER given a present-but-empty input : 11

and that file DOES carry a guard —
`test_the_case_table_matches_the_parametrisation` — which asserts the table
against **its own length**. That is self-consistency: it passes for any table
and cannot see the population. It is the obvious wrong guard, already built,
which is why the record's fix action names it.

The fourth is the producer census itself: the backend package **discovers five**
modules and **three are drivable**, while the census names three producers by
hand. The one it does not name emits **3 of 3 records the canonical consumer
refuses** — `BAD_METRIC_NAME`, and `SCOPE_INCOMPLETE` and `NO_UNIT` behind it —
on this tree, today.

*Landed during this branch:* `programs/generated_test_list_min_guard.py` checks a
generated test list against a **minimum** and a resolvable path set rather than
against emptiness. That is a real improvement on "not empty" and it is precisely
the floor this record says is not enough — a minimum cannot see a list that should
hold 40 and holds 39. Build on that file: keep its resolvable-path arm and replace
the floor with declared-versus-discovered equality.

**(o)** yes. **(d)** yes, and in the direction a floor can never see — an entry
left behind for a member since deleted.

*An in-tree exemplar of the correct form, found while chasing a sibling lane's
un-actioned baseline note.* A shipped wiring gate ratchets on the **name set**,
not the count:

    gates: 624   unwired: 58 (baseline 59)   [PASS]
    [NOTE] baseline shrank — now wired: <one program>. Re-run with --write-baseline.

I read that as a defect first. A ceiling one larger than the measurement looks
like slack a future regression could hide in — one new unwired program returns
the count to 59 and nothing goes red. **It is not slack.** The comparison is
`set(now) - set(base)`, so a newly unwired program is a *name* absent from the
baseline and fails immediately whatever the count does; a second clause catches
the count growing with no new name, which is the stale-baseline case the first
cannot see.

Both directions matter for whoever builds this record. A *count* ratchet really
would have that hole, so this name-set-plus-count-backstop is the shape to copy
rather than re-derive. And the un-actioned shrink is tidiness, not an open hole
— nobody should write the baseline believing they are closing one.

### A-4 · layer membership is declared not inferred from a filename prefix · `benchmark.verify_claim_done`

The prefix glob reaches 19 executables; the layer is 25. Run the layer's own
bad-invocation arm over the six outside it:

    _ppa/timing.py                             --this-flag-does-not-exist  rc=2
    power_total_vs_budget_check.py             --this-flag-does-not-exist  rc=2
    _ppa/area.py, _ppa/backends/openroad.py,
    closed_loop_executable_coverage_check.py,
    readme_ppa_extractor.py                                                rc=3

Two of six carry the IDENTICAL defect the suite had just fixed inside the glob —
a bare argument parse returning the could-not-check code where the contract says
bad-invocation. Both take the one-line shared fix the others already use. *Re-run
after merging main: unchanged, and `--help` still returns 0 as the control. The
one-line fix now has a name — main landed `programs/_gate_usage_exit.py`, whose
whole reason for existing is that rc 2 already means VACUOUS, so import it rather
than re-declaring the constant.*
**(o)** yes. **(d)** yes — the relation is computed, so a module added inside
the layer's package next week is in the population without anyone editing a list.

### A-5 · two input selectors given together must refuse · `ppa.head_to_head`

    $ python3 ppa_head_to_head_check.py REC.json                      rc=1
      [FAIL] TOO_FEW_ARMS   — the record IS adjudicated and refused
    $ python3 ppa_head_to_head_check.py REC.json --corpus EMPTY_DIR/  rc=2
      [CANNOT CHECK] VACUOUS: the corpus carries no record
      — and the named record was never opened

Adding an unrelated flag turns a finding into a could-not-check, on a population
the caller did not name, and says nothing about the input it dropped.
**(o)** yes. **(d)** yes — it is declared at the argument parser, so it covers
every tool in the layer that grows a second selector, not this one call site.

### A-6 · a runtime output path may not resolve inside the installed tree · `ppa.artefact_write`

    $ cd <install>/programs
    $ python3 _ppa/backends/openroad.py --log /tmp/…/openroad.log --json _probe_out/x.json
    rc=2
    $ git status --short
    ?? programs/_probe_out/

The run REFUSED and still wrote the file and created its parent inside the
installed product. A refusal that leaves the damage behind is worse than either
outcome alone, which is why the record requires the resolve-and-refuse to happen
before any directory is created.

**A stronger reproduction, found by accident while probing something else.** The
caller need not supply anything at all:

    $ cd <install>/programs && python3 <a-command>          # no arguments
    rc=0
    $ git status --short
    ?? programs/reports/<a-command>.json

The command carries a **relative default** output path, so it plants a directory
in the shipped product and **returns success**. That is worse than the
refused-but-wrote case twice over: there is no caller mistake to blame, and no
non-zero code to notice. It is also the first thing an ordinary user does —
run a tool with no arguments to see what it does. So the check must cover
DEFAULTS, not just caller-supplied paths.

**Nearest prior art, checked rather than assumed:** `programs/suite_write_guard.py`
blocks a TEST RUN that leaves the tree it tests dirty, and it exists because
three writers into the installed tree were each found by accident. It is scoped
to a suite session and it looks after the fact at the working tree's status — a
person running a shipped command outside any session is not in its population,
and by the time it would look the write has happened. Named in the record so the
next reader neither rebuilds it nor mistakes it for coverage.
**(o)** yes. **(d)** yes — it goes in the shared atomic writer, so it covers
every tool that takes an output path, not the one that was caught.

### A-7 · a published absence claim is rechecked against the tree · `ppa.search`

The stub published, verbatim into every manifest of a 60-arm sweep:

    "feasibility lane not wired: _ppa/feasibility.py has not landed"

The module had landed three commits before the program that published the
sentence. Now guarded for that one string; the class — a provenance note
asserting a named artefact is absent — is not.
**Corpus-swept on this tree, and the sweep is where the rule's two
qualifications came from.**

    verb and path anywhere in one literal (119,359 literals)   560   all noise
    + proximity, wide window                                    85
    + proximity, medium window                                  14
    + proximity, tight window                                    6
    - four attach the verb to a different noun                   2
    - two are messages on a not-found branch                     0   real

Both narrowings are now the substance of the rule. **The verb must attach to
that path** — sharing a docstring with it is not attachment, which is the entire
560. And **the claim must be unconditional**: a message emitted only on the
branch where the artefact was found missing is correct by construction, and the
two survivors are exactly that.

**This rule runs CLEAN on the tree today.** That was measured when there were
thirteen Bucket-A rules, and it was the only one of the thirteen with no real
hit; it has NOT been re-derived across the twenty-eight, so read the uniqueness
as dated and the cleanliness as current. Its motivating instance was fixed at its one site. It is worth having
anyway: that site was guarded by hand for one string, and nothing stops the next
stub from carrying the next one.
**(o)** yes: the claim reduces to a path, the path resolves, the check is a file
test. **(d)** yes — it is applied at the publish boundary, so a reason string
copied into a new publisher inherits it.

### A-8 · a metric constant across arms that differ is not measured under that lever · `ppa.search`

The strongest evidence in the whole cluster, and it needs no reference
measurement:

> Across a 60-configuration sweep the shipped power report was **byte-identical
> 60/60** while all 60 routed netlists and all 60 parasitic files differed.

The magnitude error (1.873x low, clock group at exactly 0.0%) was the weaker
finding — it took a controlled re-measurement to establish. The invariance is
available inside the flow, from the manifest the sweep already writes.
**Corpus-swept on a real 21-arm published sweep, and NARROWED BY IT.** The
invariance test alone is unusable:

    axes with >=2 arms                                     54
    invariant across arms whose implementations differ     24   <-- unusable
      + a SIBLING of the same quantity varies               8
        + the frozen value is a numeric sentinel            4

Most of the 24 are a clean design being clean on every arm — a DRC count of zero
on all 21 arms is correct, and flagging it is noise. The discriminator is the
sibling: when one reading of a quantity moves across the arms and another reading
of the SAME quantity does not, the frozen one is not describing the arms. It
needs no reference measurement and no knowledge of the right value, which is what
lets it run inside the flow.

**The top hit is a live defect, and another lane found it by a completely
different route.** A timing summary sits at the sentinel `0.0` on all 21 arms
while its sibling reading of the same quantity spreads over 20 distinct values —
from a multi-corner report whose corner key the comparison gate separately
refuses as null (the cross-layer lane's `SCOPE_SENTINEL`). Two methods with
nothing in common converging on one record is the strongest evidence either can
give, and this one adds what the scope check cannot: **the number itself does not
move when the thing it measures does.**

**(o)** yes, and it would have fired on arm 2 rather than on arm 60.
**(d)** yes — demonstrated: run on a sweep it was not written against, it named
eight candidates and four strong ones without being told what to look for.

### A-9 · a writer enforces the field shapes its declared consumer requires · `benchmark.verify_claim_done`

Found by using the tool this brief mandates. `enhancement_emit.py` documents
`component` as free text and validates it not at all; its sibling
`backlog_sanitize_check.py` requires a prefixed form. Both of my first two
emitted backlogs were refused, and the corpus shows it is not just me:

    in-tree backlogs failing the COMPONENT rule alone: 6 of 29

Each side self-consistent, each side's tests green, refusal arriving from a
different tool in a different run — F-4's shape exactly, inside the capture
tooling.

**Re-measured after merging main, and it got worse: 10 of 33.** All four new
failures are the three SIBLING capture lanes that landed the same night — the
same loop, the same emitter — carrying component values like a stage description
or a bare word. This lane's three backlogs pass, and only because the refusal is
what produced this record: I hit it on my first two and changed the values. Three
authors who did not happen to run the sibling validator shipped artefacts it
rejects, and nothing in the emit path told them.
**(o)** yes. **(d)** yes — the rule is "import the validator's shapes into the
writer", so it covers every field the validator constrains, not this one field.

### A-10 · an accepted-value branch must be able to express its own vocabulary · `benchmark.verify_claim_done`

    COMPONENT_RE = r"^(skill|program|mcp|flow):[\w_-]+$"
    canonical step identifiers: 42   accepted by the `flow:` branch: 0

Every canonical step identifier is dotted; the branch's suffix admits word
characters and hyphens. The branch names the flow's own step vocabulary and can
express no member of it. Zero in-tree records use it — which is exactly what a
dead branch and an unused branch have in common, and why nothing caught it.

**Three independent confirmations, and the third was unprompted.** The 0-of-42
scan; my Bucket-T record's component; and then, filing C-2 in this same batch, I
reached for it a third time — the natural component for a host-independence item
is the flow step that owns it — and was refused again. **An author who KNOWS the
branch is dead still reaches for it**, because it is the correct-looking answer
and the error message lists it among the supported forms. A dead branch is not
merely unused; it costs every author who trusts the help text.

**Where it lands, found by reading the emitted backlog as its recipient.** The
Bucket-T ticket in this bundle declares `root_cause_layer: forked_tool` and names
its tool — and its `component` field, the one a tracker routes on, said
`program:` followed by a plugin runner. A forked-tool bug addressed to a plugin
maintainer, because the branch that should have carried it cannot express a
dotted step identifier and the author falls back to a prefix that is wrong.

The sharper half is what the fallback revealed:

    fork:openroad     refused
    tool:openroad     refused
    flow:phase3       accepted

**The accepted-value set has no term for a layer the record schema itself
declares.** Two fields of one record disagree about what kinds of thing exist,
which is this cluster's shape inside the capture tooling's own grammar. The
ticket now reads `flow:phase3` — expressible, and merely coarse rather than
false, which is the best the grammar allows.

**(o)** yes. **(d)** yes — it is a census of a vocabulary against a pattern, so
it also catches the harder direction: a branch that works today and dies when
the vocabulary gains a separator. And it must run BOTH ways: every value the
vocabulary admits must be reachable, and every layer the schema declares must
have a value that names it.

### A-11 · discovery selects on the parsed document not on the filename · `ppa.head_to_head`

    _RECORD_GLOB = "**/*head_to_head*.json"

Run against the two record trees this repository already carries:

    ppa-crosslayer/records   582 json   15 declare the comparison schema   glob selects  0
    ppa-e2e/records          496 json    2 declare the comparison schema   glob selects  4

Zero of fifteen in one tree. In the other it selects **four where only two are
inputs** — the other two are the gate's own `_report` documents, which declare
no schema and carry an entirely different key set. Both directions of wrong,
from a name.

The two shipped denominator gates do not catch it and cannot: both are satisfied
by *a* disclosed count, and this gate discloses honestly — over a population that
was already filtered by the thing under suspicion.

**A second instance, in the same layer and sharper.** The timing module selects
sign-off reports with `sta*.rpt` under three named directories, and its own
comment claims the consequence:

> *every `sta*.rpt` under them is read, so a new corner report is picked up
> without a change here.*

True only for a report whose name starts with the token. Against the report
names the flow's own runner writes:

    timing-shaped reports the runner writes : 13
    reached by the name pattern             :  8
    not read: aging_sta, post_route_timing, pre_pnr_timing,
              si_crosstalk, si_crosstalk_timing_aware

and `pre_pnr_timing.rpt` is a report the **same runner deliberately stamps** with
the basis marker this module exists to read. Some of the five may be out of scope
on purpose; **nothing in the selector says which, and that is the defect rather
than the count.**
**Corpus-swept, and the population is not what it looks like.** Applied to every
filename pattern in the program layer:

    all discovery patterns                                  1584
      extension-only, not this rule                         1222
      carrying a semantic filename token                     362   <-- unusable
    scoped to scans over a CALLER-SUPPLIED corpus             12   <-- the real rule

The 362 are overwhelmingly correct — a layer reading artefacts it wrote itself,
under names it chose, in a directory it owns. There is no two-author problem
there. The rule holds where the documents may have come from a producer this
layer never saw, and that is **12 programs, not 362 sites**, which makes the
check per-scanner and tractable.

**And it must follow constants.** A screen reading only the literal argument of
the discovery call finds 4 of the 12 and **misses the case that motivated the
rule**, whose pattern is a module-level constant — the third time in this batch a
naive screen has failed on the very case it was written for.

**The second instance is a different rule** and is split off. The timing-report
case is same-layer, so the corpus argument does not apply to it; what is wrong
there is that the module's own comment claims a new report is picked up without a
change and the pattern does not deliver it. That belongs with the documented-claim
family.

**(o)** yes. **(d)** yes — the predicate is "select on the declared schema", so
it holds for any document class this layer gains, and the third disclosed number
it requires (files that would not parse) is the half neither denominator gate
asks for.

### C-2 · An optional dependency needs a version matrix, because present-but-too-old is the arm nothing tests · `repo.host_independence`

**Demoted from Bucket A by its own sweep.**

This began as a Bucket-A static rule and its own corpus sweep disproved it. The
narrowing went four rounds and every one over-reported:

    try/except ImportError handlers binding a name              131
      using an attribute outside the handler                     79
        with no capability guard on that use                     56
          excluding sibling and standard-library imports          8

Then I executed the six of those eight that can be run with the dependency
blocked. **Six of six degrade with a message; none crashes.** The static form
does not work, and I could not construct one that does.

**The reason is that the motivating defect was never the absent case.** It was an
attribute that arrived in the dependency's next major release, on a host carrying
the older one — the import SUCCEEDS, the guard never runs, and the attribute
raises. Blocking the module entirely, which is the only state I can synthesise
here, does not reproduce it. Absent and too-old are different states and only the
first is an import failure.

> **why_not_bucket_a**: A program cannot decide this from the source: I built the static check four
> ways and every one over-reported, and all six survivors I could execute
> degraded correctly. The input that would settle it — the dependency
> INSTALLED AT AN OLDER RELEASE — does not exist on the host at check time,
> and no amount of reading the code conjures it. Producing that input is a
> version matrix in CI, and that is the engineering.

Cost of the case that bit: **33 red test identifiers** on a stock host, and a
crash returned under the exit code reserved for a finding about the design.
**(o)** yes, but only from the CI arm it asks for — no reading of the source
would have caught it, which is the whole reason it is Bucket C.
**(d)** yes — the arm covers every optional dependency at once, including the
next one adopted, which is what a per-site rule could never do.

### A-13 · a contract relation is not an import edge and owes a pair test · `repo.test_population`

**This is the record for the asymmetry the brief names as the richest material in
the repo** — every one of the eighteen passed its own module's tests and was
caught only end to end. I had recorded the individual rules and never the
asymmetry itself.

The reason those defects are end-to-end-only is structural, not accidental. Two
modules agree on a document shape; neither imports the other, because the writer
builds a plain mapping and the reader receives one. **The relation lives in the
shared vocabulary and nowhere in the code.** Measured on this layer:

    module pairs sharing a schema identifier          47
      ...of which have an import edge                  0
    after excluding the ONE token >2 modules carry      6 contract pairs
      with an import edge                               0 of 6
      with a test importing BOTH sides                  5 of 6
      with NEITHER                                      1 of 6   <-- live

So a dependency-graph check finds **none** of them — and the five that are
covered were covered by the lanes that repaired the seam defects, one pair at a
time, after each was found the expensive way.

**The rule makes a live prediction on this tree**, which is the test of whether
it generalizes rather than describes the past: one pair — a document identifier
shared by exactly two modules — has neither an import edge nor a pair test, and
it is the same shape that produced four of the eighteen findings.

The detector's own denominator is part of the rule. Without excluding the token
that most modules carry, this layer reports 47 pairs and the 6 that matter are
indistinguishable from the 41 that do not.
**(o)** yes — four of the eighteen sit on pairs this enumerates, and it names
them without knowing anything about what went wrong.
**(d)** yes, demonstrably: it is already naming one nobody has looked at.

### A-14 · a documented command must be accepted by the program it names · `repo.doc_command_reproducibility`

Found by invoking the skill this brief is the loop of. **Its own documented
invocation of its own driver program does not run:**

    $ python3 enhancement_emit.py --records R.json \
          --out-skill-section p.md --out-program-rules p.py --out-backlogs d/
    enhancement_emit.py: error: the following arguments are required: --out-dir
    rc=2

Re-run after merging main: identical, with the declared form returning 0 as the
control. The text is at `skills/benchmark-enhancement-capture/SKILL.md:532` in
the repository, not only in the installed copy — a four-line continued invocation
whose three output flags were all replaced by one. It is deliberately not
hand-patched here: correcting the line would remove the motivating instance and
leave the population unguarded.

An existing guard already checks that a command quoted in the release notes and
manifests names a file that EXISTS. Two things put this case outside it: skills
are not in its population, and it tests existence rather than acceptance — a
stale flag and a correct one point at the same existing file.

    quoted commands naming an existing program            165
    using an option the program neither declares nor mentions  11
    of those, confirmed by RUNNING them                     2
      one reports `unrecognized arguments` outright; both exit on an argument error

**Write the screen carefully — mine was wrong twice, in opposite directions, on
this same corpus.** Matching greedily across lines bled the trailing compliance
block into the preceding command and reported **47**. Confining the match to one
line excluded every multi-line invocation and reported **0** — missing the one
case I had already proven by execution. Joining continuations first gives 11. A
checker for this that is itself built by grep will reproduce one of those two
wrong numbers, so the record says so.
**(o)** yes — it names the case that produced it.
**(d)** yes: 10 further candidates it found without being told what to look for.

### A-15 · a tool-error verdict must carry the tool's own diagnostic · `phase3.lec_post_layout`

**This is the record that settled F-16**, and it came from asking why the
attribution was impossible rather than from finding the answer directly.

    the consuming gate   a substance check over a produced document — it NEVER
                         runs the tool, yet its finding text names the tool
    the producing step   runs the tool, and retains NOTHING from it: no exit
                         status, no output tail

Two layers assert that the tool failed; neither saw the tool. A genuine tool
defect and a setup gap in the step's own invocation produce a byte-identical
record, and those are fixed in different repositories — so the verdict cannot be
routed, which is exactly the wall this lane hit.

Worse than unattributable: the consuming gate **restates** the attribution it
inherited, so an unevidenced claim appears at two layers and reads as
corroborated.
**Swept, and the sweep moved the check.** A code scan cannot answer this: the
verdict lives in a constant rather than a literal, so a literal scan finds one
site of the several that exist; and asking whether the producing FILE mentions an
exit status is meaningless when that file is tens of thousands of lines long — it
says yes for reasons unrelated to this artefact. The predicate is artefact-level:

    keys written beside the verdict   verdict · tool · top · skipped · skip_reason
    carries a tool diagnostic         NO
    schema for the artefact           NONE — so nothing can require one

**The rule's home is a schema**, making the diagnostic mandatory whenever a
verdict names a tool, not a scan over source.

**Its sharpest instance is this batch's own Bucket-T record**, found by opening
the samples rather than trusting that the paths resolved: ten committed
directories cited for a signal-11 crash, none carrying a log or an error file,
each recording a runner exit of 1 — the same value the golden arm records. The
tool's real status survived only in an uncommitted transcript, so the record
cannot be filed upstream at all. That is what this rule buys: not tidier
artefacts, but the difference between a fork bug that can be handed over and one
that cannot.

**(o)** yes — had the diagnostic been retained, F-16 would have been assignable
on the day it was found instead of open across a whole lane.
**(d)** yes — it is per tool-invoking step, and the tree has many.

### A-16 · an admitted lever must report its applicable site count · `ppa.search_space`

From the source section I had skimmed rather than read — the cross-layer lane's
account of **what it did not search**. One entry is a defect, not a choice:

> *`state_encoding` was admitted and is VACUOUS on this design … the lever is
> admitted, its applicable-site count is zero, and no candidate was authored.*

Admission answers whether the specification PERMITS turning a lever. Whether
there is anything here to turn is a property of the DESIGN, and the published
space conflates them. Verified on the document itself:

    admitted_count                                   5
    keys carried by each admitted lever             10
    of those keys, an applicable-site count          0

So the lever with nothing to turn is indistinguishable from the four with plenty,
and a planner reading `admitted_count` sizes a search against a dimension that
cannot move. The lane that hit it wrote the fact down in prose; **nothing in the
machine-readable space records it.**

This is **A-8's problem on the input side** — and cheaper. A-8 catches an axis
that did not move, after the arms are spent; this catches a lever that could not
move, before the first one is.
**(o)** yes. **(d)** yes — it is per lever per design, so it re-answers on the
next design, where a different lever will be the vacuous one.

### A-17 · a provenance path convention must be declared and identical across producers · `ppa.record_provenance`

From the last source I had not read — the method note, which mentions the split
in passing and treats it as a curiosity:

> *Artefact paths in the records are as the producing tool reported them:
> relative to the project root where the tool reported relative, absolute where
> it reported absolute. They were not rewritten, because a `source.path` that is
> not the path that was read is not provenance.*

Not rewriting them was right. But the split itself is a defect, and it is larger
than the note suggests. Measured across both published record trees:

    absolute  source.path     6867      of which host-prefixed:  6867
    relative  source.path     6674
    (as first measured; the screen was not recorded, see the correction below)

    always relative   opensta · yosys · signoff
    always absolute   openroad · power

**Corrected by an independent re-measurement, and the correction cuts against
what this record originally argued.** The figures above were taken with a screen
this report never stated — which is `A-27`'s defect, in this report — so they do
not reproduce. Re-run over both trees, grouping on `source.tool`, the field that
actually names the producing tool, and again on the metric family:

    by source.tool      absolute 6804 (host-prefixed 6804)   relative 5330
                        MIXED: openroad, opensta
    by metric family    MIXED: area, power, timing

So the split is **not** perfectly per producer. It is inconsistent *within*
producers, under both groupings available. That is worse than the original
reading, not better: the excuse that no single author could have seen it is gone,
and a per-producer fix would not converge. What reproduces exactly is the part
with a consequence — **every absolute path embeds a host home directory, 6804 of
6804**, in a field a reader trusts as neutral. The rule therefore attaches to the
FIELD, checked per record, because grouping by producer is precisely what hid the
inconsistency.

The existing portability guard cannot see any of it: it walks emitted scripts by
file suffix (`.tcl`, `.sh`) and never opens a record. So the F-14 class was fixed
for scripts and left standing for records, which is the same rule at a different
artefact class — the pattern this lane keeps finding.
**(o)** yes. **(d)** yes — it is per producer per field, so it re-answers for the
next producer added and for any other provenance field the record gains.

### A-19 · a cheap fidelity rung may not rank candidates until its rank agreement is measured · `ppa.search`

The search ships an ordered fidelity ladder, *cheapest first*, so candidates can
be screened early. Nothing requires the cheap rung to order candidates the same
way the deciding rung does — and measured on the rewrite candidates, **it does
not**:

    candidate      cheap rung      deciding rung
    nr_csel16       -21.3 %   1st     -3.3 %   3rd
    csa_mux          -6.7 %   2nd     -4.3 %   1st
    csa_alt_maj      -2.6 %   3rd     -1.3 %   2nd

This is an **order inversion**, not a loose fit. The candidate that wins by a
factor of three on the cheap rung places **third** on the one that decides, and
the true winner is second-best cheaply. **A screen keeping the cheap top
candidate discards the answer** — and the run looks efficient while doing it:
budget respected, every survivor properly evaluated, the winner simply absent
with no trace it was dropped.

The cause is physical and general. The cheap rung cannot see that the winning
candidate was *buying away* a structure the later stage charges for: **+580 µm²
of added buffering against 628 µm² saved** by the removed registers.

**The plugin already ships this idea for another track** — a bench measurement
must be shown to correlate with its simulated prediction before the prediction is
trusted. The digital search layer has the ladder and not the gate, which is the
same rule at a different artefact class, again.
**(o)** yes. **(d)** yes — it is per rung pair, so it re-answers for any ladder
the layer gains.

### A-20 · a consumer must resolve a declared output path rather than guess among candidates · `phase2.final_audit`

From a lane's own *what I could not settle*: a reliability screen writes wherever
its option points, no step pins the path, and the consumer tries **three guessed
names**. The lane called it *"a convention, not a contract"* and left it.

It is broader than the one axis, and the discriminator is that **the flow already
declares the path**:

    consumers carrying an ordered candidate list for one artefact      48
      naming at least one path the flow ALREADY declares               33
        ...in a program that reads the flow declaration                 3
        ...in a program that does NOT — guesses anyway                 30

*The screen behind 48 / 33 / 3 / 30 was not recorded, so these figures cannot be
reproduced from this report — the same gap that made `A-17`'s numbers
unreproducible, and the second instance of `A-27` inside this document. They are
dated to the original base and are not re-derived here, because reconstructing a
screen by guesswork returns a confident wrong number, which is the failure `A-27`
exists to prevent. The RELATION they describe — a declared path and a guessed
candidate list for one artefact — is verifiable independently of the counts.*

One artefact, two definitions of where it lives, and the list is where they
drift. The failure is silent in the worst direction: a consumer that finds
nothing reports the artefact **absent**, which is indistinguishable from a step
that never ran — so the axis degrades to not-measured and the run stays green.

The rule orders the declaration first and keeps the list as a **disclosed**
fallback rather than deleting it: some of the 30 may be supporting older trees
deliberately, and a second-choice hit that fires silently is itself evidence the
declaration is wrong.
**(o)** yes. **(d)** yes — it is per declared artefact, so it covers every one
the flow gains.

### A-21 · which stream carries the summary is part of the contract and must be driven to a real verdict · `ppa.cli_contract`

The originating lane spotted one program on the wrong stream and **declined to
sweep the layer**, saying so: *"asserting it could redden other lanes' files on a
clause I have not measured everywhere."* That restraint was right, and the reason
the clause is unmeasured is itself the finding.

Driven to **real verdicts**, two-sided:

    comparison command, vacuous corpus    summary -> stdout    marker -> stderr   OK
    contract command, 16 findings         summary -> stderr    stdout EMPTY       not OK

One conformant, one not. **The other seventeen are NOT MEASURED and are not
claimed** — driving each to a known verdict needs valid inputs per program, which
is exactly the work the originating lane declined.

**The screen warning, earned here.** My first probe ran every command with no
arguments and compared stream byte counts. It reported 18 of 19 "on stderr" and
is worthless: that is the argument-parser path, which is on the refusal stream
for every command by construction. It measures argparse, not the contract — the
another instance of a screen measuring something adjacent to its subject; the
lane-wide count is reconciled under *How often the instrument was the problem*.
**(o)** yes. **(d)** yes — a known-verdict invocation per command covers every
command the layer gains.

### A-22 · a third-party import at test module scope must be guarded or it aborts collection · `repo.test_population`

The tests lane found **two** files importing PyYAML at module scope with no
guard and judged them latent, the host having the package. The count is what
makes it worth doing:

    module-scope third-party imports in the test tree, unguarded   51
    distinct packages involved                                      1

*Re-run on the merged tree with the screen this record states — third-party means
resolving nowhere in the repository, and the test runner itself is excluded
because a missing runner is not a collection hazard: **50 occurrences in 50
files, still exactly one package**. Main touched six test files and none is in
the set, so the one-file drift predates the merge. The screen warning below was
re-earned in the act of re-running it: dropping the directory term from the
in-repo name set — keeping only module stems — reported 174 files instead of 50,
which is the same over-match in the same place.*

Exactly one package — so the fix is bounded and mechanical. **Proven, with a
positive control on the same blocked dependency:**

    test file   1 error during collection ... Interrupted    ZERO tests run
    program     rc=2, stated could-not-check                 degrades correctly

A skip is a *result* and appears in the roll-up. A collection error is the
**absence** of results, and it **interrupts the session** — so one unguarded
import in a tree of hundreds turns a full run into no run, and the tier that
exists to catch infrastructure-shaped non-runs cannot see a file that never
collected. The product side already handles the same dependency correctly, which
is exactly why the test-side omission is easy to miss.

**Screen warning:** a name is third-party only if it resolves nowhere in the
repository. Matching against a list of module stems misclassifies in-repo
packages and reports 216 — another over-match — the total is under *How often the instrument was the problem*.
**(o)** yes. **(d)** yes — it is per test module per import, so it covers the
next optional dependency the suite adopts.

### A-23 · a distilled rule must be routed into a program some verdict consults · `capture.emit`

A lane's note about unwired gates raised a question about **this deliverable**:
routing picks the program that *owns* the subject, which is the right criterion
for correctness and says nothing about whether anything **runs** it. A rule in a
program no verdict consults is silent forever — and worse than an unwritten one,
because the record asserts the class is now covered.

The tree already maintains the other half of the join:

    gates 624   unwired 58 (baseline 59)   newly unwired 0
    (was 61 when this branch began; main wired three, and the gate now PASSES)

and one of the three newly unwired is a program of **this very layer**, so the
bad pairing was reachable rather than hypothetical.

Checked, and the batch passes:

    Bucket-A records            44     (22 when the rule was written)
    distinct target programs    25
    targets that are unwired     0

**That is the result to want and not the one to assume** — I had not verified it
until writing this rule, having routed twenty-odd records on ownership alone.
It has since been **re-run as the batch grew**, which is the rule applying to
itself: a check quoted once is a check that was true once.

**And it is now automated, which is the rule applying to itself twice.** Running
it by hand at 21 records and again at 26 is exactly the failure this record
names. `verify.py` check 25 reads the wiring gate's committed baseline — the 59
programs known to be consulted by no automatic verdict — and refuses any record
routed at one. **The fast form's limit is stated in the check itself:** it cannot
see a program that became unwired *after* the baseline was written; the
authoritative answer needs the gate itself, about forty seconds. Saying which
one you ran is the difference between a measurement and a reassurance.

**And the limitation is now closable, not merely disclosed.** `--slow` runs the
gate and compares the live unwired set against every routed target; the default
stays fast because it is free. Measured both ways: live-unwired targets, none.
A disclosed limitation nobody can act on is just a nicer way of not checking.

**And `--slow` now also re-derives the live figures this report quotes.** Two
places here paste `gates N, unwired M (baseline B)` out of a gate run made during
the lane — another program's output, sitting in prose, with nobody re-deriving
it. The STATUS block showed exactly what happens to such a number. The check
compares all three against the gate's current output.

Its first regex matched **neither** side: the tool prints the figures with
colons, the report quotes them without. Two renderings of one fact — which is
the reason the check is worth having, and was the reason it did not work. The
control caught it and reported itself BROKEN rather than passing.
The check belongs at emit time, refusing the pairing and saying which half must
change: wire the program, or route the rule somewhere that runs.
**(o)** yes. **(d)** yes — it is per record per emit, so every future batch is
covered without anyone remembering.

### A-24 · a repository-scoped gate loses its coverage when a tree is split out · `repo.tracked_artefact_hygiene`

From a lane's requests: five tracked artefacts in the published corpus are
**truncated JSON**, and *"before this branch nothing walked that tree looking, so
nothing reported them."*

The gate for that exact class **exists and is wired**, and its own header records
the failure it was written for — a file truncated mid-string passing every
landing gate. So why did it not fire? Because coverage of a root-scoped gate is
whatever root it is handed:

    programs walking a repository index                       38   (37 when first measured)
    programs referencing the split-out tree by name           99   (98 when first measured)
    the tree present in this repository                       NO
    ...but a clone of it IS reachable on this host, tracking  8309 files
    declared as a submodule                                   NO  (module list empty)
    resolved instead by                                       an environment variable
    the hygiene gate is invoked with                          this repository's root only

*Both figures were re-derived after I found I could not reproduce them from the
record.* Each counts files directly under the program directory, matched on
source text — one for the version-control index query, one for the corpus
directory's name. Both moved by exactly **one**: a tree that grew, not a screen
that disagreed. The tell is that a genuine scope change moves the second by
**six**, not one — including the package subdirectory gives 105, which is a
different question and not a better answer.

One trap for the next reader, because it produced a wrong number inside this
audit: writing the alternation in extended-regex syntax as though it were
basic-regex matches the literal backslash and returns **zero**, silently. A
broken screen and a clean tree print the same — this batch's own central class,
turning up inside the audit of it.

*The screen behind 37 and 98 was not recorded, so these figures cannot be
re-derived from this report — the third instance of `A-27` inside this document,
after the provenance split and the declared-output-path breakdown. Attempting it
returned 88 and 364 against 37 and 98, which is not evidence that the tree moved:
it is evidence that a plausible screen and the original screen are different
screens. The figures are dated to the base and are not re-derived here. The
RELATION they support — a root-scoped gate covering a root the consumed tree is
no longer under — does not depend on either count and is verifiable on its own.*

The tree was moved out, the product still consumes it in many places, and **every
root-scoped gate stopped covering it at that moment** — with no change to any
gate's name, wiring or verdict. The population simply got smaller and nothing
could say so. The split is recorded as a layout improvement; the loss of coverage
is recorded nowhere.

This is the **third** time in this capture that the tree's departure produced a
gap: the Bucket-T roadmap that cannot be written, the records whose provenance
paths I could only audit here, and now this.
**(o)** yes. **(d)** yes — it is per gate per consumed tree, so it covers the
next tree that is split out.

### A-25 · every emitted document type must have the schema its own interface promises · `ppa.schema_coverage`

A lane asked, in its requests, why one document type had no schema file when the
interface says every instance document has one. It is not one type:

    document-type identifiers producers emit    29
    schema files present                        14
    types with NO schema                        >= 17

At least 17 — and the arithmetic is not 29 minus 14, which is the first thing a
reader will try. The matching errs toward reporting a schema as PRESENT, so 17 is
a floor on the unschema'd, implying at most 12 of the 29 types are actually
covered. Two of the 14 schema files therefore match no emitted type at all, which
is the reverse direction this record's second answer names. The
type the lane asked about is among them, and so are the bundle, the sign-off
record set, the frontier and the evidence manifest.

**This is an upstream cause, not a peer of the other records.** Two findings
already in this batch reduce to it:

* **A-15** — a tool-error verdict carries no diagnostic, and *"there is no schema
  for the artefact, which is why nothing requires the field"*;
* **A-17** — one provenance convention is resolved both ways, and
  re-measurement showed it is inconsistent *within* producers rather than
  cleanly between them, so there is no producer-level owner to arbitrate and
  nothing states which is meant.

Neither can be fixed where it was found. Both need the document type to be
describable first, which reframes them as symptoms and puts the repair here.
**(o)** yes. **(d)** yes — and in the reverse direction too: a schema for a type
nothing emits is a document class that went away and left its contract behind.

### A-26 · a docstring stating a measured fact must be bound to the measurement · `repo.test_population`

A lane flagged two docstrings as having gone stale and left them for their owner.
One is confirmed against the tree:

    _ppa/backends/opensta.py:39   "...the only dialect that stamps its own basis"
    the runner today             TWO distinct stamping sites

and the second site was added by the very change that made the sentence false.
The behaviour the paragraph justifies is still right — the stage is read from the
stamp, never inferred — so nothing misbehaves and no test fails. **Only the
stated fact expired.**

The tree does check stated counts, and it binds **2 prose documents and no
docstring** — so the most-read explanation of a module is the least-checked text
in the repository.

**I did not estimate the at-risk population, and the reason is worth recording:**
my attempt to count quantified docstring sentences matched a pattern literal
inside a regex and reported a "document" that does not exist. That is the tenth
measurement-apparatus error of this batch, so the record ships with **one
confirmed instance rather than a number I could not defend.**

*Attempted again, properly, and the naive number turns out to be the wrong
number* — which is worth more to the implementer than no number. A quantifier
screen over every module, class and function docstring in the package returns
**44 sentences**. Reading all 44:

| what the sentence is | can a tree change falsify it? |
|---|---|
| a design invariant — *refusing is the only safe read*, *the ONLY place exit codes are decided*, *an empty list is the only PASS* | **no** — the majority |
| a tree census — *the only dialect that stamps*, *all 22 edges on main*, *all three sign-off reports are byte-identical* | **yes** — the enforceable subset |

A gate flagging all 44 is switched off as noise within a day. The screen must
pair the quantifier **with an artefact-class noun**, because a census sentence
always names the thing it is counting and an invariant does not.

Two findings for whoever builds it. The lane's **second** flagged docstring was
already repaired in place — and repaired well, stating the old behaviour in the
past tense and the new one after it — so this class is handled today
*reactively, one site at a time, by whoever happens to touch the file*. That is
the argument for the gate, not against it. And there is a test in the tree whose
**name reads as exactly this rule and which is the wrong thing to extend**: its
subject is canned prose emitted into generated documents by one function, not
docstrings at all. I nearly recommended it.
*Landed during this branch, and it narrows this record without closing it:*
`programs/emitter_population_pin_check.py` binds a stated population to its source
in two places — an emitted script's literal denominator against the sites that
increment the counter, and a test's pinned ratio against the emitter. Its measured
defect is a third repair added to a post-route block where the emitter moved to 3
and the test stayed at 2. This record's shape, executed. It does not reach a module
docstring, which is the text this record is about; the mechanism is now there to
copy rather than invent.

**(o)** yes. **(d)** yes — any docstring that quantifies a population it does not
name is the same claim waiting to expire.

### A-27 · a quoted population count must name the known instance its screen was validated against · `capture.emit`

**This lane's own apparatus is the evidence.** Twelve screens I wrote returned a
number I could not use:

    a prefix match pulled in every permission flag            34 for 9
    a verb matched a path three paragraphs away              560 for 0
    a no-argument probe measured the argument parser      18 of 19, worthless
    module-stem matching counted in-repo packages as
      third-party                                           216 for 51
    an exit code read after a pipe reported `tail`
    one matched a pattern literal inside a regex and reported a document
      that does not exist

**And three of the twelve failed to find the very case they were written for** —
a pattern held in a constant, a command spanning continuation lines, and a name
composed by a format string. A positive control would have caught each in one
run, and the control is free: the motivating defect is by construction a member
of the population.

A count has no expected value to compare against — the number *is* the answer, so
any number looks like one. And the direction that survives review is the low one:
a small tidy number reads as a well-scoped rule.

Until now these warnings sat in five records under five different headings, so a
reader of any one saw only their local instance. **This record is the class**, and
it is enforceable where the others are advice: the emitter can refuse a record
that quotes a count without naming the control.
**(o)** yes — it is the rule I most needed and did not have.
**(d)** yes — every future batch quotes counts, and none of them will have an
expected value either.

### A-28 · a verdict token read from an artefact must be matched against a closed enum · `ppa.record_provenance`

**Found by re-reading the state tables as a reader.** F-17's row said its rule was
*"folded into A-1"*. A-1 is the gate-proof-vocabulary rule; F-17's stated rule is
that a verdict token must be matched against a closed enum. **Different things**,
and the second had no record and no general program — one correct implementation
at a single site, and nothing else.

    comparisons of a verdict against a single literal value   232
    comparisons against a set                                 119
    files comparing to a value and NEVER to a set             115

**The 115 is an upper bound on candidates, not a defect count** — comparing to
one value is right wherever the question really is binary, and no static screen
separates that from a reader whose `else` branch swallows an unknown token. The
record says so, and says the per-site judgement is whether that branch would be
wrong for a token the writer has not invented yet.

The tree contains one correct instance to copy: a reliability screen that maps
anything outside its three known tokens to not-measured, **quoting what it saw** —
which is what makes a growing vocabulary visible instead of silently reclassified.
**(o)** yes. **(d)** yes — it is per artefact type per reader.

### A-30 · a guard for a declared value must not accept a value its own consumer defaults · `repo.test_population`

The only rule here found by **breaking the product on purpose** rather than by
reading it. The backend seam requires every backend to be drivable or to raise
with a reason of at least forty characters, and a census asserts exactly that.
The loader supplies a generic reason whenever a module declares none:

    getattr(mod, NO_DRIVER_ATTR, None)
      or (f"`_ppa/backends/{tool}.py` declares no {DRIVER_ATTR}() and no "
          f"{NO_DRIVER_ATTR}, so nothing here can say what it reads")

That fallback is far longer than forty characters, so the predicate holds for
every backend regardless of what any of them declares.

    delete the whole reason from one backend, file re-parsed to confirm
      it still compiles                              -> 0 failed, 0 errors

**Three mutations were needed, and the two failures are part of the rule.**
Renaming the shared constant proved nothing, because the test and the code read
the same symbol and stayed consistent with each other. Deleting a single line of
a multi-line assignment produced invalid Python, and its green result was an
artefact of the broken file rather than a property of the guard. Only removing
the entire assignment, with the mutated source re-parsed, is evidence — which is
the general lesson that a mutation must be shown to be a VALID program before its
green result means anything.

**(o)** yes — it is the guard for F-2, and F-2 is the finding it fails to protect.
**(d)** yes, and deliberately stated over the semantics rather than the syntax:
the narrow form here is one raise site, but the same defeat arrives from a
dataclass default, a `dict.get` fallback, or an attribute inherited from a base
class, and the predicate — can the reading side produce this value with the
declaration absent — covers all of them.

---

### A-31 · an emitted code skeleton must take the inputs its own step has · `capture.emit`

Found by reading the sketches as the implementer who receives them, which is the
one artefact class every other check in this report treats as opaque. Check 43
confirms they are valid Python. They are, and the signature is wrong anyway:

    def rule_gate_proof_vocabulary_has_a_producer(sample_text, ports):

for a rule whose entire content is a set difference between two name registries.
It receives no RTL source and no port list, and the pre-merge comment above it
demands a corpus sweep against an RTL-benchmark scorer that cannot sweep a
registry comparison.

Both strings are hard-coded in the emitter, so the reach is every capture, not
this one:

    emitted rule functions taking `sample_text, ports`
      this lane                                        29 of 29
      the chip lane                                    13 of 13
      the matrix lane                                  10 of 10
                                                       ---------
                                                       52 of 52

Those three lanes cover phase-1 fact extraction, phase-2 final audit, phase-3
DRC, IR-drop and post-route repair, and this layer's measurement seams. **Not one
of those steps receives a sample text or a port list.** The prose in each sketch
is precise and the `def` line above it contradicts the prose — which is worse
than emitting no skeleton, because a specific wrong signature reads as
instruction rather than as boilerplate.

This is the **general-core / thin-adapter** principle the capture skill states in
its own text, violated by the capture tool: the emitter is the general layer, and
it emits one domain's adapter for everybody.

**(o)** yes — on every sketch this lane produced.
**(d)** yes, and it already has 23 instances outside this lane, in two sibling
lanes that ran the same night and were captured by different agents.

---

### A-32 · every identity a scheme declares must state what may not sit in it · `ppa.problem_identity`

From a request in a named source that this batch had not mined. Measured on the
document that declares the scheme:

    identities the scheme declares                      5
    carrying a bold rule for what may NOT sit in them   1
      (`analysis`, the one whose violation was found first)
    carrying none                                       4

The rule is not absent because nobody thought of it. It is written, in bold, one
identity over, in the same section — which is why the gap is invisible to a
reader who checks that the document addresses the question at all.

**The cost is concrete and it is why the request was made.** A cross-layer search
has to place the specification in `problem` and the rewritten design in
`implementation`. Because that membership rule is unstated, the obvious reading
of the document makes the integrity checker refuse every legitimate cross-layer
comparison — so the unwritten rule does not merely permit a mistake, it forbids
correct work.

**(o)** yes — it is the request, and the request exists because the omission bit.
**(d)** yes: the predicate is presence of a stated rule per declared identity, so
it covers the remaining three the moment anyone tries a run whose shape the
existing examples do not anticipate, which is exactly when it is needed.

---

### A-33 · an ingested input records who declared it · `phase3.reference_flow_ingest`

The last unmined request in the cross-layer source, and the evidence is in two
places that disagree.

    knobs the runner exposes on its command line            3   (all place-and-route)
    synthesis actuators it exposes                          0
    the only synthesis input it reads     a directory inside the design's input tree
    what its audit header names                             that path, and nothing else
    fields recording who authored that input                0   (9 candidates, all unrelated)

So a lever admitted as *changing no design* can only be turned by writing into
the design's own inputs — after which the runner's own audit line reports it as
the design's declaration.

**What makes this a rule rather than a complaint is what the search did about
it.** It compensated by hand: nine files staged, and the disclosure written into
the comment header of six of them. The first line of one reads that the strategy
is declared by the cross-layer search and *not by the design*. That is exactly
the right fact, recorded in the one place no consumer parses, by an author who
happened to be careful — and the next author is one omitted comment away from a
run that looks like the design asked for a synthesis strategy it never mentioned.

**(o)** yes — it is the request, and the request exists because the author had to
write the comment.
**(d)** yes: the predicate is a declarer per ingested input, so it covers every
ingest the runner performs, not the one directory this search happened to need.

---

### A-34 · a verdict reachable by exhaustion must say whether it exhausted · `phase2.rewrite_equivalence`

Two runs of one prover, which a search must respond to in opposite ways:

    converged, left a point open        3.8 s
    exhausted partway, ~33 steps      1795 s
    what the record says of each      a single unproven point
    the only discriminator             elapsed seconds, for the reader to interpret

One says *give it more time*; the other says *this needs a different relation*.
A caller that cannot tell them apart either spends the budget again or abandons a
case that was provable.

**What makes the omission legible rather than arguable** is that the program
already emits a depth for the OTHER half of its method — a bounded-refutation
depth — and emits nothing naming how far the induction reached or whether a
budget stopped it. The shape is available, in the same file, for the sibling
technique.

The source names the prize: the rewrite an agent is most likely to attempt —
changing a state encoding — is the one this relation proves least well. Whether
that whole family is reachable turns on being able to read exhaustion apart from
convergence.

**(o)** yes — on the pair above, which is where it was found.
**(d)** yes: the predicate is presence of a depth and an exhaustion flag on any
verdict a budget can cause, so it covers every prover in the layer that runs
under one, not this relation alone.

---

### A-35 · a figure that sums a subset must name the subset · `ppa.head_to_head`

This one corrects an assessment I made before testing it. I judged request 9 an
instance of the required-scope-key rule. It is not:

    required scope keys for the area figure         1   (the stage)
    scope keys the published records actually carry 5   (stage, tool, rounding,
                                                         bounding box, FILL)
    of those, naming the rest of the composition    0

So the required-key rule cannot reach it — the composition was never required —
and **the disclosure shape already exists for one component and is missing for
the others**. The record says whether fill is included and is silent on tap,
decap and logic.

Establishing what the figure actually contains took summing the process library
over the routed netlist and matching the tool to 0.2 µm². **That figure is the
objective of this search and of the published one it is compared against**, so
two aggregates of the same name and the same scope can cover different sets and
the comparison between them is arithmetic on unlike quantities.

**(o)** yes — on the objective metric of the search that raised it.
**(d)** yes: the predicate is a composition key wherever a producer sums a proper
subset, so it covers every such metric rather than the one whose contents somebody
took the trouble to derive.

---

### A-36 · a declared requirement must be satisfiable by correct practice · `ppa.feasibility`

The last of the unmined requests, and the smallest-looking one in the list.

    the per-axis view lookup            returns the caller's declaration verbatim
    satisfiability checks in the module 0, in any spelling

So a declaration demanding a slow, a typical **and** a fast view for *both* the
setup and the hold axis is accepted — and cannot be met. A flow signs setup at
the slow and typical views and hold at the typical and fast ones, which is
correct practice, so setup-at-fast and hold-at-slow never exist and the axis
reports no record forever. **The failure is silent and it points the expensive
way**: an axis with no record is indistinguishable from a run that never got
there.

**One piece has to be built before the check can exist.** Screened for a
declaration of which views the flow signs each axis at — by constant name and by
report text — and found none; the multi-corner reports name a setup and a hold
corner per report, not a producible set per axis. So the rule is two-part: the
flow declares what it produces per axis, and the evaluator refuses any per-axis
requirement that is not a subset of it.

The source that found it put the principle better than a rule name can: *the
strictest declaration a flow can satisfy is not the broadest one that can be
written down.*

**(o)** yes — on the declaration that produced the permanently unadjudicable axis.
**(d)** yes: a subset test over every per-axis declaration, so it covers any axis
and any view vocabulary the flow later gains.

---

*A cheaper detector, from the lane that made the decision.* Comparing a declared
view set against what the flow produces needs a second source that can itself go
stale. Most of these fail a test that needs neither:

| axis group | scope namespace | a global corner list demands… |
|---|---|---|
| setup, hold | signs off **across process corners** | corners it has — fine |
| DRC, LVS, antenna, IR, EM, equivalence | a **single measurement over one database**, no process corner at all | corners that do not exist — **permanently uncovered** |

The requirement is unsatisfiable **as a matter of type, not availability**. And
the tell is sharp: the only way a producer could satisfy it is to *fabricate*
the missing scopes. **A requirement whose sole route to satisfaction is
invention is malformed, not strict.** Check that direction first; fall back to
the flow comparison only for what survives it.

The shipped remedy is worth copying because it re-opens the question without
breaking anything: per-axis requirements fall back to the global list for any
axis they do not name, so a contract written before the field adjudicates
identically; an axis named with an **empty** list is undetermined rather than
trivially satisfied, since there is deliberately no spelling for *any view will
do*; a key naming no known axis is dropped rather than silently honoured; and
the resolved view set is published on **satisfied** axes too, so questioning a
requirement does not require first making the axis fail.

### A-37 · a refusal that names the obstacle also names the remedy · `ppa.cli_contract`

The last unmined item in the brief's sources, and the first clean sweep in this
lane whose screen survived its own control.

    refusal messages in the layer            23
    carrying an executable remedy             0

**The screen was validated before the figure was believed**, because a zero from
an unvalidated screen is the failure this report has recorded six times. It
detects 2 of 3 known remedy phrasings and rejects 2 of 2 messages that carry
none — so it under-detects by about a third, and the honest reading is *very
small*, not *provably zero*. It missed one of its own controls because my verb
list has no entry for "wrap".

**The cost is on record from the lane that paid it.** A contract builder refuses
an image reference given in tag form, for a good reason, and prints no hint. The
request that came out of it names the exact command that resolves the refusal and
says printing that command would have saved a cycle — which is a cycle spent
rediscovering something the program had already established.

**(o)** yes — on the refusal that produced the request.
**(d)** yes: the predicate is a remedy on any refusal whose accepted form is
derivable from what the program already checked, so it covers a flag the program
declares, a validator's own pattern, and a command whose output is the value the
refusal demanded.

---

### A-38 · a scope key the producer cannot establish is omitted, not emitted as null · `ppa.timing_scope`

Found by reading a lane record's **mutation-arms** section — material the coverage
note admitted it had skipped. Every party to this defect has already said it is
wrong:

    the interface document, in bold   a scope key present and null is WORSE
                                      than one that is absent
    the comparison gate               refuses on it by name
    a program's own comment           44 occurrences of that refusal, one field
    the timing module                 emits it anyway, at 3 call sites

And the corner it cannot establish is the **governing setup corner**, so the rows
most needed for a sign-off comparison are exactly the ones carrying the sentinel.

**The fix is already demonstrated one module over.** The power producer had this
same defect; the lane that repaired it left a mutation arm behind — revert the
fix so the keys are emitted as null rather than omitted, and a named test goes
red. The pattern to copy, the test shape to copy, and the sentence to cite all
exist. What is missing is the same edit in a sibling file.

*The request mapping had this as "partly A-2, from the producer side". Measuring
it showed otherwise: A-2 is about whether a required key is PRESENT; this is a
key that is present and null, which the interface calls worse than absent. The
mapping was an assessment and this is a measurement.*

**(o)** yes. **(d)** yes — the predicate is a null in any emitted scope, so it
covers every producer and every key, which is what makes it worth building rather
than editing the one module.

---

### A-39 · an unhandled exception may not exit with the code reserved for a finding · `ppa.cli_contract`

From a lane's own list of six defects it found and flagged as unmapped to any
finding number — a list this batch had credited that lane for three items from.

    measurement-layer entry points          20
    catching an unexpected exception         5
    letting one reach the interpreter       15

The interpreter exits 1 on an escaped exception, and the contract reserves 1 for
**a finding about the subject**. So a missing library, a permission error, or a
defect in the checker itself is reported as a defect in the thing being checked.

**The asymmetry is what makes it expensive**, and the lane that hit it said so: a
caller may skip the could-not-check code, but a finding **stops a sign-off** and
names something nobody can act on. Its own case was a contract checker that
guarded the ABSENCE of an optional library honestly and not the library being
present and too old — the attribute error escaped, the process exited 1, and a
missing library was indistinguishable from a broken contract.

The screen is an abstract-syntax walk for a broad handler at the entry point, and
it was validated both ways before the count was believed: it detects the one
program that lane fixed and does not detect one it left alone.

**(o)** yes. **(d)** yes — the predicate is a handler at the entry point, so it
covers every command the layer ships, and the shape to copy is in the 5 that
already have it.

---
### A-40 · an aggregate over exit codes combines by severity not by integer value · `benchmark.aggregate_verdict`

From the corpus lane's aggregation note: the flow's own reader maps exit code 2
to a vacuous pass and 1 to a fail, so **2 is the larger integer and the weaker
verdict**. Aggregating a corpus with a bare maximum therefore lets ADDING a
record SUBTRACT a refusal.

    call sites taking a maximum over an rc/verdict-named value   8
      passing an explicit severity key                           3
      integer maximum, but guarding the not-checked code         1
      integer maximum over a deliberate two-value space          1
      unguarded integer maximum                                  3

I did not stop at reading it. Built a two-run corpus and ran the gate:

| tree | per-run lines | exit |
|---|---|---|
| one run, manifest missing | `[FAIL] … no RUN_MANIFEST.json` | **1** |
| the same run **plus** one whose manifest is unreadable | `[FAIL] …` **twice** | **2** |

The added run is the only difference. Both lines still say FAIL; the process
says could-not-check. A consumer keying on the exit code sees the failing run
disappear.

The guarded site is the interesting one: it takes an integer maximum but carries
an explicit `if rc != NOT_CHECKED` clause. Someone hit this exact bug and
repaired **one call site instead of the class** — which is the whole reason this
lane exists.

Of the two unconfirmed sites, one takes its code from a loader that reports
unreadable input with the not-checked code (the confirmed shape), and the other
nests two integer maxima, an inner one whose result the outer then combines
again.

**(o)** yes — the confirmed call site has no severity key, so the rule fires on
it as written.
**(d)** yes — it keys on the SHAPE, a maximum over exit-code-valued operands
with no declared order, not on any of these three functions.

### A-41 · a gate writes its verdict to a path no producer owns · `flow.artefact_write_ownership`

From a flow comment left beside a hand-caught near-miss: *had the option ever
been honoured, the checker would have destroyed the measurement it was
auditing.* That sent me looking for the general case.

    gate output paths stated in the flow            138
      also written by a program                       9
        the gate invoking that same program        most — not a collision
        CONFIRMED overwrite of a producer's file      2

The two are confirmed in the **producer's own source**, not inferred. A runner
comment states that the gate-checkers run after the manifest-emitting step and
**overwrite two stamped lint artefacts with bare, identity-less payloads** — one
family collapsing to an empty list. Nothing fails: the gate exits zero, the file
exists and it parses. What is gone is the evidence, replaced by a document
saying the evidence was fine.

The repair that was applied is a caller-side sweep that re-stamps those two
directories **after** the audit has clobbered them. That repairs the damage; it
does not prevent the collision, and it covers the two directories somebody had
already noticed. **Three instances, three separate one-off responses, no rule.**

A methodology note, because it nearly cost me the finding. My first screen asked
whether a gate writes a path a *different step* declares. It returns **zero**,
and the zero is real — I injected a collision and the screen caught it. It is a
true answer to the wrong question: the confirmed collisions are **inside one
step**, because the same step declares the artefact and wires the gate that
overwrites it. A negative control proves a screen can see; it says nothing about
whether the screen is pointed at the defect.

**(o)** yes — the original is a literal path equality between a gate's stated
output and a producer's write.
**(d)** yes — it compares two generated sets and names no filename, so it fires
wherever the equality appears.

### A-42 · a generator over the tracked set refuses a tree that is not the one being published · `repo.generated_manifest`

A sibling lane left this as a parenthesis: *the inventory generator counts
TRACKED files, so it had to run after the commit — worth knowing.* Knowledge in
a report instead of a refusal in the program is the gap this batch exists to
close, so I went and looked.

The generator is careful in one direction and not the other:

| the enumeration query… | what the generator does |
|---|---|
| **cannot be answered** (no repo, no binary, timeout) | returns nothing, so a missing tool never reads as an empty repository |
| **answers about the previous commit** | accepted silently |

Run before committing, it emits a manifest of the tree *without* the work being
described, which is then committed alongside the very files it omits. Nothing in
the output says so.

**The denominator matters here and the obvious one is wrong.** 42 programs
consult the tracked-file query and 34 of them write something — but most are
CHECKERS, and a checker reading committed state is *supposed* to ignore a dirty
tree; that is the whole point of it. Flagging those would be the same error as
A-5's screen for the third time. The population is generators publishing a
manifest of the tracked set *as a tracked artefact*:

    such generators        3
      guarded              1
      unguarded            2   (one confirmed to have bitten a lane)

**(o)** yes — it would have refused instead of emitting a manifest missing the
new files.
**(d)** yes — it keys on the pairing of a tracked-set enumeration with a tracked
output, and names no generator.

### A-43 · an enforcement point named as the only one must be proven present · `repo.enforcement_point`

A sibling lane recorded that on its machine the pre-push hook **refuses every
push from an isolated working copy**, because the corpus it inspects is untracked
and therefore absent there. I have pushed from an isolated copy all batch and
was never refused, so I went to find out why.

    tracked hook       tools/git-hooks/pre-push     present, executable, 23743 bytes
    installed hook     .git/hooks/pre-push          ABSENT
    hooks directory    core.hooksPath               not configured

The hook does not run here. And the document that names it *the only
enforcement* records the other two rungs as already gone — automation disabled
at the account level, branch protection returning not-protected — so on this
machine **the number of enforcement points that actually execute is zero.**

Three tests reference the hook. All three locate the **tracked** copy and assert
on its text; **none asserts that it is installed.** Testing the script is not
testing that it runs, and a hook takes effect only from an untracked location
that every fresh clone starts without.

**This batch is the evidence that it is not theoretical.** Nine pushes were made
from an isolated copy during it and not one was gated. From my side a successful
push looked exactly like a push that had passed — which is this batch's own
central class, arriving in the first person.

So the enforcement point has two observable states, refuse-everything and
enforce-nothing, and which one a person gets is decided by an untracked file
nobody checks.

*What I did about my own pushes:* ran the gate the hook would have run, with the
documented pointer. `rc=0`, and it says why — *no evidence folders changed since
`origin/main`, nothing to enforce*, which is correct for a branch that touches
none.

**(o)** yes — the installed path is absent, so the check fails where it stands.
**(d)** yes — it compares a resolved hook path against a tracked source and
names no particular hook.

### A-44 · a search result consumed as if unique must prove it is unique · `repo.unique_lookup`

From the corpus lane's third decision, which names the move in one line: *taking
the first record is what destroys this. A gate that needs* the *contract and
finds two has not found the contract — it has found a disagreement.*

    sites reducing a search to one result                14
      first of an explicitly SORTED glob                  8   deterministic, plausibly deliberate — not claimed
      first hit of an UNSORTED walk                       4   the filesystem decides the verdict
      index [0] straight off a glob                       2   one of which is a docstring, see below

**The 4 are oversights, and that is measured rather than assumed.** The *same*
glob expression over the same plugin directory appears **sorted in one program
and unsorted in another** — so at least one of the two was not chosen.

One of the remaining two is not code. It is a docstring recording the repair of
this exact defect, and it states the casualty:

> An earlier revision fell back to `project.glob("**/sim_professional/<name>")`
> and took `hits[0]`, which let a **NESTED snapshot's bundle certify the OUTER
> project**.

The remedy also already exists, at corpus scale, and should be copied rather
than redesigned: a shared helper keys records by identity across five gates,
refuses two claimants whose content differs by naming **both paths and both
digests**, and prints byte-identical duplicates as a note instead of dropping
them — because a population whose size depends on how many times somebody
copied a file is its own defect.

So the class has a working implementation, a documented casualty, and four live
sites, and **nothing connects them.**

**(o)** yes — the original reduced a multi-match walk to its first element.
**(d)** yes — it keys on reducing a search to one result without a count, and
names no lookup.

### A-45 · an alternative proof admits nothing the proof it stands in for would refuse · `ppa.proof_group_equivalence`

The feasibility lane admitted a second way to prove the timing axes and refused
to call it a relaxation on trust:

    wns = min(0, worst_slack)   =>   wns >= 0  <=>  worst_slack >= 0

Same predicate, so it admits no candidate the original would refuse — argued in
a comment that also states what the substitution may **not** do (rescue a view
nobody analysed) and names the test that sweeps the range *"rather than trusting
this comment"*. That is the model. It is also, measured across the layer, the
**only** one:

    axes declared                                        10
      admitting more than one proof group                 6
        whose groups MIX predicate kinds                  5
      equivalence arguments anywhere in the layer         1   ← covers the one pair that does NOT mix

The mixed pairs are a zero-count beside a non-negative-slack (twice), a
verdict-membership beside a zero-count, and a zero-count beside a
magnitude-under-limit (twice). A count is zero against a threshold **the tool
chose**; a magnitude is under a limit **the contract states**. Those agree only
when the thresholds do, and nobody has said they do.

**The aggregation makes it reachable, and I read it rather than assuming it:**

    VIOLATED in any group   ->  VIOLATED      a violation cannot be outvoted — safe
    SATISFIED in any group  ->  SATISFIED     beats UNDETERMINED — this is the widening

So the group that happens to carry data on a given run decides the verdict, on
its own predicate, and the output does not record which group did it. An axis
proven the strong way and the same axis proven the weak way are indistinguishable
afterwards.

**(o)** yes — five axes declare mixed-kind groups today with no stated equivalence.
**(d)** yes — it keys on alternatives under one subject with differing predicates
and no licence, and names no axis.

### A-46 · a verdict artefact records the tree it was measured on · `repo.verdict_provenance`

A lane was handed a brief saying a named gate would go FAIL → PASS. **It did
not, on the tree the lane had.** The brief was not wrong:

| gate | the lane's base | the brief's tree |
|---|---|---|
| the wiring audit | rc 1, **7** names — the lane's line removes one, leaving 6 | rc 0 — because six wiring lines were already there |

Those six had not landed. Establishing *that* took grepping **every reachable
remote reference** for them and finding zero hits; testing the claim at all then
took adding the six in a scratch tree, re-measuring, and reverting. **A stamp on
the original verdict would have replaced all of it with a comparison of two
identifiers.**

Without the stamp, two runs disagreeing is indistinguishable from two *trees*
disagreeing, and the reader who inherits the quote cannot tell a false claim
from a true claim about a state they do not have.

    programs emitting a JSON artefact                      650
      referencing a commit identity at all         at most   36

**The screen is loose on purpose, and in the safe direction.** It matches the
word anywhere in the file, including uses that never reach the artefact — so 36
is a *ceiling* and the real figure is lower. A rarity claim measured by a screen
biased toward *finding* the property is safe; the same screen used to argue the
gap is small would not be. That asymmetry is the one thing this batch has
learned to check before quoting a number.

**(o)** yes — that artefact named no tree.
**(d)** yes — it keys on an emitted verdict with no recorded subject identity,
and names no gate.


### C-1 · A generated report header must be derived from the inputs the session actually opened · `phase3.sta`

> **why_not_bucket_a**: A program can decide this and the predicate is trivial —
> compare the claim against the input list — but no emitter records the inputs it
> opened, so today the check has nothing to read. The work is the provenance
> plumbing across every emitter, not the predicate.

The technique is known to work: one emitter now derives every self-describing
line from what it linked, and stamps what it ACTUALLY opened when it degrades.
It is applied in one place out of many.
**(o)** yes — the header said post-route and the session linked pre-route, which
its own input list would have contradicted.
**(d)** yes — the predicate is "is this claim entailed by the input list", which
is indifferent to what the claim is about; it covers a corner, a basis, a
liberty, or an activity model equally.

### T-1 · Post-route design-rule repair faults on a netlist shape after routing completes · `phase3.pnr_setup_repair` · OpenROAD

> **why_not_bucket_a**: The fault is inside the forked tool's post-route repair
> stage; the flow's classification and resume path already behave correctly — they
> name the crash, distinguish it from a routing failure, and re-run the tail with
> the faulting pass omitted. Any further plugin-side rule could only widen that
> workaround, and on two arms the resume already consumed the whole trial budget.

10 of 10 arms carrying a non-redundant accumulator crash; 0 of 52 arms that
preserve the state encoding do. Signal 11, exit 139, AFTER the router printed its
own completion line. Bad samples committed at
`ppa-crosslayer/records/trials/{x03,x04,x11,x12,x13,y03,y04,y08,z24,z25}/`;
golden at `ppa-crosslayer/records/trials/c02/`, same build, same PDK, same script.
**The samples do not carry the crash, and that is A-15 happening here.** Checked
rather than assumed: all eleven directories are tracked, but each bad one holds
only `objective.json`, `records.json` and `run.json` — no log, no report, no
error file — and every one records `runner_rc: 1`, not the 139 cited above. **The
golden records `runner_rc: 1` too**, so on the only status field the committed
artefacts carry, the ten crashing arms are indistinguishable from the passing
one. The signal and the exit code come from the originating lane's session
output, which was never committed. So this record cannot be filed upstream as it
stands: a maintainer receiving these ten directories can reproduce nothing. What
the tree DOES support is the correlation — 10 of 10 arms with a non-redundant
accumulator fail, 0 of 52 preserving arms do — which is a netlist property and is
the lead worth having.

*And the family's loss is larger than the crash count, which changes how urgent
this is.* The affected family holds **18** arms. **10** hit the fault. A further
**2** produced no number because the resume path — the mitigation, working as
designed — consumed the remainder of their hour-long trial budget. So the real
loss is **12 of 18**, and two of those twelve are attributable to the RECOVERY
rather than to the crash. A fix that merely let the repair pass skip the
offending instance quickly would recover those two on top of the ten, and the
current mitigation cannot be left standing as the answer. Nothing was done to
make any of the twelve pass: no repair step disabled by hand, no budget raised
for them, no routed database patched.

**(o)** yes — the samples ARE the original, retained.
**(d)** the enhancement is stated as a behaviour, not as a patch to these ten
inputs: the stage must exit non-zero with a named diagnostic on any instance it
cannot repair, so a different netlist shape that reaches the same fault is
covered by the same acceptance criterion.

---

### A-29 · an emitted bundle must be written to the declared location · `capture.emit`

This one was measured by somebody else, about me, before I noticed it.

The emitter takes `--out-dir` as a free string and validates nothing about it.
The layout consumers rely on — `docs/capture/<YYYY-MM-DD>-<agent>/` — lives in
prose. The commit that established it, `506ff68c1`, records the population:

    lanes emitting this artefact class on one night : 4
    lanes that chose the declared home              : 1
    lanes repaired by hand with git mv              : 3   <-- this one among them

plus a fifth lane that wrote a bare `RESULT.md` at the repo root, a name three
lanes wrote the same night, so it could not belong to any bundle and was removed
from the tree entirely. Every producer was self-consistent. Not one of them was
checked, because `grep -rl docs/capture programs/` returns nothing: no program
knows the layout exists.

What makes it worth a record rather than an apology is how it was found. Not
from the tree — the branch had been measured against a base 30 commits stale, so
the relocation was invisible from inside it. It surfaced because `git merge`
reported a *rename*, which is the only reason this bundle now updates the landed
one instead of shipping a second copy of itself at a path that had already been
ruled not to land.

**A second clause, and this bundle violates it.** A bundle has an identity as
well as a location:

    directory name declares          2026-08-21
    its own summary.json declares    2026-08-22
    its backlog ids declare          20260822
    the two sibling bundles          self-consistent, both 2026-08-21

The batch was re-emitted after midnight, and the emitter derives its date from
one instant at run time — which is right, since a record filed today should say
today. **Nothing anywhere would have reported the disagreement.** It is
deliberately not repaired by renaming the directory: that abandons the path this
bundle already occupies on the landing branch and creates a second copy, which is
this record's *first* clause failing. So it is declared instead, here and in the
record, and check 45 requires exactly that — the dates agree, or the discrepancy
is stated with both of them.

**(o)** yes — it would have refused this lane's own first emit, which is exactly
the event that produced the record.
**(d)** yes, and it already has three other instances: the two sibling lanes that
picked their own directories and the one that wrote the colliding root file. The
predicate is a path comparison against a declared constant, so any future
artefact class that declares its layout is covered by the same check.

---

## One change outside the capture bundle

`benchmark/CAPTURE_ROUTING.json` gains **3** steps. Without them **3 of the
47 records** here emit UNROUTED — the ones routed at those nine — and the
emitter's own warning says to add the entry. The other 24 route against entries
main already carries, because half of the steps this lane wrote landed with the
earlier snapshot. *These two figures have now moved twice, each time because a
record was added at a step main does not carry; they are derived from the two
routing files rather than maintained by hand, and the derivation is one command.*

*Three, not the eighteen this sentence said an hour ago, and the difference is not an edit here.* Fifteen of those steps **landed with the frozen bundle**, so relative to the point this branch left they are no longer additions. The figure is derived against the MERGE-BASE rather than against main's tip — comparing to the tip answers *how does my tree differ from main today*, which on the day this was written meant 503 commits of main's work and 131 plugin files this branch never touched.

*This read "every record here" until the universal claims in this report were
audited against their denominators. It was true when written — all sixteen steps
were new then and every record did depend on them — and the merge turned it into
a threefold overstatement, sitting in the paragraph that justifies the one plugin
file this branch touches. A reader deciding whether to accept that file is
exactly the reader it would have misled.*

    ppa.feasibility           programs/ppa_feasibility_check.py
    ppa.head_to_head          programs/ppa_head_to_head_check.py
    ppa.search                programs/ppa_search_run.py
    ppa.artefact_write        programs/_atomic_artefact.py
    capture.emit              programs/enhancement_emit.py
    capture.backlog_sanitize  programs/backlog_sanitize_check.py
    repo.host_independence    programs/gate_host_independence_check.py
    repo.test_population      programs/plugin_change_pytest_gate.py

**The last four are a correction to my own first pass.** Five records had been
routed to one program because it was the nearest listed step, which piled rules
belonging to three different files into one sketch — precisely the mis-delivery
the implementing lane would pay for. Each now sits with the program that owns
it, and the sketches land in eight files instead of five.

Two of those five have no ideal home and the records say so rather than pretend:
**no program in this tree audits a test suite's own population arithmetic.** The
meta-gate family that audits the *program* population — for wiring, for a
disclosed denominator, for host-independence — is where the *test* population
rule belongs, and both records name that as the target and the current routing
as a placeholder.

`tests/test_capture_routing_consistency.py` and `tests/test_enhancement_emit.py`
pass (69 passed, 4 skipped), as does
`tests/test_issue1130_wiring_population_parity.py` (7 passed).

*That last figure read `18 passed` until it was re-run on the merged tree. The
file is byte-identical between this lane's base and main and defines six test
functions, so it cannot have produced eighteen from the command it is quoted
against — the number came from a wider invocation and was written down beside
the narrower one. It is the only quoted figure in this report that did not
reproduce, and `verify.py --slow` now re-runs both commands and compares them to
the text, so the next one cannot go stale unnoticed.*

*That check then caught something about itself. On one run it reported `ran 5
passed, report says 7` — and the pytest summary it had read actually said **"2
failed, 5 passed"**. The check matched `(\d+) passed` and nothing else, so a RED
run reached me as a smaller green number, with no mention that anything failed.
That is the defect this whole cluster is about, committed inside the tool written
to police it. It now reads failures explicitly and reports them.*

*The underlying run is also flaky, which is the second half. That file runs gates
over the whole repository, takes about ninety seconds, and failed once in three
consecutive invocations of the identical command — the two failures being a
clean-run denominator assertion, the shape that loses to contention. So the check
re-runs once and requires the disagreement twice before calling a figure stale. A
single red from a ninety-second repository-wide gate is not evidence; treating it
as evidence manufactures a confident false verdict.*

*How this was found, and what else the same sweep says.* Every claim of absence
in this report was enumerated and split by whether anything backs it:

    paragraphs asserting that something does not exist        117
    carrying no figure, artefact or measurement themselves     31
    still unbacked once the neighbouring blocks are read        0
    genuinely measured by nothing at all                        1   <-- below

The 31 are argument whose evidence sits in the block above or below them, and
that was **checked rather than assumed** — an earlier version of this paragraph
said so on my judgement alone, which is the habit this whole sweep exists to
catch. The one that survived is the sentence that follows.

No gate is implemented. No version bumped. No baseline written. Nothing pushed
to main. **Measured, not asserted** — that sentence stated four things and
nothing checked any of them, which made the four claims a landing reviewer most
needs to trust the four he had only my word for. Check 47 now derives all four
from the base: no changed version line in either manifest, no baseline file in
the diff, no `.py` added anywhere under the plugin tree, and `HEAD` not an
ancestor of `main`. It is shown able to fail — run against a base across which
main itself added programs, the same predicate reports 12 added files and 6
changed version lines.

## Where each record came from

| source named in the brief | records it produced |
|---|---|
| `ppa-e2e/FINDINGS.md` F-1..F-18 | A-1, A-2, A-6, A-7, A-8, C-1 — and eleven ALREADY-PROGRAM |
| `ppa-e2e/RESULT.md` (13 requests) | folded into the above. Paid on this tree: **1, 2, 4, 5, 6, 8, 10, 11, 12**. Partly paid: **3** (8 of 9 axes gained a producer), **9** (three of four scope keys), **13** (host paths yes, the reliability count and the relative output path no). **7** was answered with a DIFFERENT fix than the one requested — the source artefact was not put in the scope; instead the index learned to tell corroboration from conflict, which settles the fatal half and leaves two genuinely disagreeing artefacts refused, on purpose |
| `ppa-crosslayer/RESULT.md` (10 requests) | T-1; and it is the evidence that F-3 went 0 → 6 axes and that `drv` is the one left. **Its ten requests were never mapped the way the other source's thirteen were — that table is below, and five of the ten are unmined** |
| `jrc_ppa-layer-rc-contract` | A-3, A-4 |
| `jcorpus_ppa-corpus-mode` | A-5, A-11 |
| `agent_jppa-tests` | **C-2** (first written as a Bucket-A rule, demoted by its own sweep), **A-22**, and the fourth-instance measurement under A-3 |
| `agent_jppafeas-feasibility-producers` | A-1, A-2 |
| `jrecords_record-shape-reconcile` | the producer-census instance under A-3 |
| `jreq_lander-three` | its three requests are landed. **"Nothing left to distil" was wrong** — re-read after the coverage of every named source was questioned rather than assumed. Its environment note carries the measurement behind **C-2** (33 of 46 shipped test files in this layer failing from one too-old dependency) and names the shared helper that already handles that case for three files, which C-2 now cites so the implementing lane builds on it |
| using the emitter this brief mandates | A-9, A-10 |
| the brief's own line that the ASYMMETRY is the richest material | **A-13** — the one I had read and not acted on |

## The one thing I could not settle — now settled, and it did not go where I expected

**F-16 is NOT a forked-tool defect, and the record that would have sent it to the
wrong repository was never written.**

For most of this lane I left it open on the honest ground that I could not tell a
tool defect from an invocation gap. Working out *why* I could not tell is what
settled it:

* the consuming gate is a substance check over a produced document — **it never
  runs the tool**, so its finding text names a cause it cannot observe;
* the producing step, which does run the tool, **retains nothing from it** — no
  exit status, no output tail.

So two layers assert that the tool failed and neither saw the tool. That is why
the attribution was unfalsifiable, and it is a defect in its own right — **A-15**.

The tree then answers the question the record could not. The runner's own helper
documents this exact abort: physical-only cells present in the routed netlist and
absent from the timing library stop the tool before the comparison begins, and
the helper calls that a **false** tool-error, fixing it by emitting blackbox
stubs. The failure class is **the step's own setup**, not the tool.

Two lessons worth separating. Not filing the Bucket-T record was right — the
evidence for the tool was never there. But "I cannot attribute this" was not the
end of the enquiry: the reason I could not attribute it was itself the finding,
and the answer was in the tree the whole time.

## What remains open

**One item, and it is not mine to close.** The skill binds every Bucket-T record
to the forked-tool roadmap at `benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md`, and
`benchmark-data/` is a separate repository. T-1 carries its full attribution
block in the emitted backlog; whoever lands it must add the roadmap entry there,
or the instruction should be repointed.

## The "could not settle" seam, read out and closed

Four records came from the lanes' own *what I could not settle* sections
(**A-20**, **A-21**, **A-22**, **A-23**) — a lane stopping honestly at its scope
boundary and writing down what it saw, material that never reaches `FINDINGS.md`
because it was not that lane's finding.

**The last section of that seam produced no record, and that is the correct
outcome.** A lane reported two commands answering rc=0 to what looked like an
empty input, and declined to call either a defect. Checking its reasoning: all
**15** declared vacuous invocations correctly name a required argument of their
own program, so where the declared table reaches, an invented arm is impossible.
The one false reading on record was taken against a program **outside** the
table — an empty directory handed to a command whose real input is a document.

So it is not a new rule; it is **harm evidence for A-3 and A-4**, and the sharper
form of both: a member outside the declared population does not sit un-examined,
it gets examined by an improvised arm and yields a confident wrong answer. Both
records now carry it.

## Input coverage — every named source now read

The status checks in this lane were answered twice by an internal audit that
compares records to each other, and twice it reported CLEAN while primary
sources were still unread. **A consistency audit measures coherence, never
coverage of the input.** So the last passes audited the input instead:

| source | state |
|---|---|
| `ppa-e2e/FINDINGS.md` | read in full — all 18 |
| `ppa-e2e/RESULT.md` | read in full, including §1–7 |
| `ppa-e2e/METHOD.md` | read in full |
| `ppa-crosslayer/RESULT.md` | read: §5–§10 and the requests — **and §1–§2 late.** §2 is the control the brief named; §1 yielded `A-16`'s second clause. Between them: the seventeenth ALREADY-PROGRAM, the correction to `A-15`'s remedy, and a disclosure the published search space does not make. The coverage note above was accurate about what had been read and silent about the brief having asked for more |
| six lane records | read: findings, *what I could not settle*, and every REQUESTS/HANDOFF section |

The last section produced **no new record, and that is the correct outcome.** It
reported two commands of one layer disagreeing on what a readable-but-empty input
should return, and said the lane could not establish which answer was the
layer's. Measured here:

    readme extractor,  read-but-empty     rc=0
    metric extract,    read-but-empty     rc=2
    the layer's own present-but-empty test asserts   rc=2, three times

**The layer does have an answer.** The lane could not see it because the answer
lives in a test whose population is the filename prefix, and the command
returning 0 is one of the executables that prefix misses. So the boundary does
not merely leave members unchecked — **it hides the settled answer from the
people who own them.** That is folded into **A-3** and **A-4** as their third
measured instance rather than a twenty-ninth record.

## Landing readiness — measured base against head, not asserted

A question I had never asked of my own branch: **would it land?** Three gates
could plausibly care about a capture bundle and the routing entries beside it.
All three were run on this branch AND with the routing file reverted, then the
outputs compared.

*Re-measured after the merge, because the shape of the change moved: the bundle
is no longer a new top-level directory — it now updates one that main already
carries — and of the 16 routing entries this lane wrote, 8 had already landed
with the earlier snapshot, so only 8 are new against main. Main has not moved
since (still `81cd5321b`), a trial merge is conflict-free, and no file this
branch touches is one main touched.*

| gate | base | head | comparison |
|---|---|---|---|
| tracked JSON/YAML parses | — | **rc 0** | clean on this branch |
| gate is wired | **rc 0**, unwired 58 (baseline 59) | **rc 0**, unwired 58 | **output byte-identical** — re-run on both arms after each of the two merges; it was rc 1 / 61 at the start of this lane and main has since wired three, so this gate is now GREEN on both |
| checker execution wiring | rc 1 | rc 1 | **output byte-identical** |

One of the two red gates **went green while this branch was open** — main wired
three programs and the wiring gate now passes on both arms. The other is
pre-existing on main and this branch moves neither: not the count, not the names,
not a byte of the report. The routing entries
wire nothing that was unwired, which is consistent with **A-23**: every program
this batch routes to was already reachable from an automatic verdict.

Stated as a comparison rather than a verdict on purpose. A gate that is red on
the base cannot answer *"did this change make it worse"* by its exit code — only
the diff of its output can, which is the same rule this batch records twice
over.

**And the comparison's own instrument was separation-tested**, because three
byte-identical outputs are equally consistent with *"my change has no effect"*
and with *"this gate prints the same thing regardless"*. Pointed at a different
root the gate returns `rc 2` and `[CANNOT DETERMINE]` instead of its census — so
it is not a constant.

That establishes sensitivity to the root, not to the routing table specifically,
and the honest claim needs the second half: **the identical output has a
mechanism, not just an observation.** The gate counts a program as wired when it
is reachable from the flow document, the routing table, a runner or the CI
scripts — and **A-23** independently measured that every program this batch
routes to was *already* reachable by one of the other paths. So the entries
could not have changed the census, and two unrelated measurements agree on why.
That agreement is the evidence; the byte-identity alone would not have been.

**One honest note on how this was measured.** Comparing required temporarily
reverting the routing file, running, and restoring it. The first attempt timed
out mid-sequence, and I verified the restore had completed before continuing
rather than assuming it — the working tree and `HEAD` agree at 54 steps. The
third gate then needed a longer budget than the first attempt allowed; its
result here is a completed run, not an inference from a partial one.

## Buildability — the deliverable's stated purpose, checked

The brief's reason for these records is that a separate lane implements them and
*"needs your `pattern` and `fix_action` to be precise enough to build from."* I
had never checked that systematically. The rubric: a buildable `fix_action` names
a **predicate** (what to compute), a **population** (what to compute it over) and
a **refusal** (what to do on a hit).

    Bucket-A records                          44     (26 when the rubric was applied)
    shortest fix_action                       > 300 characters
    genuinely missing a rubric element         0

**What the rubric check does NOT prove, tested rather than assumed.** The three
patterns match concepts, not literal words, and that is right — but it makes them
permissive. Fed four strings deliberately:

    a genuinely buildable instruction              passes
    "should be checked across all the relevant
      cases and reported when it fails"            passes  <-- pure vagueness
    a narrative sentence with no instruction       fails
    "it needs fixing"                              fails

So the check separates an instruction from narrative and from emptiness, and it
**cannot separate a specific instruction from a plausible-sounding one**. The
figure it produces is therefore a floor on form, not evidence of precision, and
this report should not be read as claiming otherwise.

What does carry that weight is different and is elsewhere: the nine sweeps, each
of which changed what its rule tells a builder; the records that name a file and
a line rather than a description; and the shortest `fix_action` in the batch
running to 872 characters of measured specifics. Those are checkable by reading
one record, which is the honest instrument here.

*A screen written to re-check the rubric across the nine records added since it
was first applied reported 22 of 35 missing an element. It required the literal
words where the verifier matches the concepts — the seventh time in this lane a
screen of mine measured my vocabulary, and the first time it did so against my
own verifier, which was right.*

**Routing aptness, checked separately from routing existence.** The verifier
confirms each record's routed program EXISTS; it cannot confirm the routed
program is the right one, and a misroute sends the implementing lane to the wrong
file. Screened by asking which programs each `fix_action` names and whether the
routed one is among them:

    Bucket-A records naming any program at all           29
    naming a program OTHER than the routed one            3
    of those, a genuine misroute                          0

All three name a gate that landed on `main` during this branch and is offered as
a starting point — *build on this file* — rather than as the owner of the fix.
The screen over-matches by construction, since it cannot tell a routing target
from a reference, so the three were read rather than counted.

**And the buildability check itself is A-27's worked example, twice over.** The first run
reported **14 of 26 missing a refusal** — because the pattern `\brefus\b`
cannot match the word *refuse*, the `\b` falling between `s` and `e`. A-27 says
to validate a screen against a known instance before quoting its number; doing
that failed the control immediately and the real figure was **2, not 14** — a
sevenfold inflation, in the direction that would have sent me rewriting a dozen
sound records.

Reading the surviving 2 cleared both: *"apply them to every field the validator
constrains"* and *"collect the document-type identifiers producers stamp"* are a
predicate and a population, in words my list did not happen to contain. So the
answer is **zero**, and it took a control plus a read to get there rather than
one regex.

**Re-validated afterwards against A-27's tightened bar.** The control I used
here was positive-only — a known-good record scoring three of three — which is
the same shape as the self-against-self control that let a broken instrument
publish a number two sections down. So the rubric was re-run against four
deliberately-failing inputs:

    empty fix_action            flagged, all three missing
    vague prose, no mechanism   flagged, all three missing
    predicate only              flagged, population + refusal missing
    predicate + population,
      no refusal stated         flagged, refusal missing

All four are caught, including the subtle last one. **The instrument separates,
so the zero is a result.** Checking this was not optional once A-27 changed: a
rule tightened and not applied backwards to the author's own earlier claims is
advice, which is the thing this whole batch exists to stop producing.

## No near-duplicates — and the first number I published from a broken instrument

The brief warns that *"a fabricated near-duplicate is worse"* than a missing
record. The emitter enforces that only for the buckets that write a backlog, so
the patterns were unchecked by anything. Over **all 47 records**:

    pairs compared                      1081
    maximum similarity                 0.41
    pairs above 0.40                      0

**Controls, all three separating:** a record against itself **1.000**, a
deliberately near-duplicated pattern **0.966**, an unrelated pair **0.144**. The
0.38 maximum sits far below the near-duplicate signal, so the conclusion stands:
no two records restate one class.

**The first version of this section was wrong, and how it went wrong matters
more than the correction.** I reported 0.07 over 325 pairs. The similarity
matcher applies a heuristic that discards frequent characters on inputs above a
few hundred characters, and it is disabled by a constructor argument — I set the
attribute *after* construction, where it does nothing. Every score in that run
was produced by a matcher that could not see similarity.

I did run controls. **They could not fail.** Self-against-self returns 1.00 even
on a broken matcher, because identity survives any heuristic; and the
near-duplicate control went through the same broken call path, so it inherited
the defect it was meant to detect. A control executed with the fault it is
testing for is decoration.

That is the fourteenth apparatus error of this lane and **the first to reach a
committed artefact** — which is exactly what **A-27** exists to prevent, and it
happened anyway because the rule as written asks for a control and not for the
one property that makes a control real: **it must demonstrate SEPARATION.** A-27
now says so.

## The ALREADY-PROGRAM claims — can the guards they name actually fail?

Sixteen findings produced no record because a program already enforces the class.
Each was verified by reading that program. But an ALREADY-PROGRAM entry asserts
**coverage**, and unverified coverage is the subject of three records in this
batch — so the claims owe the same separation test as everything else: *can the
named guard fail?*

    files backing the claims, checked         9
    carrying tests whose names indicate a
      negative arm                            all 9, between 1 and 10 each
    read directly to confirm the name means
      what it says                            1

**The name count is a screen and is labelled as one** — a test called
`…is_never_withheld` might assert a positive. So one was read in full, the
negative arm of the census backing two of the three findings the brief singles
out. It reconstructs the pre-fix declaration, asserts the consumer refuses it by
code, and its own docstring states the stake: *"If `unit_suffix_of` stopped
firing, the census above would pass over a tree where every unit was wrong."*

**The follow-up this section first deferred has since been done.** Rather than
leave it named, the negative arms were inspected at BODY level across all nine
files:

    tests named as a negative arm                             36
    whose body matches a failure-assertion pattern            26
    of the 10 unmatched, read in full                          2 — both genuine

Both survivors read as real: one asserts that the self-audit returns a non-empty
finding list for an empty lever set, the other constructs a check stating nothing
and asserts the verdict is not-checked. **So the body regex under-counts**, and
the defensible statement is that 36 negative arms are named, 26 are confirmed
mechanically, and every one inspected by hand — three across this lane — is
genuine.

Not "sixteen verified guards", and not a bare name count either. The claims are
demonstrably not resting on tests that assert only the happy path, and the
residual is a regex's blind spot rather than a doubt about the guards.

**A correction to what follows, found late and by reading a section this report
admitted skipping.** The originating lanes had already done this. One of the six
lane records carries a table of ten mutation arms — *"a guard that cannot go red
is not a guard"* — and its arms 1, 2, 4 and 5 are the same mutations run below
for F-5, F-4, F-9 and F-10, against the same tests, with the same result. Another
carries fifteen arms with a control this report only adopted later: every row
verified green-BEFORE as well as green-after, so a test already failing cannot be
mistaken for a working arm.

So the execution evidence below is **a re-confirmation on a tree 244 commits
later, not a first demonstration**. That is worth having — a mutation arm from a
past lane can rot, and these did not — but it is a different claim from the one
the next paragraph originally made, and the difference is exactly the kind this
report spends its length insisting on.

**And then the question was answered by EXECUTION rather than by inspection**,
for the three findings the brief singles out. Everything above reads code; a
named negative arm can still be vacuous, so each guard was made to fail by
breaking the product it protects, one line at a time:

    F-4  a carrier declaration changed to the wrong envelope
         -> 1 failed  test_the_three_shipped_producers_write_documents_the_consumer_READS
    F-5  an area metric named `…_um2` declared with unit `count`
         -> 2 failed  test_no_declared_unit_contradicts_its_metric_name
    F-9  the value comparison collapsed so a conflict reads as corroboration
         -> 5 failed  test_the_SAME_bytes_giving_TWO_values_is_a_parser_defect

Baseline before each: 13 passed. **Each failure NAMES the class it is supposed to
catch** — which is the part that matters, because a guard can go red and be
uninformative, and a red that names something else is not coverage of this class.
Each mutation was reverted immediately and the working tree confirmed
byte-identical afterwards (`git diff --exit-code`, zero dirty entries, three
times).

**Extended to fifteen, and one of the runs disproved a claim.** The same
procedure was applied to twelve more of the sixteen:

    F-10  de-duplicate by CONTENT, not by path
          -> 3 failed   test_one_measurement_is_not_counted_twice
    F-11  required views are PER AXIS, not global
          -> 24 failed  test_a_corner_independent_axis_no_longer_needs_the_timing_corners
    F-15  the hold axis proves from the worst-slack name too
          -> 9 failed   test_worst_slack_and_wns_are_the_same_predicate
    F-18  a verdict spelling may not be silently dropped
          -> 3 failed   test_the_accept_set_is_the_one_the_feasibility_axis_declares
    F-2   a backend states its OWN reason for not being drivable
          -> 0 failed, 0 errors   <-- THE GUARD CANNOT FAIL

Two more were driven the same way:

    (smaller) the bundled validator's semantics hold on a stock host
          -> 1 failed   test_the_bundled_semantics
    (lane) a present-but-empty population is never a pass
          -> 2 failed   test_a_present_but_empty_population_is_never_a_pass
                        test_mutation_metric_extract_empty_bundle
    F-1   an excluded lever's owner must RESOLVE, or it is unowned
          -> 1 failed   test_with_the_owner_absent_the_reason_says_unowned_not_delegated
    F-14  absolute host paths in an emitted deck are detected
          -> 5 failed   test_the_real_defect_goes_red
    (lane) a bad invocation is 3, not the could-not-check code
          -> 20 failed  test_unknown_flag_is_bad_invocation_not_undetermined

So **fifteen of the sixteen ALREADY-PROGRAM claims have now been driven:
fourteen fire and one cannot.** The bundled validator was probed by letting a
boolean validate as an integer — the JSON Schema subtlety a hand-written
validator is likeliest to get wrong — and `test_the_bundled_semantics` catches
it. Only **F-13** is undriven, and it is enforced by a document and a
finding-code convention, which a mutation cannot address — so it was VERIFIED
instead, both halves of the citation and not just the file's existence:

    §3 "Identity" heading present                                    yes
    the rule stated in bold: an artefact that varies with the
      implementation may not sit in the analysis identity            yes
    `PPA-C-016` present, and naming this case                        yes

A prose-enforced claim is the one kind that rots with nothing going red, so all
three are now pinned by check 42. **Sixteen of sixteen are therefore accounted
for: fifteen driven, fourteen of those firing, one disproven, and one verified
against the document that enforces it.**

*Two paragraphs here were wrong before they were right, and both errors were
mine rather than the guards'.* The first put the vacuous-population census among
the things that had defeated a probe. It did not belong there: I never probed it,
and the sentence attributed to it a failure that had happened to two other
things. Probed properly it fires — and one of the two tests that go red is
already called `test_mutation_metric_extract_empty_bundle`, so the repository was
doing this before I was.

*The second said the two denominator gates "resisted an honest probe".* They did
not. I handed each a synthetic directory; the disclosure gate went on probing all
90 declared CI gates because its population is chosen by a `--population` switch
I had not read, and the zero-denominator gate's population is gates that *state*
a zero population, which my stub never did. Both returned PASS for reasons
unrelated to my input, and I wrote that down as a property of the gates instead
of a defect in the probe.

Driven properly, with a two-arm control each — one stub committing the offence
and one doing the right thing — both fire and both name the offending arm. The
disclosure gate reports `PASS_WITHOUT_DENOMINATOR` against the silent stub and
accepts the disclosing one. The zero-denominator gate probes two, finds both
stating a zero population, and separates the one that refused from the one that
exited 0. Against the real tree it reports 569 gates probed, 25 stating a zero
population, 24 refusing and 1 exempted. The `[FAIL] STALE_INVENTORY_ENTRY` line
the synthetic runs produced is not a defect either: it is the gate correctly
noticing that a dated exemption stops describing anything once the population is
a two-file temporary directory.

Earlier in this list: F-2's guard requires each backend to be drivable or to
raise with a reason of at least forty characters — and the production seam
supplies a generic fallback reason, comfortably longer than forty characters,
whenever a module declares none. The predicate is therefore true by construction
and no backend can violate it. Three mutations were needed to establish that
honestly: renaming the shared constant proved nothing (both the code and the test
read the same symbol, so they stayed consistent), and deleting one line of a
multi-line assignment produced invalid Python, whose green result was an artefact
rather than a finding. Only the third — removing the whole assignment and
re-parsing the file to confirm it still compiles — is evidence.

The narrow syntactic form of this — a raise whose message is `<lookup> or
<default literal>` — occurs at **one** production site in the tree. It is
recorded as **A-30** anyway, and the reason is a mistake this lane made twice
already: folding a distinct failure into a neighbouring record is exactly how
`F-17`'s rule and `F-6`'s second clause came to be invisible. A guard proven
unable to fail is not a footnote on a population record. The rule is stated over
the semantics rather than the syntax, because a default can also arrive from a
dataclass field, a `dict.get`, or a base class.

**One by-product, measured and deliberately NOT made a record.** The second
mutation on the bundled validator — making `validate_schema_itself` return no
errors at all — was undetected, and the reason is that the function has no caller
anywhere in the tree. Swept, because a population of one would not be worth
mentioning:

    names exported in an `_ppa` `__all__` with no reference
      outside their own file                                     15

A name in `__all__` is a declared public interface, so fifteen of them having no
consumer is the same declared-versus-actual disagreement this cluster keeps
finding, and a mutation to any of them is undetectable by construction. It is
written down here with its measurement rather than promoted to a record, and the
distinction from `A-30` is deliberate: A-30 exists because a claim IN THIS REPORT
was shown false, whereas this is a hygiene observation with no failing consequence
demonstrated. The measurement is here for whoever wants to make the case; I have
not made it.

This is deliberately NOT wired into `verify.py`. A verifier that edits the
product tree to prove a point is a verifier that can leave the tree edited, and
this batch already records what an unnoticed tree write costs. The procedure is
written down here so it can be repeated by hand; the three commands are in the
list above.

## The brief's own requirements, audited against the finished records

Every method used on this deliverable so far examined it on its own terms. The
last one available is to read the brief as a checklist and test the records
against it. The ladder's field requirements pass — the Bucket-T record carries
all five it demands, and both Bucket-C records carry theirs. Two requirements did
not:

- *"a rule's docstring states the general PATTERN, not the war story."* One
  Bucket-A docstring opened its last sentence with *"Two defects already recorded
  in this batch reduce to it"*. A docstring ships **into a program**, so that
  sentence would have travelled into the tree and outlived the batch it names.
  Worse, it characterised a sibling record in terms that had already been
  corrected in this report and not here — **the same fact in two places, fixed in
  one**, which is the defect A-9 and A-17 are both about, committed while
  correcting A-17.
- *"Each one carries the MEASUREMENT."* One Bucket-A record described its
  measurement in prose and carried **no figure at all**. It now states that the
  layer presents 19 commands, that exactly 2 were driven to a real verdict, and
  that the other 17 are not measured and not claimed.

**The brief's FIRST requirement, tested rather than assumed.** *"START WITH THE
18. For each, write the rule that would have caught it."* The verifier confirms
the table has eighteen rows; it never confirmed a row states a RULE rather than a
status. Screened for obligation — 18 rows, **0 stating anything less** — with two
negative controls proving a bare status does not match.

The screen took three attempts, and the misses are worth naming because anyone
rebuilding it will repeat them: a verb list of *must / may not / never* misses
the imperative mood (*"De-duplicate by CONTENT, not by path"*), misses *"Nothing
that enters a hash identity may carry…"*, and misses *"may claim only"* if the
alternative requires those two words to be adjacent — they are three words apart.
Each miss reported a real rule as a defect. **This is deliberately not made a
permanent check**: the regex needed three passes to stop producing false
positives on hand-written English, and a fragile screen wired into a gate fails
later for reasons that have nothing to do with the document. The measurement is
recorded; the table is eighteen stable hand-written rows and does not need a
parser standing over it.

A third flag was my screen's fault, not the records': the Bucket-T record looked
figure-free because I searched the field the Bucket-A records use, and the ladder
puts a T record's measurement in `problem` and `bad_sample`, where it is dense
with them. Check 46 encodes that exemption rather than repeating my mistake.

## The same question, asked of the records, and where the tooling stops

If a check's name can promise more than its predicate delivers, so can a RULE's
name promise more than its own `fix_action` achieves — and that would mislead the
implementing lane rather than a reader. The question is the right one. **The
tooling cannot answer it.**

A screen for fix_actions that narrow their own scope flagged 24 of 35, on the
word *only* — which ordinary prose uses constantly. Three of the flagged were
read in full, named here so the sample is not a claim about the rest:

| record | what the flag actually was |
|---|---|
| the accepted-value branch | *"the suffix admits **only** word characters"* — describing the defect |
| the docstring binding | part of the build instruction, not a narrowing |
| the absence claim | *"take **only** paths within a short window"* — a screen refinement |

None narrows its rule name's promise. That is a negative result **on a sample of
three**, and the population figure is deliberately not given, because the screen
that would produce it is the eighth in this lane to measure my own vocabulary
instead of the text.

**This is where the ladder ends.** Figures that are projections of repository
data can be bound, and now are. What a binding proves can be tested, and was.
Whether a name is honest can be read, and was, for the verifier's 54 checks. The
same question about 47 records needs 47 readings, and the honest report is the
three that were done rather than a number that would look derived.

## Three check NAMES promised more than their predicates deliver

A control proves a check is not vacuous. It does not prove the check's **name**
matches its strength — and a reader trusts the name, because the name is what the
output prints. All 51 were read against their predicates, and three named a
semantic property while testing a syntactic proxy:

| the name said | the predicate did |
|---|---|
| every record *answers* the brief's two questions | the `(o)` and `(d)` markers are present |
| no two patterns *restate one class* | lexical similarity below a threshold |
| every action names predicate, population and refusal | those concepts appear in the text |

None is wrong; each is weaker than it sounds. The similarity one cannot see two
patterns restating a class in different words — which is why the closest pair in
this batch was read by hand rather than trusted to the number. The marker one
cannot tell a considered answer from the letter `y`. The third is the
buildability rubric, whose limit is measured above: it passes on *"should be
checked across all the relevant cases and reported when it fails."*

**Two have been renamed to what they test**, so the output can no longer imply
more than it establishes, and the third carries its limitation in the section
that quotes it. That is the cheaper repair than strengthening them: a check that
honestly reports a syntactic result is useful, and a check whose name claims a
semantic one quietly retires the reading that would catch the difference.

## The verifier audited as an artefact, not used as one

Every claim in this report rests on `verify.py`, and five defects have been found
in it so far — each one incidentally, while it was being used for something else.
So it was audited deliberately, on the question this batch keeps asking of other
people's guards: **can each check fail?**

    check() calls                                        48
    with a control within the surrounding lines          46
    without                                               2

One of the two was genuinely vacuous. *"Every sketch resolves to its section by
name"* was `all(d in byslug for d in defs)`, and **`all()` over an empty list is
`True`** — so if the glob or the `def` regex ever stopped matching, the check
would pass while examining nothing, printing `0 sketches` inside a green run.
That is precisely the shape this report documents elsewhere: an empty check and a
clean check print the same.

Fixed by asserting the population is non-empty first, and **proved by removing
it**: with the sketch files moved aside the check now reads `0 sketches` and goes
RED, where before it would have gone green. The files were restored and the tree
confirmed clean. The other was already safe — its guard clause makes a missing
table row a failure rather than a pass — and it now carries a control anyway, so
the audit's own figure is zero uncontrolled checks rather than "two I judged to
be fine".

**Then the controls themselves were read, because the framework cannot audit
them.** It catches a control that *fails to fail* at run time and prints
`CONTROL BROKEN`; it cannot tell a control that detects a fault from one that is
true no matter what. Reading all thirty:

    inject a known fault and require it to be caught          strong
    assert only that a parse succeeded                        weaker, but real
    true regardless of the fault                              2

Both are now repaired. The first was found earlier — a control asserting a
deliberately-absent filename was absent, which holds under a *wrong* repository
root too, and is why the root bug it was guarding went unnoticed until the bundle
moved. The second is in the authoritative arm, the half that matters most: the
live wiring check is an **intersection**, so an empty parse result passes it
having examined nothing, and its control read `... or bool(stdout)` — a clause
true whenever the gate printed anything at all, which says nothing about whether
the parse found the list. It now requires the parsed population to be non-empty
and not to over-match a name the gate never prints.

Re-run on the slow arm, the population is real, so the check had been doing its
work all along and simply had no guard proving it. That distinction is the point:
this did not find a wrong answer, it found **an answer that was not entitled to
be trusted**.

## Does any commit describe a change it does not carry?

A prose edit raised an exception and the commit ran anyway, because the edit and
the commit were separated by a newline rather than by `&&`. The report lagged the
verifier by one commit. That is a process failure worth knowing about, and the
question it raises is bigger than the instance: **can the commit history be
trusted to describe the tree?** A landing reviewer reads the messages.

Audited across the whole branch, with the screen validated before the result was
believed:

    commits examined                                          107
    messages claiming a change to the report or a record       65
    of those, not carrying that change                          0

The screen was checked both ways first — it matches a message that claims prose
and does not match one that only describes a code repair — because a phrase-set
that matches nothing returns a clean answer indistinguishable from a clean
branch. That validation also corrected me: I had accused the offending commit of
describing a section it did not ship, and re-reading its message, it does not.
It describes an audit and a repair, and both are in it. **The real fault was
narrower than the accusation** — the edit failed silently, so the report trailed
by one commit, and no message was ever false. The overstatement stands in the
git history, which is not rewritten; it is corrected here instead.

## How often the instrument was the problem

This report names a lot of defects. A reader deciding how much to trust them
needs the other number: how often a screen I built returned a wrong answer about
a subject that was fine. The report was counting — badly. It carried **three
incompatible running tallies**, none reconciled with the others and none updated
for anything found afterwards. Measured once, in one place:

    paragraphs documenting an instrument error            17
    explicit "reported X where the answer was Y" pairs     4   (560→0, 216→51,
                                                               47→11, 34→9)

**17 is a floor, not a total** — it counts what the prose bothered to write down,
and the late sweeps produced more than they recorded: an absence sweep whose
granularity was wrong, a universal sweep that read a spelled-out count as no
count, a superseded-denominator screen wrong three times in five, an obligation
screen that needed three passes, and four consecutive greps that nearly filed a
defect against a correct shipped gate.

The rate is the point, and it cuts both ways. A large share of the candidate
findings in the later sweeps were the instrument rather than the subject — and
**every one was caught by running a control before believing the result**, which
is why they appear here as corrections rather than as claims. So the reader's
calibration is: a figure that names its screen and its control has been through
that filter; the handful explicitly dated to the base has not been re-run at all,
and says so.

## Every blockage in this report, measured

The handoff names things this lane could not do. Those are the easiest claims in
a report to get wrong, because a blockage is asserted from the outside and
nothing fails when it is imagined. Seventeen paragraphs here assert that
something is impossible or blocked; all of them carry evidence in or beside them.
But evidence *near* a claim is not the claim being tested, so the two that
actually stop work were tested directly:

    the verifier cannot be wired          the landing manifest lists 47 protected
                                          paths and the hygiene-gate script is
                                          one, with the `authority` role — and no
                                          entry covers this bundle's own path
    the Bucket-T crash evidence is gone   both run trees the records' provenance
                                          paths name are absent from this host,
                                          so it can be REMADE but not found

Both hold. One of them did not hold in the form it was first written: the
handoff had said to *attach* the crash artefacts, which presumes they exist
somewhere, and the check turned that into *re-run one arm to produce them* —
a different instruction with a different cost.

## The ten requests in the cross-layer source, mapped

The other source's thirteen requests have a paid/unpaid table in this report.
This one's ten never got the same treatment — the coverage row credited it with
`T-1` and the evidence for one finding, which is what I took from it rather than
what it contains. Mapped properly:

| # | request | this batch |
|---|---|---|
| 1 | give the runner a first-class synthesis-strategy flag | **now recorded as A-33** — verified: the runner exposes 3 place-and-route knobs and no synthesis actuator, and the search that hit this compensated by hand in 6 of 9 staged files |
| 2 | state that an artefact the search may rewrite cannot sit in the `problem` identity | **now recorded as A-32**, and measured wider than the request: the scheme declares five identities and exactly one states what may not sit in it |
| 3 | the timing module should omit scope keys it cannot establish, not write null | **now recorded as A-38** — the mapping said "partly A-2", and measuring it showed otherwise: A-2 is about a key's PRESENCE, this is a present-but-null key the interface calls worse than absent |
| 4 | fix the Phase-3 power session or stop the report claiming post-PnR | the class is **F-7** in the eighteen |
| 5 | a `drv` producer | **A-1** exactly — the axis with no producer for any of its proof names |
| 6 | declare the schema library or bundle it | the bundled-schema ALREADY-PROGRAM, plus **C-2** for the version matrix |
| 7 | report how far the equivalence induction got | **now recorded as A-34** — the program already emits a depth field for its refutation half and none for its induction half |
| 8 | the post-route repair crash, ten reproductions | **T-1** exactly |
| 9 | name the taps in the area taxonomy | **now recorded as A-35, and my assessment was wrong** — tested, the required scope is 1 key and the composition is not among the 5 carried, so the required-key rule cannot reach it |
| 10 | the smaller ones | **both halves now recorded** — the satisfiability item as **A-36**, and the refusal-without-a-remedy item as **A-37**, which measures 23 refusals in the layer and 0 carrying one |

**Four are covered exactly, one partly, five are not mined.** They are listed
rather than absorbed, because a request that is neither paid nor recorded is
invisible to both the lander and the implementing lane, and this table is the
only place the five appear. The two worth a record on their evidence are 1 and 2;
the case for each is written beside it above rather than asserted here.

## How much to trust each figure in this report

Every re-measurable figure that was re-measured had moved. Four for four. That is
worth converting into an instruction rather than a boast, because it means a
reader cannot treat the numbers here as uniform. They fall into three classes and
the report now says which is which.

**Bound to live data — cannot go stale without the verifier failing.** Seventeen
of its fifty checks bind a figure: the batch's own arithmetic (bucket counts, the
ladder split, the status block, every heading and prose tally that states a
record count), the two quoted pytest figures, the live gate figures under
`--slow`, the near-duplicate pair count and maximum, the summary against disk,
and the bundle's own date. Edit any of them wrongly and the run goes red.

**Re-measured during this lane and current.** The nine sweeps, the record-tree
counts, the provenance split, the schema-coverage figures, the documented-command
failure, the six exit codes, the unguarded-import census. Where these moved, the
row says so and shows both values.

**Dated to the base and NOT re-derivable.** Two rows quote populations whose
screen was never recorded, so a later attempt produces a conflicting number
rather than a confirmation — one reconstruction came back at more than twice the
original. Those rows say so in place, and the relations they support are stated
in a form that does not lean on the counts. One further row is exempt for a
different reason its own record gives: the question it asks cannot be answered by
scanning code at all.

**Every Bucket-A record carries a measured population.** Checked from the sweep
table rather than from the prose, because a prose screen for this measures the
author's vocabulary and did, twice:

    records with a section                          37
    whose sweep row carries a figure                35
    without one                                      2   (C-1 and T-1)

The two are the two buckets where a sweep row is not the home. C-1's population
does not exist yet — that is its stated reason for being Bucket C, since no
emitter records the inputs its check would read. T-1's measurement lives in its
sample fields, where the ladder puts it, and is dense with figures there.

**And the batch cannot answer that question about itself, which is worth saying
rather than fixing by retrofit.** Counting the records that carry an explicit
additional-instance marker — a convention I used deliberately — gives 4 of 37.
But others demonstrate multiplicity without it: one names four fresh offenders
across three sibling lanes, one spans 52 of 52 across three lanes, one has three
independent confirmations. So the marker undercounts, and it undercounts because
**I applied my own convention inconsistently**, not because the instances are
absent.

The consequence is concrete and it is what `A-11` just demonstrated: a reader
deciding which rules survive a point fix cannot get that from this document at a
glance. Retrofitting a marker across thirty-seven records would make the number
look derived when it would in fact be re-read — so the honest statement is the
one above, and the four that carry it are the four that carry it.

*A measured population is not the same as a measured SECOND instance, and the
table cannot tell them apart.* That distinction is what made `A-11` survive main
repairing its motivating site: the record named two instances and only one was
fixed. Records that name several are noted as such in their own text; the
count of those is not derived here, because deriving it needs the reading the
sweep table cannot do.

The practical reading: **a figure in this report that is not marked as dated has
either a check standing over it or a re-measurement behind it.** The two that
have neither are labelled, and they are labelled because trying to check them is
what revealed that an unrecorded screen does not merely leave a figure
unverifiable — it manufactures a disagreement that looks like drift.

## Re-measuring the older sweeps, and what it cost to try

Nine sweep rows were measured against the program tree, and main moved thirty
commits underneath them. Six were re-attempted. The result splits by one thing
only — whether the row recorded HOW it counted:

| row | outcome |
|---|---|
| A-9 | reproduced, and **moved**: 6 of 29 → 10 of 33, the four new offenders being the sibling capture lanes |
| A-22 | reproduced: 51 → 50, still exactly one package |
| A-25 | reproduced, and **the gap widened**: 17 of 29 → 19 of 38 |
| A-11 | **partial** — the census reproduces within three per cent (1584 → 1544) but its taxonomy does not, because where "extension-only" ends was never stated, and its load-bearing figure needs a judgement no screen makes |
| A-24 | **not re-derivable** — a plausible reconstruction returned more than twice each figure |
| A-26 | reproduced, and **closed its own gap**: 2 → 7 documents bound, and the population it left unestimated is now 1215 candidate docstrings of 4026, by a stated screen |
| A-5 | re-measured BY EXECUTION: 8 commands, **6 silently pick one**, 1 refuses with the wrong exit code, 1 returns a green pass on zero work; the remedy is demonstrated in-tree by **4 gates calling a shared seam** with the bad-invocation code — not by argparse, and not by the rc-2 refuser I first credited |
| A-20 | **not re-derivable** — no screen recorded at all |

Three reproduced, two could not be, one partly. **Every failure is the same
cause, and it is not the tree moving: it is that the row did not say how it
counted.** A-25's row moved by nine types and that is a finding; A-24's row
"moved" by a factor of two and that is an artefact of using a different screen.
From the outside those look identical.

*The obvious shortcut was tried and failed, which is worth recording because it
is the fifth time.* Rather than re-attempt each row, a screen was written to ask
which sections record their criterion. It answered nine of nine — including the
two I had already read and confirmed do not. It fires on any section that happens
to mention scanning. That is the fifth keyword screen over this report's own prose
to measure the author's vocabulary instead of the text, and the table above is
built from the re-measurements actually attempted, not from it.

## The one claim class that keyword screens cannot audit

Five classes of claim in this report were audited by building a screen over the
prose: absences, universals, temporal states, superseded denominators, and
blockages. Each found something. The sixth class is the one an implementer
actually builds from — the **mechanism**: *because X, Y*. A wrong count misleads;
a wrong mechanism misdirects the fix, which is what `A-17`'s original argument
did.

The screen was built and it does not work. It asked which mechanism-asserting
record sections show a CONTRAST supporting them — the mechanism present against
absent — and reported that 14 of 25 show none. Tested against a section I had
personally run two groupings on that same day, it found no contrast there either:
that section says *"again on"*, *"by `source.tool`"*, *"MIXED"* and *"grouping"*,
and the screen was looking for the words I happened to think of. It was measuring
my vocabulary, not the presence of a contrast, and a fourth guess at the word
list would measure the fourth guess.

**So the figure is withdrawn rather than refined**, and the honest answer is that
this question is already answered mechanically somewhere else: the sweep table.
Every rule in it now carries a sweep, and a sweep IS the contrast — a before and
an after over a named population. That is why nine sweeps changed nine rules
while five prose audits changed the prose. A mechanism stated in a paragraph can
only be read; a mechanism with a population and a sweep can be run.

The general lesson, measured across four attempts: **a keyword screen over one's
own prose measures the author's vocabulary.** It is worth building once to find
what it happens to catch, and it is never worth wiring, because the vocabulary it
encodes is the one blind spot guaranteed to be shared with the text.

## A record closed on main while this branch was open

The withdrawn record is `A-18`.

This was a Bucket-A rule: *a lever that deletes a design property must be priced,
or the winner is a trade.* Main landed the fix in the 214 commits it gained
during this lane, and the brief's rule is that a class an existing program
enforces gets named, not duplicated. So the record is withdrawn and the entry
moved to the ALREADY-PROGRAM list.

What landed, verified rather than taken from a commit message:

    programs/ppa_eco_spare_records.py   the producer — the spare population as
                                        canonical records a gate can adjudicate
    `_ppa/feasibility.py`               `ECO_AXIS = "eco_readiness"` — the axis
                                        that refuses
    spare_cell_coverage_check.py        were enough inserted, spread, tied off
    spare_cell_preservation_check.py    did they survive to the shipped artefacts

The producer's own header states the defect in the same terms this record did: a
search deleted a design's entire spare-cell population and **scored better for
it** — smaller area, lower power, and no axis anywhere saying the layout could no
longer be repaired by a metal-only ECO.

**This is the outcome the loop exists to produce**, and it is worth saying plainly
that it happened without this batch: the sweep here established that the property
was invisible to both judges, and main independently built the producer, the axis
and two gates. The record's value now is the measurement it leaves behind, not
the rule it no longer needs to argue for.


## Re-checked against main's 214 commits

The brief's anti-duplication rule has to be discharged against the tree as it is,
not as it was when a record was written — and main moved twice under this branch,
the second time by 214 commits. Every record whose target program main touched
was re-checked:

    distinct programs this batch routes to            18
    changed by main's 214 commits                      5
    records those five carry                           9
    closed by main                                     1   (withdrawn, above)
    still holding                                      8
      of which one had its MOTIVATING SITE fixed         1   (A-11, and the
        while the class survived elsewhere                    record stands)

The eight were verified individually rather than assumed from the diff: the
equivalence prover still emits no depth and no exhaustion flag, the interface
document still states exactly one identity's membership rule, the feasibility
module still contains no satisfiability check, and the area figure's required
scope is still a single key with no composition.

**One of the eight is the brief's own case, made concrete.** A-11's motivating
site was repaired on main during this lane — the comparison gate stopped guessing
at filenames, and a landed test states the old defect in the same terms this
record does. Its SECOND instance was not touched: the timing module still selects
sign-off reports by a filename prefix, and its own comment still promises that a
new corner report is picked up without a change there, which was measured false
at 8 of 13. So the record is updated and **not** withdrawn. Withdrawing on the
strength of the visible site being fixed is precisely the mistake the brief warns
about — *a fix that landed is where the distilled rule is missing, because the
next occurrence is somewhere the fix did not look.*

**One of the eight nearly read as closed.** A screen for whether the search space
had gained a record of which levers were exercised returned six hits — and all
six are the word *searched* in other senses: the directories the program reads
documents from, a lever refused for want of permission, and the pre-existing list
of place-and-route knobs excluded on purpose. None of them says which ADMITTED
lever a run turned. The vocabulary trap this report has now recorded five times,
appearing once more in the check that exists to prevent duplicating other
people's work.

## The honest sentences, checked verbatim against the records

The deliverable owes, *"for each Bucket B/C/D, the one honest sentence the ladder
demands."* Three records owe one (2 C, 1 T). Checking that the sentence in this
report is the sentence in `recoveries.json` — not merely that a blockquote exists
— found **one had drifted**:

    record:  "...all six survivors I could execute DEGRADED CORRECTLY"
    report:  "...every survivor I could execute BEHAVED CORRECTLY"

Both defensible; the record's is the more precise, and the record is what an
implementer reads. The report is now aligned to it, and all three render verbatim.

**The drift is this batch's own subject, committed by its author.** One fact held
in two places with nothing relating them is exactly **A-9** and **A-17** — and it
survived every other check here, because each of my audits asked whether a
required element was *present*, never whether two copies of it *agreed*.
Presence is not agreement, which is the whole finding of the three records the
brief singles out.

**So the agreement question was then asked of the numbers too.** A screen
comparing each record's figures against its report section flags 12 of 19 — and
that number is **not a finding**: it counts numbers the section adds (line
references, breakdowns) as though they were disagreements, conflating
elaboration with contradiction. Reported here only so the next reader does not
re-derive it and believe it.

The answerable question is narrower — *did a figure I revised mid-lane survive
in one place and not the other?* — and it was asked of the four records whose
headline numbers changed:

    invariance rule        24 / 54 and 8            both places agree
    discovery rule         362 / 1584 and 12        both places agree
    routing-vs-wiring      26 / 16 current          both agree; the superseded
                                                    21 / 15 appears only in the
                                                    record, deliberately, as history
    screen-validation      0.07 / 0.38 / 0.966      all in the record; the report
                                                    adds a population size

**Zero contradictions.** One real drift in the whole deliverable, found in the
prose the ladder demands and fixed above — which is the honest yield of asking a
question I had not been asking.

**And it is now a check rather than a reading.** Check 26 compares every figure
the sweep table quotes against the record it summarises. It required the
number-word normaliser to be built first: without it the check reports **11 rows
in disagreement**, and every one is `zero` in the record against `0` in the
table. That false 11 is the reason the normaliser sits in the check instead of a
filter — it was measured, read by hand, and would otherwise have been rediscovered
by whoever ran this next.

## Traceability — a sketch must lead back to its narrative

An angle I had not tried: **can someone holding only `candidates/` find the
measurement narrative?** The sketches carry the pattern, the docstring and the
whole fix action, so the content travels. The link does not: no sketch names a
record id. The only handle is the generated `def rule_<slug>`, derived from the
record's `rule_name`, which is also supposed to be the section heading here.

Tested, and it did not round-trip:

    rule definitions in the sketches                 28     (26 at the time)
    resolving to a section by name, before           20     of those 26
    resolving after                                  28     all of them

**Seven headings paraphrased the rule name instead of using it.** *"…may not rank
until…"* for *"…may not rank candidates until…"*; *"…is contract, and must be
driven…"* for *"…is part of the contract and must be driven…"*. Each reads
better and each broke the only link between an emitted artefact and the evidence
behind it.

This is the **presence-versus-agreement** class again, one section up, and the
third instance of it in my own work: the elements were all present, and two
copies of one string disagreed. My audits counted sections and counted defs;
nothing asked whether a def could *find* its section. The fix is to make the
heading quote the record verbatim, which is now true for all 26 and is
mechanically checkable — a heading is either a `rule_name` or it is not.

**And then the same defect turned up in the population I had not looked at.**
Having fixed the 26 Bucket-A headings I declared traceability closed. The check
I wrote only walked `A-`; the three C and T headings had drifted too, all three
of them:

    C-2  heading dropped the clause naming what the arm tests
    C-1  "...the inputs the session opened" for "...actually opened"
    T-1  "post-route repair faults" for "post-route design-rule repair faults
         on a netlist shape"

Fixing the population under examination and leaving the adjacent one is **A-3
and A-4's own lesson**, committed here by their author one section after writing
it down. All 29 headings now quote their record verbatim, and the check walks
all three buckets rather than the one I happened to be thinking about.

## The verification is a command, not a paragraph

Every claim above was measured once, by hand, across as many sessions — and then
asserted in prose. **A check a human has to remember is not a check**, which is
the thesis of the brief this batch answers, so the claims are now one command:

    $ python3 docs/capture/2026-08-21-jcap-ppa/verify.py
    PASS — every claim this batch makes was re-measured and holds.

Fourteen checks: bucket counts against the report table, one section per record,
every heading quoting its record verbatim, a measurement in every record,
predicate/population/refusal in every buildable action, no two patterns
restating one class, each honest sentence rendered verbatim, the emitter's
summary against the records and against disk, and every sketch resolving back to
its section.

**Two properties it was built with, both earned here.** Every check compares two
artefacts rather than inspecting one, because all five defects found in this
deliverable were *agreement* failures with nothing missing. And every check runs
a control that must fail first — if the control passes, the check reports itself
BROKEN instead of green.

**Extended twice, each time to something it did not cover.** The first version
checked fourteen things and not the two that had actually gone stale during the
lane — the sweep table as the batch grew, and routing. Then it did not cover the
brief's *first* requirement, the rule stated for each of the eighteen findings,
nor whether the emitted backlogs still pass the sanitiser that consumes them —
and two of those were refused on first write, so a later edit could refuse them
again in silence. **Thirty-four checks now, plus an authoritative mode**, the last of them the one that closes the loop:
`candidates/` is *generated*, so editing `recoveries.json` without re-emitting
leaves sketches that still resolve by name, still read plausibly, and describe
the previous version of the rule. Name resolution cannot see content drift.

That check was **proven live rather than argued**: perturbing one record's
docstring makes it fail and name the record and the field; restoring the record
makes it pass. A control that has actually failed on the real artefact is worth
more than any constructed one.

**Both new controls were weak and were replaced.** One asserted a row number
that could never appear; the other asserted the sanitiser file exists. Neither
demonstrates the check can fail, which is precisely what A-27 was tightened to
require. They now ask for a nineteenth rule that is not there, and run the
sanitiser against a deliberately malformed backlog — and both must fail before
their check is believed.

That second property paid immediately: **on its first run the harness declared
its own measurement control broken.** The control string was *"a claim with no
quantity at all"*, and the number-word pattern matched on *"no"* — the control
was itself a positive. A hand-written check would have printed PASS and I would
have believed it. This one refused to.

**And it went on to catch three more errors — all three in itself.** The
title-versus-tables check reported 23, then 27, against a title of 16 that was
correct all along: each prose anchor I split on sat beside other tables and the
span swallowed them. Replacing the anchors with a structural read — find the
table by its own header row, stop at the first non-table line — gives 16 and 16.

Four bad screens in one file, every one caught by the file rather than by me,
and the deliverable's numbers unchanged throughout. That is the difference
between a check that runs and a check that was run once.
## A dangling reference the whole verifier walked past

The demotion of one record out of Bucket A left the provenance table citing an
id that no longer exists — for the rest of the lane, through twenty-seven checks
and several audits that all reported CLEAN.

**They walked past it because of their shared direction.** Every check started
from the record set and asked *is this represented in the prose?* None asked the
reverse: *does this prose reference point at anything?* One direction of a
two-way relation, checked twenty-seven times.

Check 29 asks the reverse. It also excludes the plugin's own finding codes,
whose tails read as record ids — matching them reports a phantom.

**And its first fix reintroduced the problem it was fixing.** Rewriting the row
to explain the demotion, I wrote the dead id into the explanation, and the check
kept failing — correctly, because a reader scanning for that id would still find
something that looks live. The history is now stated without the bare id.

**The lesson was then applied rather than admired.** Two relations remained with
the same shape, and both are now checked in the reverse direction: a routing step
this branch added that no record uses, and a sweep-table row naming a record that
does not exist. Both come back clean — **16 added steps, all used; 27 rows, none
orphaned** — but they were unguarded until the direction was named. An orphan is
not cosmetic: a routing entry nobody uses claims a step exists for work nobody
filed, and a summary row for a deleted record asserts a rule the batch no longer
makes.

A suite of checks can share a blind spot precisely *because* it is a suite —
thirty checks written from one habit of thought all point the same way. That is
the batch's own central finding at the level of the checking apparatus.

**Demonstrated once more while adding the contents map.** This document had run
to 1,778 lines with no orientation, so a map was overdue on readability grounds
alone. Building it surfaced a section headed **"The twelve records"** sitting
over twenty-nine — stale for most of the lane, and invisible to all thirty
checks because every one of them inspects the `###` record headings and none had
ever looked at the `##` section headings above them. A level of the document
nobody had thought to walk.

The map is checked in both directions: every section listed, every entry
pointing at a real section.

**Then the levels were enumerated deliberately rather than stumbled into**, and
two were still unwalked: the anchors the map's links actually target, and the
`#` title's own count — the one line every reader sees, sitting above a STATUS
block that had been checked for several passes.

The anchor check reported **8 of 21 broken** on its first run. The slug rule is
*each space becomes a hyphen*, not *runs collapse*: a stripped em-dash leaves two
spaces and so a double hyphen. All 8 were the test's assumption, not the
document's links — 21 of 21 resolve. Nineteenth screen error of this lane, and
the same shape as the eighteen before it: a plausible failure count produced by
the measuring code.
## Emission is reproducible, and the one thing that moves is the one that should

A last property nobody had measured: **re-running the emitter over the same
records — does it produce the same artefacts?** If it did not, the committed
`candidates/` would be one arbitrary rendering of many and the sync check would
be comparing against an accident.

    16 sketch files          byte-identical on re-emit
    3 backlog YAMLs          differ in exactly one line

That line is `submitted_at`, and the emitter's own source explains why it must:
the field is *"a measurement or it is nothing"*, having previously been a literal
midnight that made every record look measured. So the single non-reproducible
field is the single field whose whole purpose is to record an instant.

The practical consequence, stated because it will surprise someone: **re-emitting
dirties three files in `git status`** without changing a word of content. The
committed timestamps are the record of when this batch was emitted; a re-run
should be reverted rather than committed.

**And adding this very section broke the build.** Writing it introduced a
twenty-second heading without updating the contents map, and check 32 failed
exactly as intended — the map is a second copy of the section list, and I had
edited one copy. I compounded it by running the verifier *after* the commit in
the same command chain, so a failing state reached the branch for one commit.

Both are recorded rather than tidied away. **Verify before you push, not beside
it**: a check whose result arrives after the push is a check that did not run in
time. And a map maintained by hand will drift again, so it is now *regenerated*
from the headings rather than edited — the same promote-the-habit-to-a-program
move this whole batch is about, applied to the document's own furniture.
## Three checks the verifier was missing, two of which could not have failed

Reading the records rather than diffing them found that the question the brief
asks of EVERY record — would the rule have fired on the ORIGINAL defect, and
would it fire on a DIFFERENT instance of the same class — was answered in all
thirty, under the `(o)`/`(d)` markers, and enforced by nothing. A marker is one
token; dropping one is invisible. That is now check 35.

Writing it produced two defects in the verifier itself, and they are the same
shape as the cluster it verifies:

- **A check appended at the end of the file gates nothing.** `check()` appends to
  a list; the verdict reads that list once and exits. Everything after the verdict
  prints and cannot fail the run. Both new checks were written there first and
  were dead. Check 37 now refuses it — and its first draft searched for the
  verdict with `.index`, matched the copy of that same literal inside its own
  source, and reported the bug against itself. `.rindex`, and a control that
  asserts the two differ.
- **One helper was defined twice.** Names bind at call time, so every call after
  the second `def` silently got the other body. The duplicate-pattern guard scored
  0.385 under the intended normaliser and 0.361 under the shadow — and the shadow
  is what any check appended at the end of the file would have used. Renamed;
  check 36 refuses a second definition of any name.

Neither changes a published number: the only `sim()` calls sit above the shadow,
so 0.385 was always the figure computed. What they change is what the next check
would have done. Both are recorded as self-instances on **the record that says a
rule must be routed into a program some verdict consults** — a guard that runs
after the verdict, and a name that resolves to the wrong body, are both "present,
and not consumed by the thing that reports on it". They are not a new record.

## Was every commit green? Replayed, and the answer is one

The verifier proves the deliverable holds *now*. It says nothing about whether it
ever did not — and I knew of one commit that was red, because I caused it. What I
did not know was whether there were others.

Every commit that touched `docs/capture/2026-08-21-jcap-ppa/` since the verifier existed was replayed
against **its own** report, records and routing table:

    commits replayed     20
    red                   1   — the one already documented above

So the account in this document matches the history. One failing commit, caused
by adding a section without updating the contents map, present on the branch for
exactly one commit.

**The first attempt at this scoped the population wrongly**, and instructively:
it replayed the 14 commits that *modified the verifier*, on the reasonable-sounding
theory that those are the ones whose checks changed. All 14 passed — and the red
commit was not among them, because it touched only the report. **A check is
broken by edits to the thing it checks, not by edits to itself.** Filtering on
the checker excludes precisely the commits that can break it, which is the
population error this batch records three times over, made once more while
auditing for it.
---

## This bundle moved, and it was the merge that said so

The branch was cut from `origin/main` at `a00f53f20` and every figure in this
report was measured there. Main then moved **30 commits** while the lane was
open, and one of them, `506ff68c1`, established `docs/capture/<date>-<agent>/`
as the one home for a capture bundle and moved this lane's earlier snapshot
there — explicitly ruling that a bundle at the repo root does not land.

This branch was still writing to `ppa-capture/` at the root. As built, it would
not have landed, and nothing in the tree said so: the routing file, the emitted
sketches and the verifier were all internally consistent with a base that had
been superseded. What surfaced it was a status line I read wrongly and then
checked — `git rev-parse origin/jcap-ppa` disagreed with a push that said
`Everything up-to-date`, because `git fetch origin <branch>` without a refspec
writes `FETCH_HEAD` and leaves the remote-tracking ref stale. `git ls-remote`
settled it, and reading main properly is what exposed the relocation.

Three consequences, all now in the tree:

- **The bundle is at the canonical path** and UPDATES the landed one. The
  fourteen records that landed with the snapshot are a subset of those
  here; the single one not carried forward is the optional-import rule, which its
  own corpus sweep DEMOTED from Bucket A to C-2, so it survives as a C record
  rather than being dropped.
- **The routing file is a strict superset.** Main landed 8 of the 16 step entries
  from the snapshot; this branch adds the other 8. No shared entry has a
  differing value, so the merge was additive and no routing decision was
  overwritten.
- **The convention got a record.** `A-29` — three of four lanes emitted to the
  wrong directory the same night and no program knows the layout exists.

**One deliberate departure.** The convention commit chose to leave the moved
bundles' emit-time path strings as they were, reasoning that rewriting them
"would describe a run that never happened". This report rewrites them, and the
disagreement is narrow rather than a contradiction: a *documented command* is an
instruction to the reader, and `python3 ppa-capture/verify.py` is now a command
that cannot run at all. The commands here name the paths the artefacts actually
occupy, and the emit line is the exact invocation that produced the bytes in
`candidates/` — re-run at the new path, which is how they were regenerated. The
historical claim is preserved where it belongs, in this section and in `A-29`,
rather than in a command line that would fail for whoever tried it.

## A shipped record's evidence was a source screen, and it was wrong

Reading the corpus lane's second decision — *an exact path and a corpus are never
both silently accepted* — sent me back to my own record for that class. Its
shipped evidence read: **nine commands take both a single target and a collection
selector, and NOT ONE declares a mutual-exclusion group.**

That sentence is true. It is also the wrong measurement, and it took five
consecutive failed probes in one sitting to see why.

| # | probe | what it returned | why it was wrong |
|---|---|---|---|
| 1 | count refusal-shaped keywords per gate | 5–11 mentions each | counted my own vocabulary, not behaviour |
| 2 | run six gates with both selectors | rc=3 on all six | `--report` is not a flag on any of them; argparse rejected an **unknown argument**. Right answer, wrong cause |
| 3 | re-run with each gate's real flag | one gate rc=2, not 3 | its `--baseline` is a **companion** to a corpus, not a competitor — no conflict to refuse |
| 4 | grep source for the refusal mechanism | **0 of 6** had one | but I had just watched three of them refuse |
| 5 | regex the whole tree for the population | 32 commands | `--allow-*` flags are permissions, not collection selectors |

Probe 4 is the one that matters. The refusal is real; it is delegated to a shared
seam whose exit constant lives in the seam, so a per-file grep for that constant
sees nothing in any caller. **The layer's actual remedy was invisible to the
screen that declared the layer had no remedy** — and that screen is what the
record shipped.

So the population was re-measured by RUNNING all eight commands and reading the
exit code:

| outcome | count | what a caller sees |
|---|---|---|
| refuses via the shared seam, bad-invocation code | 4 (a different set) | both selectors named, and why — **the shape to copy** |
| silently picks one | 6 of 8 | a verdict about the input they did not name |
| refuses correctly, returns NOT-CHECKED | 1 of 8 | indistinguishable from "found no artefacts" |
| **returns a GREEN PASS on `Scanned 0 ICs`** | 1 of 8 | success, over zero work |

The record's substance survived — the gap is real and it is most of the
population. Its evidence did not. And the correction changed the FIX: an
implementation that adds a mutual-exclusion group, which is what the record used
to ask for, fixes six of eight and leaves the wrong-code and vacuous-pass cases
untouched. The rule has three failure shapes, not one.

Ten over-matched screens in this lane now. Nine were caught in scratch. This one
shipped, and only a sibling lane's unrelated decision note walked me back into it.

## Where two of these rules fire NEXT, now that this layer closed them

The corpus lane's note said one gate still finds its records with a filename
glob. It does not any more — it walks every JSON under the corpus and selects on
the declared schema, keeping the glob only so that a file which WAS named a
record and cannot be parsed stays in the population. *Unreadable is not absent*
is a distinction I did not have a name for and now do.

The same file carries the self-reading measurement in a comment: pointed at a
corpus, the old glob matched four files — two records and **two reports the
checker itself had written**. A report has no arms, so the gate refused its own
output with the most severe verdict it can reach. **Half that corpus verdict was
the gate marking its own paper.**

So I measured whether the layer closed it everywhere, and nearly filed a false
finding doing it:

| how the gate selects | needs an own-output exclusion? | has one |
|---|---|---|
| on a declared input schema | **no** — its report declares a different schema, so it cannot be selected | 0 of 3 |
| on a structural predicate | **yes** — its own output has the same shape | **3 of 3** |

A keyword screen reports that as *three of six gates are unguarded*. It is
wrong in the same way A-5's screen was wrong: it counts a mechanism's presence
without asking whether its absence is correct. Three of these gates cannot eat
their own output no matter what, and adding an exclusion to them would be dead
code. **The class is closed in this layer.**

Which sharpens the second half of the question both records must answer. If the
rule cannot fire again here, the different instance has to live outside — so I
went and found it. Three non-PPA commands find inputs by a semantic filename
glob and write their own JSON. The one I read through resolves its input like
this: three declared candidate paths, and when none exists, **two recursive
globs that return the first match of an unordered walk**, then `None`.

Its producer takes its output path from the caller, so there is no fixed
filename for the consumer to agree with — the guessing is not sloppiness, it is
the only thing available given the interface. That is the record about resolving
a declared path rather than guessing among candidates, standing outside the
layer it was captured in, which is the whole argument for distilling a landed
fix into a rule.

## Four classes checked this pass and deliberately NOT recorded

All four looked like records. None survived measurement, and the reasons are
different enough to be worth separating.

**A gate's exit code must be exercised through the process boundary.** The
corpus lane drives five CLIs as subprocesses and says why: the flow acts on the
exit code, and an in-process entry-point call leaves the verdict-to-exit-code
mapping unmeasured. Real rule, and this layer already obeys it — of 20 `ppa_*`
commands, **20 are driven as a subprocess somewhere in the suite.** The screen
is loose (it asks whether a test file naming the command also spawns a process),
but it is loose in the direction of over-reporting coverage, so a 20 of 20 from
it is weak evidence of a gap and adequate evidence of none. No record.

**A null count must not be read as zero.** This one is a genuine class — an
absent count means the tool did not report, not that it found nothing — and
nothing in the record set covers the CONSUMER side of it; the existing record
covers the producer emitting the null. A pattern sweep returns **37** sites
defaulting a violation-, error- or failure-named count to zero. I validated two
before believing it:

| site | verdict |
|---|---|
| a crosstalk gate reading a count out of a tool's report | **correct** — the default sits *after* an explicit presence check that reports the missing field |
| a schema gate defaulting three counts | **correct** — it is reading its own result object, in a print |

Two of two are correct, and the first is the remedy shape rather than the
defect: *check presence, then default.* So 37 is a vocabulary count, not a
defect population, and recording it would repeat the A-5 error I have now made
and caught several times over. The class stays unrecorded until somebody
measures it with a screen that can tell an external artefact from a locally
built dictionary — which is the honest statement of what is missing, and is
itself the harder half of the rule.


**A bounded search reporting nothing must state its bound.** The cross-layer
lane states it while obeying it: its refutation pass found no counterexample in
twelve cycles from reset, and it published that as *"a bounded search, not a
proof… so the difference between refuted and unproven stays visible."* Distinct
from the record this batch already carries, which separates *unproven because
the budget ended* from *unproven because the method finished* — this separates
*no counterexample within a bound* from *no counterexample*.

My screen for it returned **184 programs**, and it is the worst screen in this
batch. It matched the word *bounded* anywhere in a file, so it collected
watchdogs, docker memory helpers and two dozen protocol synthesisers. The real
population is the sites that actually invoke a bounded solver — about **seven**,
identifiable by a depth or sequence flag — and **four of those already name
their bound**.

The two remaining were not instances either, and the second is the best
illustration this batch produced:

| candidate | what it actually is |
|---|---|
| a vector generator matching `bmc` | emits a formal harness and states its mode |
| a USB-PD synthesiser matching `bmc` | **`bmc` is Biphase Mark Coding**, a line code — nothing to do with bounded model checking |

The file's own comment warns that this acronym collides and guards its matching
against exactly that. **My screen walked into the trap the file it matched was
written to avoid.** No record: the class is real, the tree has roughly seven
sites, and most of them already comply.

## Six refusals, one principle: two absences compare EQUAL

Three separate readings this pass landed on the same sentence written three
different ways, so the family is worth stating once rather than three times.

**The principle.** Wherever a verdict is reached by comparing two things, an
absence must not be an admissible value — because *two absences compare equal*,
and equality is read as agreement. A blank is not a wildcard; it is the one
value that makes any two subjects look identical.

| enforcement point | what it refuses | how I know |
|---|---|---|
| `PPA-C-007` | GROUPING two runs on an identity that is `NOT_MEASURED` | **driven** — four UNDETERMINED rows, each naming the identity it cannot support a claim about |
| `VERDICT_SENTINEL` | COMPARING a verdict metric whose value is `""` | **driven** — *"two of them compare EQUAL, so two circuits nobody compared would read as agreeing"* |
| `VERDICT_NOT_A_STRING` | the same field in the OTHER direction — a number wearing `unit: verdict` | **driven** — *"a verdict encoded as a number is a number downstream"* |
| `SCOPE_UNDECLARED` | an arm carrying a number with no scope at all | **driven, by accident** — a malformed probe of mine tripped it |
| `SCOPE_INCOMPLETE` | required scope keys absent, *"both arms declaring nothing would otherwise satisfy equality"* | cited |
| `SCOPE_SENTINEL` | required scope keys present but `null` or `""` | cited — *"State the field or omit the key."* |

**And the remedy is layered, which is the part worth copying.** One function
carries four of these, each closing the degenerate case the previous one opens:

    compare the scope dicts for EQUALITY      no blind spot by construction
      ...but both arms could declare nothing  -> require a key list
      ...but both could declare it null       -> refuse the sentinel
      ...but one could carry no scope at all  -> refuse the undeclared

Its docstring argues the first line better than I can: *a checker with three
hand-written comparisons acquires a fourth blind spot the day somebody adds a
fifth scope key, whereas requiring the dicts to be equal has none — a key that
exists is compared, and a key that does not exist yet is compared the moment it
does.*

That is the same shape as **A-3**, one level up: assert the whole structure
rather than enumerate the fields, and the guard covers what has not been
invented yet. Three of the six are logged above as ALREADY-PROGRAM claims; the
value of naming the family is that an implementer building any new comparison
now has all four layers in one place instead of rediscovering them in the order
they were originally discovered — which, judging by the three distinct code
names, is how they were.


**An emitted artefact must agree with the exit code.** The feasibility lane
states this as a defect the repository *has shipped before*: **a `--json` file
that looked clean beside an honest exit code.** Real, uncovered by any record
here — and I could not measure it, across two screens.

The first looked for a verdict-bearing key as a JSON literal: **271 of 650**
programs appeared to carry none. That screen is wrong, and I knew a
counter-example by name — most emitters serialise a dataclass, so the field is a
class declaration and not a literal. Including declarations took it to **200**.

Still not a population. Much of the 200 are *generators* whose JSON is a product
rather than a verdict, and "no verdict field" is correct for those. So I drove
one that is unambiguously a check: it exits **1** and writes
`['program', 'version', 'summary', 'findings']` — no verdict key. But its
`findings` list carries the failure, so a reader of the file alone *can* tell.
That is not the defect the lane describes.

**Zero confirmed instances, and the screen is the reason.** "Carries no verdict
key" and "looks clean while the exit code says otherwise" are different
properties, and only the second is the defect. A screen that can tell them apart
has to compare the artefact's CONTENT against the exit code — run the program
both ways and diff what it wrote — which is a fixture harness, not a grep. That
is the honest statement of what building this rule costs, and it is why no
record claims it.

## The records quote numbers and mostly do not quote the command

Found by trying to re-derive my own figures rather than by reading the brief
again, which is the only reason it was found at all.

Two records claim a count over the program tree — how many programs walk a
repository index, how many reference the split-out corpus. Re-measuring both
today gave **different numbers**. That is *not* proof they went stale: my screen
today is not the screen that produced them, and comparing counts from two
different screens is the error this batch has already recorded twice. It is
proof of something else — **I could not tell**, because the record states the
number and not the question.

    records                                            47
      fix text quotes a figure                         35
        names a literal command                         6
        states WHAT was measured and over what scope   35   (hand-read, not detected)
        states a predicate another reader could re-run  9   (the three reconstructed here, plus six that already did)

The brief is explicit about this: *the command, the number, the before and
after.* On the strict reading, 29 figure-bearing records fall short.

**That strict figure is the one I first reported, and it was wrong by half.** I
counted records "carrying a screen" by searching for the marker phrases I had
been writing — so the detector measured *my own vocabulary* and missed every
record that stated its screen in other words, including one that already carried
a full re-run *"with the screen stated above"*. Measured on the property instead
of the phrasing, the records with a bare number are **12**, not the 24 I
reported one commit ago. That is the same error this batch has now recorded
about a dozen times, committed inside the audit whose entire subject is it.

**The strict reading overstates it, and saying so is not a defence.** The
brief's operative test is what a record must let a reader do — *what it
returned, on what input* — and many records meet that without a shell line: A-40
says a corpus of one manifest-less run exits 1 and the same corpus plus an
unreadable manifest exits 2, which is an input and a return. What is missing in
those is reproducibility of the *population* figures, not of the defect.

So the honest split is: the defect measurements are mostly reproducible from
what the record says; **the population figures mostly are not**, and those are
exactly the numbers a later reader will want to re-check when the tree has
moved. Three records measured today now carry their commands, including the
detail that cost me two attempts — the run directories have to be named with the
prefix the gate's own discovery uses, or both arms read zero and the effect
vanishes.

**Four figures have now been re-derived, and the result is reassuring in a way
worth stating**, because "I could not reproduce it" is easy to mistake for "it
was wrong":

| figure | recorded | today | what moved |
|---|---:|---:|---|
| programs walking a repository index | 37 | **38** | the tree grew by one |
| programs naming the split-out corpus | 98 | **99** | the tree grew by one |
| programs directly under the program directory | 1238 | **1240** | the tree grew by two |
| gates the wiring enumeration counts | 619 | **624** | the tree grew by five |
| commands the layer presents | 19 | **20** | the tree grew by one |
| emitter sites writing a basis stamp | 16 | **15** | **does not fully reproduce — see below** |
| evidence artefacts carrying a digest | 525 of 525 | **525 of 525** | **reproduces exactly** |
| schema files in the layer's schema directory | 14 | **15** | the tree grew by one |
| document types emitted | 29 | **≥25** | a literal screen cannot settle it — see below |
| axes constant across a 21-arm sweep | 24 of 54 | **24 of 53–55** | the flagged count is exact; the denominator brackets it |

**Six re-derivations. Five are small growths and none is a screen mismatch.** The numbers
were sound; what was missing was the question that produced them. That is a
better outcome than it looked when the first two disagreed, and it is only
knowable because the screens are now written down.

**The sixth is the useful one, because it did not come out clean.** Counting the
stamp as an emitted literal gives 15 against 16 recorded. That is the right
order of magnitude and almost certainly the same question — but I cannot
attribute the difference of one. It could be a site removed; it could be my
pattern, because at least one occurrence in that file spaces the token
differently from the others. What I *can* say is that the off-by-one is *inside*
the right screen rather than *between* screens: a broader count of every mention
of the token gives 41, and every mention that is not a read or a parse gives 37,
both far enough away to prove they answer a different question. The record says
all of that rather than quietly restating 16.

One of the six is taken from the gate itself rather than counted independently,
deliberately: an independent count would have to re-derive what counts as a
gate, and a second definition of one population is exactly how two figures about
one thing begin to disagree.

**Three more were screened after that correction, and the split between what I
could fix and what I could not is the useful part.** Those three were figures I
measured myself in this pass, so the question was still in hand: the distinct
output paths in the flow document, the presence-and-absence of two hook paths,
and the axis structure read from the policy module rather than counted in
source. Writing their screens took minutes because nothing had to be
reconstructed.

The remaining **nine** were measured earlier in the batch, before screens were
being written down at all. Re-deriving them means reconstructing the question
first — which is exactly the cost this record documents, now paid at the wrong
end. **That asymmetry is the whole argument for the rule:** a screen written
beside its number costs nothing, and the same screen recovered afterwards costs
a search that may not converge, as the basis-stamp figure above shows.

**One figure reproduced exactly, and it explains which numbers need re-checking
at all.** 21 trial contracts, 525 evidence artefacts, 525 carrying a digest —
identical to the record, where every other re-derivation had drifted by one to
five. The difference is the kind of population. The drifting figures count files
in a source tree that grows; this one counts entries in **committed evidence**,
which cannot move without a commit that changes it. So a figure over published
artefacts is worth quoting without a date and a figure over a working tree is
not — which is a cheaper rule than re-checking everything.

**And one re-derivation produced a number that is smaller than the record, which
cannot be growth.** A literal match for the type identifier assigned to a
document's schema field gives 25 against 29 recorded. Fewer is not growth, so it
is the screen — and the same search shows why: many producers assign the
identifier from a module constant rather than writing it inline, so a literal
match misses them and **25 is a floor, not a count.** It is consistent with 29
and does not confirm it.

Re-deriving that side properly means resolving constants to their values, which
means reading the modules rather than grepping them. Worth knowing before
starting, **because the grep looks like it worked.** The rule itself is
unaffected: the floor already exceeds the schema count, so types without a
schema exist whichever figure is right.

**The invariance figure reconstructed further than I expected, and it corrected
the heuristic above.** Grouping every entry in the 21 published trials' flat
record files by metric identifier and counting those holding one value across
all arms gives **24** constant — identical to the record — over **53** axes when
restricted to measured records, or **55** when derived ones are admitted. The
number the rule turns on is settled; the recorded 54 sits between the two, so
the whole remaining ambiguity is one inclusion decision about derived records.

**And it breaks the direction heuristic, which needs a precondition I did not
state.** "Larger means growth" assumes the population *can* grow. This one is
committed evidence, which cannot — so a larger answer here means only a broader
screen. The heuristic misleads on exactly the artefacts that are most stable,
and the record now says so.

Two traps it cost, both this batch's own class: the contract document's metrics
key is **empty** on these arms (the measurements live in a sibling file), so a
sweep aimed at the contract returns 0 axes from 21 arms and looks like a clean
corpus.

**The last six were hand-read, and the number I have been tracking was wrong in
every one of its six revisions.** I reported the bare-number count as 24, then
12, then 9, 8, 7, 6 — each time from a phrase detector searching for the marker
words I happened to be writing. Reading the final six by hand: **none of them is
a bare number.** Every one states what was measured and the scope it was
measured over — *verified input by input… read directly*, *corpus-swept on this
tree*, *measured on this layer: 6 contract pairs*, *measured on this tree: 48
consumers*.

So the real gap was never "a number with no context". It is narrower and
harder: **a number whose exact predicate another reader could re-run.** My
detector never measured that property once, across six commits of reporting it.

**That is this batch's central class, arriving in the audit written about it,
for the fourth time** — and the correction only came from abandoning the screen
and reading six items, which took less time than any of the six re-measurements
that produced the wrong figures.

What the three full reconstructions in this pass show is what "re-runnable"
actually costs: the digest figure reproduced exactly in one attempt, the
invariance figure took four attempts and settled its load-bearing half while
bracketing its denominator, and the emitted-type figure could not be settled by
any grep because the identifiers are assigned through constants.

**So I hand-read the rest — all 35 — and the count is 3.** Not 24, 12, 9, 8, 7
or 6. Three records state a figure without saying enough about how it was taken
for another reader to re-run it. Everything else states its scope, and a good
deal of it states more than any detector I wrote ever credited:

- one decomposes **52 of 52** across three independent lanes — 29, 13 and 10 —
  so the total can be checked a lane at a time;
- one specifies the predicate as a procedure: *join backslash continuations
  first, then extract each quoted invocation, then decide acceptance from the
  program's own declared options*;
- **two say outright that the screen was validated before the figure was
  believed** — which is the standard this whole section is arguing for, already
  met, in records written before the argument existed.

**The three are named here rather than left for someone to find**, because
"three fall short" with no names is the same defect one level up:

| record | what it says | what is missing |
|---|---|---|
| ~~a scope key the producer cannot establish is omitted~~ | **closed** — reproduces exactly, by parse | needed an AST parse; a grep finds **zero** of five, see below |
| ~~layer membership is declared not inferred from a filename prefix~~ | **closed** — carries a stated, re-runnable screen | the original 32 could **not** be recovered; a supplied screen replaces it, see below |
| a verdict reachable by exhaustion must say whether it exhausted | *measured on the program and on two of its own runs* | which two runs, and what was compared across them |

**A second closed, and it reproduces exactly — but only by parsing.** The
module's eight-key scope constructor is called 5 times. Two pass a literal null
for both the corner and the clock; four pass a null clock; **three** pass a null
clock while carrying no resolved corner — two null outright, one a conditional
that yields null on the branch that matters. Three is the recorded figure,
recovered without ambiguity.

**The reusable part is why a grep cannot do it.** The nulls are *positional
arguments*, so searching for a key name beside a null finds **zero of the five**
and reads as a module with no nulls in it at all. A reader who greps here
concludes the exact opposite of the truth — which is worse than getting no
answer, and is the strongest argument in this section for stating the screen
rather than the number.

The other figure in that record, a count of refusals on one field, is **cited
from a comment in the program** rather than measured, and stays labelled that
way. A number from a comment and a number from the tree are different kinds of
claim, and collapsing them would hide which one the record rests on.

**One of the three closed earlier, and how it closed is the point.** The original
figure of 32 could not be reproduced: three readings of *a test file selecting a
population by filename prefix* gave **52** for any identifier-then-star glob,
**38** excluding the universal every-test prefix, and **17** also requiring the
source extension. The recorded 32 matches none and sits between two — so the
original scope is **lost rather than drifted**, and the tell is the magnitude: a
drift moves a figure by a few, these differ by tens in both directions.

So the record now carries a **supplied** screen rather than a recovered one —
the broad reading, 52 today — and says which it is. That is a real closure: the
figure is re-runnable by anyone now, even though the number it replaces is gone.
The broad reading is deliberate, because the rule's point is that most such
selectors are *correct* and the record's job is to size the population a
discriminator must sort, not to count defects.

I caught the naming omission re-reading my own paragraph, which is the fourth
time this section has had to correct itself and the reason it is worth as much space
as the records it audits. **That number comes from reading 35 records, not from
a screen** — which is the only reason I trust it, and it took less time than the
six re-measurements that produced the six wrong ones. A figure
without its question is a memory, which is the brief's own word for what this
loop exists to stop producing.

## Summary

**STATUS**: 47 records emitted and validated — 44 Bucket A, 2 C, 1 T, zero B,
zero D. 18 ALREADY-PROGRAM claims examined, 17 holding and 1 (F-2) disproven by
execution, each named with the program that enforces
each. All 18 findings carry a stated rule. Every claim in this document is
re-measurable by `python3 docs/capture/2026-08-21-jcap-ppa/verify.py` (51 fast + 4 authoritative). No gate
implemented, no version bumped, no baseline written, nothing pushed to main.

*This block read "15 records — 13 Bucket A" until the batch had nearly doubled
past it. It is the section a reader reads first and the last one to be checked,
because none of the twenty-one checks covered it. Check 22 does now.*

*And the eighteen ALREADY-PROGRAM claims — the part of this report that argues
something needs no work — each name the program that covers the class. Nothing
checked those programs still exist. Rename one and the sentence still reads
correctly while the class quietly stops being covered, which is **A-7**'s shape
turned on the deliverable's own reasoning. Check 24 resolves all 17 named
artefacts; all 17 are present.*

### The Bucket-A ladder, resolved four ways

The skill splits Bucket A into ALREADY-PROGRAM / EXTRACT-NEW / AUGMENT-EXISTING /
KEEP-JUDGMENT, and the implementing lane needs the split more than it needs the
bucket. My 37 resolve as:

| resolution | n | records |
|---|---:|---|
| ALREADY-PROGRAM | 18 claims, **17 hold** | not records — listed above with their enforcing program; F-2's guard is shown unfalsifiable |
| **AUGMENT-EXISTING** | 22 | A-1, A-2, A-5 … A-11, A-14 … A-21, A-23, A-24, A-26, A-27, A-28, A-29 |
| **EXTRACT-NEW** | 22 | A-3, A-4, A-13, A-22, A-25, A-30, A-31, A-32, A-33, A-34, A-35, A-36, A-37, A-38, A-39, A-40, A-41, A-42, A-43, A-44, A-45, A-46 |
| KEEP-JUDGMENT | 0 | every candidate reduced to a named predicate |

**Contention warnings for whoever applies these**, because the skill asks for
augments to be reported rather than applied by N agents in parallel. Derived from
the routing rather than remembered — the first version of this list named three
rules against one file and was already out of date by five:

    6 rules -> plugin_change_pytest_gate      A-3, A-4, A-13, A-22, A-26, A-30
    5 rules -> enhancement_emit               A-9, A-23, A-27, A-29, A-31
    4 rules -> ppa_head_to_head_check         A-2, A-5, A-11, A-35
    3 rules -> ppa_search_run                 A-7, A-8, A-19
    3 rules -> cli_exit                       A-21, A-37, A-39

* **The six test-population rules are one piece of work, not six.** A-3 and
  A-4 share a helper — the relation-derived population is the input both need,
  and computing it twice is how two answers start to disagree. A-13, A-22 and
  A-26 all want the same plumbing: a walk over the test tree that knows which
  file belongs to which layer. Build that once. **A-30 joins them**: it is the
  same question asked of a guard's inputs rather than of a test tree's
  membership, and it needs the same walk to find the assertions to inspect.
* **A third cluster has formed at the exit contract** — A-21, A-37 and A-39 all
  constrain what a command's exit code and message mean, and the check that
  derives this table is what noticed, in the same commit that created it.
* **The five emitter rules likewise.** A-9, A-23, A-27, A-29 and A-31 all
  constrain one program, and three of them constrain what it WRITES — the field
  shapes, the output location and the skeleton's signature. One pass over the
  emit path, not five.
* **A-35 joins the comparison gate's three**, making four: it adds a scope key
  the same gate must then compare on, so it is one edit with the others rather
  than a fifth pass over the same file.
* **The multi-rule files each want one pass, not several.** Apply them together or
  serialise them; three agents editing one file in parallel is the contention
  the skill's reporting rule exists to prevent.

### Corpus sweep: these fire on the current repo, and that is CORRECT

The skill's rule is that a new Bucket-A guard must run CLEAN before it ships,
because *"a guard that flags the very state you just shipped is not a guard, it's
a bug."* That rule is about **false** positives. **12 of the 13 Bucket-A rules
that existed when this was written fire on this tree, and every one is a TRUE
positive** — each names a measured defect quoted in its record. **A-7 was the one
that ran clean**, and it says so. *That ratio is dated and has NOT been
re-derived across the thirty: doing so honestly means sweeping each rule, which
is the work the table below tracks and the handoff assigns. The count of rules
whose sweep has actually been done is stated there, not estimated here.*

### Figures that name no population cannot be told apart

Three classes of prose figure have now gone stale the same way — correct when
written, falsified by the batch growing underneath them. The obvious response is
a check: scan for any figure whose denominator is a superseded value of a live
count. It was built and run:

    prose figures citing a superseded denominator            5
    of those, genuinely stale                                2
    of those, a figure about a DIFFERENT population           3

The two real ones are fixed above — a sweep row still reading `6 of 29` after its
own record had been re-measured to `10 of 33`, and a claim about "these 15
records" written when the batch was fifteen.

**The check is deliberately not wired**, and the reason is the other three. Every
false positive was a figure using the word *records* about a different set: three
records emitted by one producer, twenty-nine in-tree backlog files, a numerator
in `9 of the 33`. A gate that is wrong three times in five is a gate that gets
switched off, and this one needs the judgement *which population is this?* that a
regex cannot make.

**The program layer reached this conclusion first, and I nearly filed a defect
against it.** The shipped disclosure gate accepts a bare count, and its source
says why in a sentence that anticipates the objection exactly: *"a bare count
passes this check (it IS a denominator); the count of gates disclosing with a
number ONLY is published … because a HIT count is not a SCAN SIZE and text alone
cannot separate them."* It publishes the residual rather than pretending the
distinction does not exist:

    rc 0: 163 | disclosing: 162 (reason 140 / number-only 22) | silent: 1

So 22 of the 162 disclose with a number and no noun — the same class as the prose
figures above, measured and tracked in the program layer since before this lane
existed. **There is no gap here and no record is owed.**

Getting to that took **four consecutive instrument errors**, and they are worth
listing because every one produced a confident wrong answer about a correct
program: I grepped for the identifier where the code prints the *value*; then for
`number_only` where the output says `number-only`; then read `tail -3` of a run
whose census is on line 2; then read the JSON of the wrong population. Each time
the finding looked real. The subject was right throughout and the instrument was
wrong throughout — which is `A-27` stated as plainly as this lane can state it.

What generalises is a drafting rule, and it is the same family as the records
about docstrings and quoted counts: **a figure must name its population.**
`29 records` cannot be distinguished from a stale batch count; `29 in-tree
backlogs` can, and the staleness becomes self-evident to a reader without any
tooling. The sweep row above now reads that way.

### Which rules have actually been swept, and what happened to them

A record's measurement is of the DEFECT. A sweep measures the RULE — its false
positives. **Every row in the table below now carries a sweep.** The last nine
were run at the end of this lane, and the tally over the whole batch is that
**not one rule has ever survived its own sweep unchanged.**

**What the last nine changed, as a checklist for building.** They did not find
nine new defects; they found nine ways the rule as recorded would have produced
the wrong check, and those fall into four shapes worth handing over:

| shape | rules | what the sweep caught |
|---|---|---|
| **The check would be born vacuous** | A-19, and A-23 conditionally | the artefact the rule reads is empty in all 21 trials, so the check would open every file, compare nothing and report success. A-23's clean result holds only because this branch adds the routing entries; without them it fires nine times on a tree that was merely uninformed |
| **The check would over-flag** | A-16, A-6, A-10 | a site count demanded from a tool-scoped lever that has no sites; a static scan for relative defaults that flags correct generators; a screen for unhandled choices that flags every value passed to a callee |
| **The stated reason for exemption was false** | A-1, A-2 | both claimed freedom from false positives *by construction*, and in both one input to the set difference is derived rather than declared |
| **An objection blocking the fix dissolved** | A-17, A-18 | no absolute path is forced, so the convention can be declared without rewriting provenance; and the deleted property is outside BOTH judges, not merely unpriced |

The generalisation for whoever builds these: **a record measures a defect, and
that is not yet a buildable rule.** The gap between the two is where the check
acquires its population, its exemptions and its refusal — and on this batch that
gap was non-empty every single time it was measured.

| rule | naive | after the sweep | outcome |
|---|---:|---:|---|
| A-5 | 8 commands | 8 | re-measured by RUNNING each, after the source screen proved wrong: **6 of 8 silently pick one**, 1 refuses correctly but exits NOT-CHECKED, 1 exits **0 on `Scanned 0 ICs`**. The in-tree remedy is a **shared seam** 4 gates call, exiting bad-invocation — my earlier row credited argparse and held up the rc-2 refuser, which is itself one of the defects |
| A-7 | 560 hits | 0 | narrowed twice; **runs clean** |
| A-8 | 24 of 54 axes | 8 | narrowed; found a live defect |
| A-11 | 362 sites | 12 scanners | **rescoped**; one instance split off. **Its motivating site was fixed on main mid-lane — and the record stands**: the timing selector still picks sign-off reports by filename prefix |
| A-14 | 11 candidates | **8 confirmed** | strengthened; 3 masked, not cleared |
| A-3 | 161 floors | 36 | rescoped; `>= 1` is a different, valid assertion |
| A-4 | 32 prefix globs | needs a discriminator | **most are correct**; see below |
| A-6 | 759 of 1238 take an output path | **7 relative defaults, not all defects** | **swept**: the offending property is where a path RESOLVES at runtime, not that its default is relative — a static scan reports 7 and several are correct. Confirms the check belongs in the shared writer |
| A-10 | 29 choice sets | **0**, and 1 for the grammar form | **swept**: the rule does NOT widen to accepted-value sets generally — for a plain choice list, handled-ness is not statically decidable once a value is passed onward. Screen went 10 → 2 → 0, all mine |
| A-15 | 1 literal site | artefact-level | **check moved**; a code scan cannot answer it |
| A-16 | 5 admitted levers | **4 design-scoped, 1 tool-scoped; and 3 of 5 never searched** | **swept**: demanding a site count from all five is 1 false positive — a synthesis strategy has no sites. **Second clause**: the space publishes no field saying which admitted levers were exercised, so a consumer reads coverage of five where the run turned two |
| A-17 | 6804 absolute, **2 roots** | **0 outside a run tree** | **swept**: no absolute path is forced, so the declared-convention check has an empty false-positive population and the "rewriting breaks provenance" objection does not apply. Earlier correction stands: mixed WITHIN producers, 6804/6804 host-prefixed |
| A-19 | 21 trials | **21 empty proxy files** | **swept**: a check keyed on the cheap rung's own artefact is born vacuous — it is empty in every trial. Build from the predicted and measured orders, and make emptiness a refusal |
| A-20 | 48 lists | 30 | narrowed to those ignoring an existing declaration |
| A-21 | 18 of 19 | 1 of 2 | the 18 was argparse; 17 programs NOT measured |
| A-22 | 216 imports | 51 | narrowed to true third-party; one package, proven fatal |
| A-23 | 53 records, 3 lanes | **0 / 0** | **swept on a real population**, 23 records not mine: no unrouted step, no unwired target. Clean result is conditional on this branch's routing entries — without them 9 of 30 would be unrouted |
| A-24 | 37 gates | 98 consumers | the consumed tree is outside every one of them |
| A-25 | 29 → **38** types | 17 → **19 unschema'd** | upstream cause of A-15 and A-17, and **re-measured: the gap is widening** — nine new document types against one new schema |
| A-26 | 2 → **7** docs bound | **1215 candidates** of 4026 docstrings | re-measured: the binder is markdown-only by construction, and the population the record left unestimated is now bounded by a stated screen |
| A-27 | **12 bad screens** | 3 missed their own case | the class behind every warning above |
| A-28 | 232 single-value | 115 files | upper bound on candidates, stated as such |
| A-29 | 4 lanes | **3 wrong** | not my measurement — the convention commit's own |
| A-30 | 1 raise site | **guard cannot fail** | proven by mutation; stated over semantics, not the syntax |
| A-31 | 52 of 52 | **29 + 13 + 10** | the emitter's own template, across three lanes; not one step takes those inputs |
| A-32 | 5 identities | **1 states its rule** | the prohibition exists in bold, one identity over, in the same section |
| A-33 | 3 knobs, **0 synthesis actuators** | **6 of 9 staged files** carry a hand-written disclosure | the correct fact, in the one place no consumer parses |
| A-34 | 2 runs, 3.8 s and 1795 s | **identical JSON** | the depth field exists for the other half of the method |
| A-35 | 1 required scope key, 5 carried | **0 name the composition** | one component IS named — `fill` — and the rest are not |
| A-36 | declaration honoured verbatim | **0 satisfiability checks** | and the producible set is not declared anywhere, so build that first |
| A-37 | 23 **marked** refusals | **0 carry a remedy** | survived its control — and its denominator is the marked subset, blind to unmarked refusals by construction |
| A-38 | 3 null-emitting sites | **44 recorded refusals** | the doc forbids it in bold, the gate refuses it, a sibling module already fixed it |
| A-39 | 20 entry points | **15 unguarded** | an escaped exception exits on the finding code; 5 siblings already guard it |
| A-40 | 8 aggregation sites | **3 unguarded** | rc 2 outranks rc 1 by integer order; CONFIRMED by execution — adding a run took a corpus from rc 1 to rc 2 |
| A-41 | 138 gate output paths | **2 confirmed** | a gate's output path equals a producer's; the overwrite is documented in the producer's own source and repaired after the fact |
| A-42 | 3 tracked-set generators | **2 unguarded** | guards the query FAILING but not the query answering about the previous commit |
| A-43 | 3 tests reference the hook | **0 assert installation** | the tracked hook is present, the installed one is absent, and 9 pushes this batch went ungated |
| A-44 | 14 reduce-to-one sites | **4 unsorted** | the same glob is sorted in one program and unsorted in another; a repaired instance let a nested snapshot certify the outer project |
| A-45 | 6 multi-group axes | **5 mix kinds** | 1 equivalence argument exists and it covers the one pair that does not mix; a SATISFIED group beats an UNDETERMINED one |
| A-46 | 650 verdict emitters | **≤36 stamp a tree** | a brief that was right about an unfetchable tree cost a full remote-ref sweep and a scratch reconstruction to adjudicate |
| C-2 | 131 handlers | 0 confirmed | **DEMOTED out of Bucket A** |
| A-1 | 34 names | **26 declared, 8 derived** | **swept, and it overturns the row**: 3 of 4 registries are declared tables; timing composes its 8 from three format strings, and a missed expansion is a false positive shaped like a finding |
| A-2 | 3 axes | **1 declared** | **swept, and it overturns the row**: FP-free by construction needs BOTH sides declared; only timing declares its emitted keys, power declares one, area none |
| A-9 | 29 → **33** in-tree backlogs | 6 → **10** offenders | swept during construction, then RE-MEASURED after the merge; the 4 new offenders are the sibling capture lanes |
| A-13 | 47 pairs | 6 | swept during construction; unusable until the generic token was excluded |

In every case the discriminator was invisible from the defect that motivated the
rule, and in three of them a naive screen missed the motivating case itself.
That is the argument for the sweep being mandatory rather than advisory.

**Five of the six sweeps were mis-measured on the first attempt, by me, in this
lane.** A prefix match pulled every permission flag into A-5's population (34 for
9). A greedy multi-line match bled a boilerplate block into A-14's (47 for 11),
and confining it to one line then reported 0. A-7's verb matched a path three
paragraphs away (560 for 0). A-11's literal-argument screen missed a pattern held
in a constant. And A-14's invocation test cleared cases argparse had merely
*masked* — one error is reported, so a missing required argument hides an
unrecognized flag, which is why 4 confirmed became 8 once the required arguments
were supplied. **Every rule here will be built by someone writing the same screen
I wrote.** Each `fix_action` now names the specific way its own screen goes
wrong.

**Every Bucket-A rule is swept or accounted for, and the table above now lists
all fourteen** rather than only the ones with dramatic numbers — a reader should
not have to reconcile prose against a partial table. Ten were swept outright.
A-1 and A-2 are false-positive-free by construction — a set difference over
declared tables cannot invent a member. A-9 and A-13 were swept during
construction: A-9's 6-of-29 IS its sweep, and A-13 required the generic-token
exclusion before it produced a usable number at all.

Three of the last four changed what the record says:

* **A-4 needs a discriminator the record did not have.** 32 test files select by
  filename prefix and MOST ARE CORRECT — the universal prefix meaning *every
  test* is the right selector for a suite-wide property. The rule fires only
  where a prefix stands in for a SEMANTIC SUBSET, which is where a naming
  convention and a boundary can drift apart.
* **A-6 is clean where the record puts it, and only there.** No program in the
  shared writer's population writes into the installed tree, so no false
  positives. But the tree's two real in-tree regenerators live at repository
  root, outside that population, and neither imports the writer. The same
  predicate on a broader hook would catch them, and they are legitimate.
* **A-10 guards a population of one.** Exactly one pattern of that shape exists.
  The defect is live and thrice-confirmed and worth fixing; as a *guard* its
  value is the next one, not this one. Saying so is the honest measure.

The failure mode to avoid is therefore the opposite of the usual one: an
implementer who reads "must run clean" and narrows a correct guard until the tree
goes green has deleted the finding, not shipped the fix. **Fix the defect the
guard names; do not tune the guard to stop naming it.** The clean-run requirement
applies from the commit that fixes the last true positive onward.

### Dual-track, which every one of these owes

The skill binds every NEW deterministic gate to ship with (a) **evidence
emission** — the measured value, the excerpt, the count it judged on, so a second
track can re-judge the same input — and (b) a **named AI cross-check plus a
converge step**, run even when the program says PASS. A verdict with no attached
evidence cannot be cross-checked and is incomplete.

It applies to all 13 Bucket-A records, and is stated here rather than in each
`fix_action`. **That is a deliberate call with a cost**, so it is written down:
`recoveries.json` is the machine-readable artefact an implementer reads, and a
requirement living only in this prose can be missed. The concrete form is the
same sentence for every rule — emit the table, the count and the excerpt the
verdict was computed from — so repeating it fourteen times would add no
information while making each `fix_action` harder to read for the part that IS
specific to it.

### The Bucket-T roadmap the skill binds me to could not be written

The skill says every Bucket-T item must be added to
`benchmark-data/ic/OSS_EDA_FORK_ROADMAP.md`. **That path does not exist in this
repository** — `benchmark-data/` was split to a repository of its own, so the
instruction points across a boundary this branch cannot reach. T-1 therefore
carries its full attribution block in the emitted backlog and is NOT in the
roadmap. Whoever lands it must add the roadmap entry in the other repository, or
the instruction should be repointed. Recording the non-compliance, rather than
satisfying the letter of it by creating a local file nothing reads.

### The 4th distill target was considered and is empty

`agents/ic_expert_db/ic_expert_db.json` holds generalizable design-CLASS CRAFT
keyed by IC class. **None of these 33 records routes there** — re-derived, not carried: the 33 route to 18 distinct programs and not one is the expert DB. **The reason is
structural rather than an oversight:** every one is about the FLOW — a gate's
vocabulary, a producer/consumer seam, an exit code, a population guard — and none
is knowledge about what makes a class of circuit correct. Recording the empty
route so the next reader can see it was asked rather than skipped.

## Next

**This bundle ships in two pieces, and the split is a batch decision, not a
technical one.** The branch that carries it into the current batch was FROZEN
while the batch was being assembled — ten of sixteen member branches had moved
within two hours, so every re-merge invalidated the report describing it. The
frozen branch holds 44 records and 19 already-program claims, and it verifies
`rc 0` on its own tree; that is what lands.

Everything measured after the freeze is on **`next/ppa-capture-followups`**,
which branches from the frozen tip and rides the following batch. It is not
merged into the frozen branch:

| after the freeze | |
|---|---|
| new records | **A-44** (a search reduced to one result without counting it), **A-45** (whichever proof group has data decides the verdict) |
| new already-program claim | the twentieth — an empty value is not a value, because two empties compare equal |
| refinements to frozen records | **two** — A-5 gains the demonstration its count was missing, A-36 gains a detector needing no second source |
| new synthesis | the six-refusals family, and two classes checked and deliberately NOT recorded |

The three staleness guards in the verifier — the introducing-sentence count, the
stated check count, and the per-record reading cost — are **in the frozen
branch**, not here. I wrote otherwise in the first draft of this paragraph and
checked it against the frozen tip before shipping, which is the only reason it
does not say so still.

**If you are reading the frozen bundle, it does not know this branch exists**; if
you are reading this one, the counts here are the larger set.


**Before landing, run this — and read its exit code, not its output:**

    python3 docs/capture/2026-08-21-jcap-ppa/verify.py            54 checks   exit 0 = every claim holds
    python3 docs/capture/2026-08-21-jcap-ppa/verify.py --slow     + 4 authoritative checks (gate runs and the quoted pytest figures)

That instruction is here because I learned it the expensive way in this lane: I
once ran the verifier *after* the commit in the same command chain, and a failing
state reached the branch for one commit. A check whose result arrives after the
push did not run in time. Anything that edits this document — including a
reviewer fixing a typo in a heading — can break the contents map, the STATUS
counts, or a record-to-section link, and the command says which.

**`verify.py` is UNWIRED, which is A-23 applied to this batch's own tooling.**
Nothing invokes it — measured, not assumed — so by the standard this batch
records, it is a check that produces no verdict. I could not wire it:
`tools/ci/repo_hygiene_gates.sh` is one of 47 pinned protected paths, and
editing a protected path is the class **A-3**'s neighbouring record shows cannot
be landed by re-pinning in place. So it is stated rather than quietly left:
**whoever lands this adds one line to the hygiene gates**, and until they do,
every claim in this document is re-measurable only by someone who remembers to
run the command.

    python3 docs/capture/2026-08-21-jcap-ppa/verify.py     54 checks, exit 0 = every claim holds
    python3 docs/capture/2026-08-21-jcap-ppa/verify.py --slow   + 4 authoritative checks (gate runs and the quoted pytest figures)

**It was held to the two invocation properties this batch records about other
people's tools.** A-14 is about a documented command that does not run, and A-6
about a command that writes into the installed tree; both apply to a script
handed to a lander who will invoke it from wherever they happen to be:

    run from the repository root, the lane directory, the marketplace
      directory and an unrelated temporary directory        rc 0 in all four
    run from INSIDE the installed programs directory        rc 0, and the
      working tree carries the same zero entries afterwards

Cwd-independence comes from resolving every path against the script's own
location rather than the caller's, and the one temporary file it needs — the
malformed backlog its sanitiser control requires — is created and removed inside
a temporary directory.

*Both lines were re-run after the bundle moved, because the move is exactly what
breaks this kind of claim, and it did: the script built every plugin path from
`HERE.parent`, which was the repository root only while the bundle sat at the
root. Three levels down, every plugin-facing check died on a path with
`docs/capture/` spliced into the middle of it. It now resolves the root by
walking up to a marker instead of counting `..`, which is the fix its own A-6
neighbour describes. The control that should have caught it could not: it
asserted a deliberately-absent filename was absent, which is true under a wrong
root too. It now also asserts a known directory resolves.* A verifier that fails from the wrong directory, or leaves
a file behind, would be an instance of two of the records it is verifying.

### The work, in order

Work through it in sequence. Step 1 gates the rest.

1. **Run the verifier** (above). Read the exit code.
2. **Implement the 29 Bucket-A rules** — a separate lane, per the brief. Take
   `pattern` and `fix_action` from `docs/capture/2026-08-21-jcap-ppa/recoveries.json`; the sketches in
   `docs/capture/2026-08-21-jcap-ppa/candidates/` are already filed beside the program that owns each
   fix, and each `fix_action` names the specific way its own screen goes wrong.
   **Start with A-13** (it names a live seam nobody has looked at) and **A-1**
   (one axis is unanswerable today, so no candidate can ever be promoted).
   **Build the five test-population rules as one piece of work**, per the
   contention list above.
3. **All nine previously unswept rules are now swept — and not one survived
   unchanged.** Two overturned their own row, one bounded a rule's scope, one
   settled where a check belongs, one unblocked a repair, one found a false
   positive the rule would produce on its own motivating document, one showed a
   check would be born vacuous, and one passed on a population twice this batch.
   The base rate for sweeping is now 9 of 9; sweep any rule this batch gains.
 **Four of the nine are now swept**, and the yield argues for
   the rest: two overturned their own row, one survived on a population twice
   the batch, and one settled a design question the record had argued on
   reasoning alone. **A-1 and A-2 were two of the nine and have now
   been swept. Both overturned their own row, and for the same reason**: each
   claimed freedom from false positives *by construction*, on the ground that a
   set difference cannot invent a member — and in both cases one input to the
   difference is not a declared table but something a check must DERIVE. A-2's
   emitted-key side is declared for one of three axes; A-1's timing names are
   composed from three format strings. A missed derivation drops a member and
   the rule reports an absence that is not there, which is a false positive
   wearing the shape of a finding. **Treat "FP-free by construction" as a
   hypothesis to test, not a reason to skip the test** — it has now been wrong
   twice out of twice. Thirteen sweeps
   changed ten rules and demoted one out of its bucket; the base rate says expect
   change.
4. **Wire the verifier** — one line in the pinned hygiene gates, which this lane
   could not touch. **Verified, not assumed**: the landing manifest carries 47
   protected paths and `tools/ci/repo_hygiene_gates.sh` is one of them, declared
   with the `authority` role. The same check confirms the other direction — no
   entry covers `docs/capture`, so this bundle's own path is freely landable and
   the only thing needing an owner's hand is that one line.
5. **File the Bucket-T roadmap entry** in `benchmark-data/`, the repository this
   branch cannot reach — but **not before attaching the crash artefacts**. The
   ten committed bad samples do not contain the crash: three JSON files each, no
   log, no error file, and a runner exit of 1 that the golden arm also records,
   so nothing in the tree distinguishes them from a passing run. A maintainer
   receiving them can reproduce nothing. **The evidence cannot be found, only
   remade**: the two run trees the records' provenance paths point at are both
   gone from this host, checked. So attaching the tool's exit status, its stderr
   tail and the post-route netlist means **re-running one crashing arm** — budget
   that, rather than going searching. This is `A-15` as a precondition rather
   than a lesson, and as the clearest statement of its cost: the rule reads like
   tidiness right up until the window closes.
6. Then **proceed to** the **Bucket-C provenance plumbing**, which is the precondition for the
   header rule and the reason that record is C rather than A.

**Two things are outstanding that are not on the numbered list, because neither
is this lane's to close.**

- **F-2's guard cannot fail, and the fix it guards has already landed.** That is
  the worst combination: the class reads as covered, the code is currently
  correct, and a regression would be silent. `A-30` is the rule; the concrete
  repair is to stop `driver_for` supplying a generic reason, or to assert against
  each module's own attribute rather than the accessor's return.
- **Three sibling capture lanes have backlogs on `main` that its own validator
  rejects.** Measured while re-checking `A-9`: in-tree backlogs failing the
  component rule went from 6 of 29 to **10 of 33**, and all four new failures came
  from the bundles landed by `506ff68c1`. Those files are outside this branch, so
  they are reported rather than touched.

**F-16 is settled, not outstanding**: the post-layout equivalence failure is the
step's own setup, not the forked tool — the runner's helper documents the abort
and calls it a false tool-error. It is mentioned only because an earlier version
of this section sent readers to reopen it.
