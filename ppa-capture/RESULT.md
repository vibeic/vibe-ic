# The PPA cluster, DISTILLED — 18 records, and the sixteen rules that were already programs

The twenty-odd lanes that converged on the measurement layer all captured. None
distilled. This lane turns that cluster into records the next blind run can be
gated by, and it is honest about the largest single finding: **eleven of the
eighteen end-to-end findings are already enforced by a shipped program or a
general census test, and were fixed between the run that found them and this
tree.** Add the smaller `jsonschema` item, which is not one of the eighteen, and
four more classes drawn from the six lane records, and the count is
**11 + 1 + 4 = 16**. Those sixteen produced no record; duplicating them would be
worse than skipping them.

Two of the sixteen are marked *conditional* rather than clean. The brief's test
for a landed fix — can the class recur in a module nobody has touched? — is
really a question about whether the guard's population is DISCOVERED or
DECLARED, and theirs is declared. Both are flagged in the table and folded into
**A-3**.

Tree distilled against: `origin/main` @ `a00f53f20`, plugin **v1.11.66**.
Sources: `ppa-e2e/FINDINGS.md` (F-1..F-18), `ppa-e2e/RESULT.md` (13 requests),
`ppa-crosslayer/RESULT.md` (10 requests), and six lane records in
`/tmp/capture_lanes/`.

    python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py \
        --records ppa-capture/recoveries.json --out-dir ppa-capture/candidates

Accepted with no refusal and no unrouted record.

## Count per bucket

| bucket | n | |
|---|---:|---|
| **T** | 1 | forked place-and-route tool faults after its own route completes |
| **A** | 15 | deterministic rules — the default, and every one names its predicate |
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
| 14 | Nothing that enters a hash identity may carry a path that differs between runs of the same configuration. | program |
| 15 | An axis must prove from the names its evidence actually prints, or declare itself unprovable — not from a name no artefact emits. | program |
| 16 | A proof must name the artefact the downstream consumer consumed; a proof about an upstream intermediate does not satisfy an axis scoped to the final one. | program; the tool error behind it is **unsettled** |
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
| F-2 `--backend` drove nothing | the driver seam in `_ppa/backends/__init__.py` (`extract_records` / `NO_DRIVER_REASON`); `test_ppa_producer_consumer_agreement.py::test_every_backend_is_drivable_or_says_WHY_NOT` | **conditionally.** The census iterates a literal 5-tuple, not the package. `load()` imports directly, so a sixth module IS drivable — it is just invisible to the guard and to the alternatives a refusal prints. See **A-3** |
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

Four more classes, drawn from the six lane records rather than from the 18, are
also ALREADY-PROGRAM. Each was a candidate record until I opened the program:

| class | already enforced by |
|---|---|
| a PASS must say how much it looked at | `programs/gate_discloses_denominator_check.py` — a shipped gate over a 493-program population, with four measured walking bugs in its own header |
| a gate that read NOTHING must not exit 0 | `programs/gate_zero_denominator_refuses_check.py` — and its header states exactly why the first gate does not imply it, which is the distinction I would otherwise have re-derived |
| a bad invocation is 3, and asking for `--help` is not a bad invocation | `programs/_ppa/cli_exit.py` reads the exit code rather than catching the type; `test_ppa_layer_exit_contract.py` carries BOTH arms — the two are one defect from opposite sides, so a suite testing one manufactures the other |
| a present-but-empty population is never a pass | `tests/test_ppa_layer_vacuous_population.py` — the right question, on 8 of 19 programs; the coverage gap is recorded under **A-3**, not as a class of its own |

Three more are fixed on this tree but their guard is the fix itself, and the
CLASS is what this lane recorded instead:

| F | fixed by | record written for the class |
|---|---|---|
| F-6 sign-off reports carry no basis stamp | the multi-corner emitters stamp it (`phase3_one_shot_runner.py:34476, 35159`) | folded into the C record: a header derived from inputs, not written as a literal |
| F-7 power measured before place-and-route | `_emit_power_report(basis=...)` derives every header line from what it linked | **A-8** (the invariance, which is the stronger evidence) and **C-1** (the header rule) |
| F-12 the search hard-wires the stub, and the stub's reason is false | `--feasibility-policy` plus `STUB_REASON_CONTRADICTED_BY_TREE` | **A-7**, generalised off that one string |

