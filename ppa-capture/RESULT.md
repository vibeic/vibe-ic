# The PPA cluster, DISTILLED — 29 records, and the sixteen rules that were already programs

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
| **A** | 26 | deterministic rules — the default, and every one names its predicate |
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

    always relative   opensta · yosys · signoff
    always absolute   openroad · power

**The split is perfectly per producer** — so it is invisible from inside any one
of them, each being flawlessly consistent with itself, and it is exactly the
two-authors-one-interface shape this whole cluster is about. **Every one of the
6867 absolute paths embeds a host home directory**, in a field a reader trusts as
neutral.

The existing portability guard cannot see any of it: it walks emitted scripts by
file suffix (`.tcl`, `.sh`) and never opens a record. So the F-14 class was fixed
for scripts and left standing for records, which is the same rule at a different
artefact class — the pattern this lane keeps finding.
**(o)** yes. **(d)** yes — it is per producer per field, so it re-answers for the
next producer added and for any other provenance field the record gains.

### A-18 · a lever that deletes a design property must be priced or the winner is a trade · `ppa.pareto`

The published winner of the 60-arm sweep won partly by **deleting all ten of the
design's spare ECO cells**. The report decomposes the move exactly:

    default -> winner                   6594 -> 6136 um2      -6.95 %
      of which, density 0.30 -> 0.60    6594 -> 6291          -4.60 %   real
      of which, spare 0.02 -> 0.00      6291 -> 6136          -2.46 %   a trade

So roughly a third of the headline win is paid for in metal-only ECO readiness,
and the preserving candidate is a **different arm** — 2.4 % worse on the
objective and whole on the property.

**The ranking layer cannot express any of this.** The word for that property does
not appear anywhere in the search or frontier modules — zero mentions. The lever
is exposed by the runner, the objective does not price it, so the optimum sits at
the setting that removes it, monotonically, and the ranking reports a straight
win.

**Two separate lanes computed the distinction by hand and put it in prose** — one
naming the preserving arm as "the winner a design that wants design-for-ECO
should read", the other making an ECO-preserving winner its own headline
category. Two independent hand-computations of the same missing term is the
evidence that the layer owes it.
**(o)** yes. **(d)** yes — it is per declared property, so it covers the next
lever whose range includes switching something off.

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
seventh time in this lane a screen has measured something adjacent to its
subject.
**(o)** yes. **(d)** yes — a known-verdict invocation per command covers every
command the layer gains.

### A-22 · a third-party import at test module scope must be guarded or it aborts collection · `repo.test_population`

The tests lane found **two** files importing PyYAML at module scope with no
guard and judged them latent, the host having the package. The count is what
makes it worth doing:

    module-scope third-party imports in the test tree, unguarded   51
    distinct packages involved                                      1

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
packages and reports 216 — the eighth over-match in this lane.
**(o)** yes. **(d)** yes — it is per test module per import, so it covers the
next optional dependency the suite adopts.

### A-23 · a distilled rule must be routed into a program some verdict consults · `capture.emit`

A lane's note about unwired gates raised a question about **this deliverable**:
routing picks the program that *owns* the subject, which is the right criterion
for correctness and says nothing about whether anything **runs** it. A rule in a
program no verdict consults is silent forever — and worse than an unwritten one,
because the record asserts the class is now covered.

The tree already maintains the other half of the join:

    gates 619   unwired 61 (baseline 59)   newly unwired 3

and one of the three newly unwired is a program of **this very layer**, so the
bad pairing was reachable rather than hypothetical.

Checked, and the batch passes:

    Bucket-A records            26     (22 when the rule was written)
    distinct target programs    16
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

    programs walking a repository index                       37
    programs referencing the split-out tree by name           98
    the tree present in this repository                       NO
    declared as a submodule                                   NO  (module list empty)
    resolved instead by                                       an environment variable
    the hygiene gate is invoked with                          this repository's root only

The tree was moved out, the product still consumes it in 98 places, and **every
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

At least 17, because the matching errs toward reporting a schema as present. The
type the lane asked about is among them, and so are the bundle, the sign-off
record set, the frontier and the evidence manifest.

**This is an upstream cause, not a peer of the other records.** Two findings
already in this batch reduce to it:

* **A-15** — a tool-error verdict carries no diagnostic, and *"there is no schema
  for the artefact, which is why nothing requires the field"*;
* **A-17** — two producers resolve a provenance convention in opposite
  directions, with nothing to state which is meant.

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
| `ppa-crosslayer/RESULT.md` | read: §5–§10 and the requests |
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
could plausibly care about a new top-level directory and 17 added routing
entries. All three were run on this branch AND with the routing file reverted to
its base content, then the outputs compared:

| gate | base | head | comparison |
|---|---|---|---|
| tracked JSON/YAML parses | — | **rc 0** | clean on this branch |
| gate is wired | rc 1, unwired 61 (baseline 59) | rc 1, unwired 61 | **name sets identical** |
| checker execution wiring | rc 1 | rc 1 | **output byte-identical** |

