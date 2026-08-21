# The PPA cluster, DISTILLED — 12 records, and the eleven rules that were already programs

The twenty-odd lanes that converged on the measurement layer all captured. None
distilled. This lane turns that cluster into records the next blind run can be
gated by, and it is honest about the largest single finding: **eleven of the
eighteen end-to-end findings are already enforced by a shipped program or a
general census test, and were fixed between the run that found them and this
tree.** Those eleven produced no record. Duplicating them would be worse than
skipping them.

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
| **A** | 10 | deterministic rules — the default, and every one names its predicate |
| **B** | **0** | see below: no candidate survived the "name the undecidable decision" test |
| **C** | 1 | the predicate is trivial; the provenance plumbing it must read is not |
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

## The eighteen, and what is true on this tree

Eleven are ALREADY-PROGRAM. For each, the program or census test that enforces
it now — checked by reading it, not by trusting the fix note.

| F | already enforced by | general over |
|---|---|---|
| F-1 no owner for the excluded levers | `crosslayer_search_space.py` emits `UNOWNED` when the named owner does not resolve; `tests/test_ppa_pnr_search_space.py:340,362` has both arms | any deferral; the owner is resolved from the tree |
| F-2 `--backend` drove nothing | the driver seam in `_ppa/backends/__init__.py` (`extract_records` / `NO_DRIVER_REASON`); `test_ppa_producer_consumer_agreement.py::test_every_backend_is_drivable_or_says_WHY_NOT` | every backend module, the day it is added |
| F-4 producers emit envelopes the consumer refuses | `_ppa/metrics.py:963-965` registers all three carriers; `test_ppa_producer_consumer_agreement.py` §2 walks the whole envelope namespace | every registered envelope |
| F-5 declared unit vs required unit | `_ppa/area.py:188` moved to the name-derived unit; same test file §1 walks the whole area registry | every area metric, added or existing |
| F-9 two readings of one metric under one scope | `_ppa/metrics.py:582-676` separates corroboration from conflict; `test_ppa_second_record_identity.py`, 12 tests | any second record under one identity |
| F-10 every timing row emitted twice | `_ppa/timing.discover_reports` de-duplicates by CONTENT; `test_ppa_layer_timing_view_dedup.py` | any mirrored artefact tree; `path_ordinal` covers F-10b |
| F-11 `required_views` is global | `_ppa/feasibility.required_views_by_axis`; `test_ppa_feasibility_views_and_slack.py`, 6 tests | per-axis, including the empty-list and unknown-key cases |
| F-13 no rule for the `analysis` identity | `docs/PPA_INTERFACES.md` §3 states it in bold; `PPA-C-016` names the misfiled artefacts | any hash identity over an emitted artefact |
| F-14 absolute host paths in emitted scripts | `programs/emitted_script_portability_check.py` — a shipped gate, `26 of 34` on the run that produced it | every emitted analysis deck |
| F-15 no artefact prints a hold `wns` | `_ppa/feasibility.py:227-228` — the hold axis proves from the worst-slack name too | both timing axes, both proof groups |
| F-18 a count is demanded where the schema allows a status | `_ppa/benchmark.py` `CHECK_CLEAN` / `VERDICT_CLEAN`; `test_ppa_verdict_and_scope_shapes.py` | every floor check, verdict-valued or count-valued |
| (smaller) `jsonschema` not a dependency | `_ppa/jsonschema_bundled.py` — bundled, so a stock host is covered | and it names the 3.2.0 case the import guard missed |

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

---

## The twelve records

Every one carries the command and the number. The two questions the skill exists
for are answered per record: **(o)** would it have fired on the original defect,
**(d)** would it fire on a different instance of the class.

### A-1 · gate proof vocabulary has a producer · `ppa.feasibility`

    $ python3 -c "…union the producers' name tables; diff against the axis proofs…"
    drv  ['timing.drv.max_cap_violations', 'timing.drv.max_fanout_violations',
          'timing.drv.max_tran_violations', 'timing.drv.violations']   0 producers

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

The comparison gate requires six scope keys for the power axis
(`_ppa/benchmark.py:199`); the producer emits five (`_ppa/power.py:452-472`
fills three of the four it was missing and leaves one). Measured by the
cross-layer lane: `h2h_B` refuses `rc=2 SCOPE_INCOMPLETE`, naming the one key,
on both arms, before any value is compared.
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
**(o)** yes. **(d)** yes — it goes in the shared atomic writer, so it covers
every tool that takes an output path, not the one that was caught.

### A-7 · a published absence claim is rechecked against the tree · `ppa.search`

The stub published, verbatim into every manifest of a 60-arm sweep:

    "feasibility lane not wired: _ppa/feasibility.py has not landed"

The module had landed three commits before the program that published the
sentence. Now guarded for that one string; the class — a provenance note
asserting a named artefact is absent — is not.
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
**(o)** yes, and it would have fired on arm 2 rather than on arm 60.
**(d)** yes — it is a distinct-value count against a distinct-identity count, so
it fires on any axis whose session reads upstream of the lever. Two arms make it
non-vacuous, so it must not be gated behind a minimum sweep size; the record
says a one-arm sweep is skipped and SAYS it was skipped.

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
**(o)** yes. **(d)** yes — it is a census of a vocabulary against a pattern, so
it also catches the harder direction: a branch that works today and dies when
the vocabulary gains a separator.

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

`benchmark/CAPTURE_ROUTING.json` gains four steps — `ppa.feasibility`,
`ppa.head_to_head`, `ppa.search`, `ppa.artefact_write` — pointing at the
programs that own the fixes. Without them every PPA record emits UNROUTED, which
is a routing table that cannot express the layer it is asked to route; the
emitter's own warning says to add the entry. `tests/test_capture_routing_consistency.py`
and `tests/test_enhancement_emit.py` pass (69 passed, 4 skipped), as does
`tests/test_issue1130_wiring_population_parity.py` (18 passed).

No gate is implemented. No version bumped. No baseline written. Nothing pushed
to main.

## The one thing I could not settle

**F-16 — post-layout equivalence returns a tool error.** The consumer side is
already correct and general: `_ppa/signoff.read_equivalence` refuses a proof
whose gate netlist is not the one that became the layout, and
`lec_post_layout_check.py` is a shipped gate for exactly this. What remains is
that the run itself reports `yosys did not produce a parseable output`. I could
not establish from the evidence whether that is the forked tool or the
invocation, and Bucket T requires that answer — a T record naming the wrong
layer sends the fix to the wrong repository. It is stated here rather than
filed, and it needs one reproduction with the tool's own stderr retained.