Four are LIVE on this tree, measured today:

| F | measured now | record |
|---|---|---|
| F-3 axes with no producer | 8 of 9 gained one (`_ppa/signoff.py`, 8 metric names). **`drv` still has none** — all four of its proof names are produced by nothing anywhere in the tree | **A-1** |
| F-8 power scope short of its required keys | process / voltage / temperature now filled from the liberty stem; **`mode` still absent**, so the comparison still refuses on both arms | **A-2** |
| F-17 the reliability report supports no count | the READER is now honest (a verdict outside the enum maps to not-measured with the token quoted) and a ratio proof was added; the axis is still undetermined on a default run | folded into **A-1** |
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

## The twelve records

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

**(o)** yes. **(d)** yes, and in the direction a floor can never see — an entry
left behind for a member since deleted.

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
bad-invocation. Both take the one-line shared fix the others already use.
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

**This rule runs CLEAN on the tree today — the only one of the thirteen
Bucket-A rules that does.** Its motivating instance was fixed at its one site. It is worth having
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

**(o)** yes. **(d)** yes — it is a census of a vocabulary against a pattern, so
it also catches the harder direction: a branch that works today and dies when
the vocabulary gains a separator.

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

### C-2 · an optional dependency needs a version matrix — **demoted from Bucket A by its own sweep**

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

> **why_not_bucket_a**: A program cannot decide this from the source — I built
> the static check four ways and every one over-reported, and every survivor I
> could execute behaved correctly. The input that would settle it, the dependency
> installed at an older release, does not exist on the host at check time, and no
> amount of reading the code conjures it. Producing that input is a version
> matrix in CI, and that is the engineering.

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

### C-1 · a generated report header must be derived from the inputs the session opened · `phase3.sta`

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

### T-1 · post-route repair faults after routing completes · `phase3.pnr_setup_repair` · OpenROAD

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
**(o)** yes — the samples ARE the original, retained.
**(d)** the enhancement is stated as a behaviour, not as a patch to these ten
inputs: the stage must exit non-zero with a named diagnostic on any instance it
cannot repair, so a different netlist shape that reaches the same fault is
covered by the same acceptance criterion.

---

## One change outside `ppa-capture/`

`benchmark/CAPTURE_ROUTING.json` gains **eight** steps. Without them every
record here emits UNROUTED — a routing table that cannot express the layer it is
asked to route — and the emitter's own warning says to add the entry.

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
`tests/test_issue1130_wiring_population_parity.py` (18 passed).

No gate is implemented. No version bumped. No baseline written. Nothing pushed
to main.

## Where each record came from

| source named in the brief | records it produced |
|---|---|
| `ppa-e2e/FINDINGS.md` F-1..F-18 | A-1, A-2, A-6, A-7, A-8, C-1 — and eleven ALREADY-PROGRAM |
| `ppa-e2e/RESULT.md` (13 requests) | folded into the above. Paid on this tree: **1, 2, 4, 5, 6, 8, 10, 11, 12**. Partly paid: **3** (8 of 9 axes gained a producer), **9** (three of four scope keys), **13** (host paths yes, the reliability count and the relative output path no). **7** was answered with a DIFFERENT fix than the one requested — the source artefact was not put in the scope; instead the index learned to tell corroboration from conflict, which settles the fatal half and leaves two genuinely disagreeing artefacts refused, on purpose |
| `ppa-crosslayer/RESULT.md` (10 requests) | T-1; and it is the evidence that F-3 went 0 → 6 axes and that `drv` is the one left |
| `jrc_ppa-layer-rc-contract` | A-3, A-4 |
| `jcorpus_ppa-corpus-mode` | A-5, A-11 |
| `agent_jppa-tests` | A-12; and the fourth-instance measurement under A-3 |
| `agent_jppafeas-feasibility-producers` | A-1, A-2 |
| `jrecords_record-shape-reconcile` | the producer-census instance under A-3 |
| `jreq_lander-three` | its three requests are landed; nothing left to distil |
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

---

## Summary

**STATUS**: 15 records emitted and validated — 13 Bucket A, 1 C, 1 T, zero B,
zero D. 16 rules found ALREADY-PROGRAM and named with the program that enforces
each. All 18 findings carry a stated rule. No gate implemented, no version
bumped, no baseline written, nothing pushed to main.