The two red gates are **pre-existing on main** and this branch moves neither —
not the count, not the names, not a byte of the report. The 17 routing entries
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

    Bucket-A records                          26
    shortest fix_action                       > 300 characters
    genuinely missing a rubric element         0

**And the check itself is A-27's worked example, twice over.** The first run
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
the patterns were unchecked by anything. Over **all 29 records**:

    pairs compared                      406
    maximum similarity                 0.38
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

    rule definitions in the sketches                 26
    resolving to a section by name, before           20
    resolving after                                  26

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

    $ python3 ppa-capture/verify.py
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
again in silence. **Twenty-seven checks now, plus an authoritative mode**, the last of them the one that closes the loop:
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
---

## Summary

**STATUS**: 29 records emitted and validated — 26 Bucket A, 2 C, 1 T, zero B,
zero D. 16 rules found ALREADY-PROGRAM and named with the program that enforces
each. All 18 findings carry a stated rule. Every claim in this document is
re-measurable by `python3 ppa-capture/verify.py` (27 fast + 1 authoritative). No gate
implemented, no version bumped, no baseline written, nothing pushed to main.

*This block read "15 records — 13 Bucket A" until the batch had nearly doubled
past it. It is the section a reader reads first and the last one to be checked,
because none of the twenty-one checks covered it. Check 22 does now.*

*And the sixteen ALREADY-PROGRAM claims — the part of this report that argues
something needs no work — each name the program that covers the class. Nothing
checked those programs still exist. Rename one and the sentence still reads
correctly while the class quietly stops being covered, which is **A-7**'s shape
turned on the deliverable's own reasoning. Check 24 resolves all 17 named
artefacts; all 17 are present.*

### The Bucket-A ladder, resolved four ways

The skill splits Bucket A into ALREADY-PROGRAM / EXTRACT-NEW / AUGMENT-EXISTING /
KEEP-JUDGMENT, and the implementing lane needs the split more than it needs the
bucket. My 26 resolve as:

| resolution | n | records |
|---|---:|---|
| ALREADY-PROGRAM | 16 | not records — listed above with their enforcing program |
| **AUGMENT-EXISTING** | 21 | A-1, A-2, A-5 … A-11, A-14 … A-21, A-23, A-24, A-26, A-27 |
| **EXTRACT-NEW** | 5 | A-3, A-4, A-13, A-22, A-25 |
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
| A-17 | — | 6867 / 6674 | split is perfectly per producer; all 6867 host-prefixed |
| A-18 | — | 0 mentions | the ranking layer has no word for the property it deletes |
| A-19 | — | order INVERTED | the cheap rung's top candidate places third |
| A-20 | 48 lists | 30 | narrowed to those ignoring an existing declaration |
| A-21 | 18 of 19 | 1 of 2 | the 18 was argparse; 17 programs NOT measured |
| A-22 | 216 imports | 51 | narrowed to true third-party; one package, proven fatal |
| A-23 | — | 0 of 26 | **re-run as the batch grew; still passes** |
| A-24 | 37 gates | 98 consumers | the consumed tree is outside every one of them |
| A-25 | 29 types | **17 unschema'd** | upstream cause of A-15 and A-17 |
| A-26 | 2 docs bound | 0 docstrings | 1 expired claim confirmed; population NOT estimated |
| A-27 | **12 bad screens** | 3 missed their own case | the class behind every warning above |
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

**`verify.py` is UNWIRED, which is A-23 applied to this batch's own tooling.**
Nothing invokes it — measured, not assumed — so by the standard this batch
records, it is a check that produces no verdict. I could not wire it:
`tools/ci/repo_hygiene_gates.sh` is one of 47 pinned protected paths, and
editing a protected path is the class **A-3**'s neighbouring record shows cannot
be landed by re-pinning in place. So it is stated rather than quietly left:
**whoever lands this adds one line to the hygiene gates**, and until they do,
every claim in this document is re-measurable only by someone who remembers to
run the command.

    python3 ppa-capture/verify.py     27 checks, exit 0 = every claim holds
    python3 ppa-capture/verify.py --slow   + the authoritative wiring run

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
a temporary directory. A verifier that fails from the wrong directory, or leaves
a file behind, would be an instance of two of the records it is verifying.

**Next: implement the 13 Bucket-A rules** — a separate lane, per the brief. Take
`pattern` and `fix_action` from `ppa-capture/recoveries.json`; the emitted
sketches in `ppa-capture/candidates/` are already filed beside the program that
owns each fix. Start with **A-13** (it names a live seam nobody has looked at)
and **A-1** (one axis is unanswerable today, so no candidate can be promoted).

Then **proceed to** the two items this lane could not close: F-16's
tool-versus-invocation question, which needs one reproduction retaining the
tool's stderr; and the Bucket-C provenance plumbing, which is the precondition
for the header rule.