### The Bucket-A ladder, resolved four ways

The skill splits Bucket A into ALREADY-PROGRAM / EXTRACT-NEW / AUGMENT-EXISTING /
KEEP-JUDGMENT, and the implementing lane needs the split more than it needs the
bucket. My 13 resolve as:

| resolution | n | records |
|---|---:|---|
| ALREADY-PROGRAM | 16 | not records — listed above with their enforcing program |
| **AUGMENT-EXISTING** | 10 | A-1, A-2, A-5, A-6, A-7, A-8, A-9, A-10, A-11, A-14 |
| **EXTRACT-NEW** | 3 | A-3, A-4, A-13 |
| KEEP-JUDGMENT | 0 | every candidate reduced to a named predicate |

**Two conflict warnings for whoever applies these**, because the skill asks for
augments to be reported rather than applied by N agents in parallel:

* **A-2, A-5 and A-11 all edit `ppa_head_to_head_check.py`.** Three rules, one
  file. Apply them together or serialise them.
* **A-3 and A-4 share a helper** — the relation-derived population is the input
  both need, and computing it twice is how the two answers start to disagree.
  A-13 wants the same test-population plumbing, so all three want one new
  program, not three.

### Corpus sweep: these fire on the current repo, and that is CORRECT

The skill's rule is that a new Bucket-A guard must run CLEAN before it ships,
because *"a guard that flags the very state you just shipped is not a guard, it's
a bug."* That rule is about **false** positives. **12 of these 13 Bucket-A rules
fire on this tree today, and every one of them is a TRUE positive** — each names a measured
defect quoted in its record. **A-7 is the one that runs clean**, and it says so.

### Which rules have actually been swept, and what happened to them

A record's measurement is of the DEFECT. A sweep measures the RULE — its false
positives. **Four rules have been swept. Not one survived unchanged.**

| rule | naive | after the sweep | outcome |
|---|---:|---:|---|
| A-5 | 34 commands | 9 | rescoped; **0 of the 9 guard**, nothing to narrow |
| A-7 | 560 hits | 0 | narrowed twice; **runs clean** |
| A-8 | 24 of 54 axes | 8 | narrowed; found a live defect |
| A-11 | 362 sites | 12 scanners | **rescoped**; one instance split off |
| A-14 | 11 candidates | **8 confirmed** | strengthened; 3 masked, not cleared |
| A-3 | 161 floors | 36 | rescoped; `>= 1` is a different, valid assertion |
| A-4 | 32 prefix globs | needs a discriminator | **most are correct**; see below |
| A-6 | — | 0 false positives | clean **where the record puts it**; placement warning |
| A-10 | — | population of **1** | real defect, but the guard protects one site |
| A-15 | 1 literal site | artefact-level | **check moved**; a code scan cannot answer it |
| A-16 | — | 5 admitted, 0 counted | verified on the published document |
| C-2 | 131 handlers | 0 confirmed | **DEMOTED out of Bucket A** |
| A-1 | — | n/a | FP-free by construction: a set difference cannot invent a member |
| A-2 | — | n/a | FP-free by construction, same reason |
| A-9 | 29 records | 6 offenders | swept during construction; 6 of 29 IS its sweep |
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
keyed by IC class. **None of these 15 records routes there, and the reason is
structural rather than an oversight:** every one is about the FLOW — a gate's
vocabulary, a producer/consumer seam, an exit code, a population guard — and none
is knowledge about what makes a class of circuit correct. Recording the empty
route so the next reader can see it was asked rather than skipped.

## Next

**Next: implement the 13 Bucket-A rules** — a separate lane, per the brief. Take
`pattern` and `fix_action` from `ppa-capture/recoveries.json`; the emitted
sketches in `ppa-capture/candidates/` are already filed beside the program that
owns each fix. Start with **A-13** (it names a live seam nobody has looked at)
and **A-1** (one axis is unanswerable today, so no candidate can be promoted).

Then **proceed to** the two items this lane could not close: F-16's
tool-versus-invocation question, which needs one reproduction retaining the
tool's stderr; and the Bucket-C provenance plumbing, which is the precondition
for the header rule.
