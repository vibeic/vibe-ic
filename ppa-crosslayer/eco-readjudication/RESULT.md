# ECO-readiness is a feasibility axis, not a column

**The correction this answers, verbatim:** *"why you delete ECO backup, that is
for ECO-ready design, you should not delete them."*

It is right, and the gap was real. Spare/ECO cells are what make a bug found
after tape-out fixable by a **metal-only ECO**. Delete them and the only
remaining repair is a base-layer respin — a new mask set. For a tape-out-bound
design their removal is not a trade to be weighed against area; it removes a
property the design is required to have.

The published cross-layer search already knew this and said so **in prose**:
`ppa-crosslayer/RESULT.md` writes that the PnR-only winner bought "one third …
[by] **deleting every spare ECO cell**". Nothing turned that sentence into a
verdict. The spare count was a column in a table, and a column is something a
reader has to notice.

---

## 1. The axis, and where the requirement is declared

### 1.1 The axis

`_ppa/feasibility.py` gains a tenth axis, `eco_readiness`, beside setup, hold,
drv, drc, lvs, antenna, ir, em and equivalence. A candidate whose declared
spare/ECO population is not met is **INFEASIBLE**, exactly as a candidate with a
DRC violation is — `FeasibilityResult.eligible_for_promotion` is False and no
number on any other axis can outweigh it, because the promotion gate reads no
number that could be made large enough.

Three pieces of machinery were needed and each is small:

| addition | why |
|---|---|
| `KIND_LIMIT_MIN` proof kind | Every existing kind expressed *zero violations*, *non-negative slack* or *at most a declared ceiling*. A spare population violates by being **too small**, and the gate could not express a floor at all. |
| `AXIS_NOT_APPLICABLE` status | Every other axis always applies — a routed design owes a DRC answer. This one does not, and "no requirement was declared" is neither a pass (SATISFIED) nor a hole (UNDETERMINED). |
| `FeasibilityPolicy.eco_requirement` | The design's declaration, carried **verbatim**. Not a row in `limits`, because `limits` answers *what number* and this answers *is there a requirement at all* — and an absent limit and a declared-zero limit are precisely the two states this axis exists to keep apart. |

### 1.2 Where the requirement is declared

In the design's own contract, as an `eco_readiness` block:

```json
"eco_readiness": {
  "required": true,
  "min_spare_cells": 10,
  "min_spare_cells_by_kind": {"inverter": 3, "nand2": 2, "nor2": 2,
                              "mux2": 1, "aoi": 1, "dff": 1},
  "min_distinct_positions": 3,
  "require_tie_off": true
}
```

`policy_from_document` reads it and passes it through unnormalised;
`eco_requirement_state` is the single reader. **No program in this repository
contains a spare count or a spare density.**
`test_no_spare_count_or_density_is_hard_coded_in_the_gate` measures that over
the gate's own AST — every numeric literal in the ECO section, allowed set
`{0, 1}` — rather than asserting it in a docstring.

**Only what the declaration asks for is proved.** A declaration that names no
kinds produces no per-kind proof; one that does not require tie-off produces no
tie-off proof. A gate that also checked the obligations nobody declared would be
inventing requirements, which is the same defect as inventing a threshold.

### 1.3 The seven applicability states — and why none of them collapse

The brief asks that a design which declares none is **NOT_APPLICABLE**, and that
*the record says which of the two it is*. The lander's ruling then supplied the
predicate that decides what an **absent** declaration means: not a new
declaration, but the route the flow took (§1.5). Together they give seven:

| state | code | axis status | what it means |
|---|---|---|---|
| `REQUIRED` | — | SATISFIED / VIOLATED / UNDETERMINED | A requirement was stated; adjudicated against the candidate's own records. |
| `NOT_REQUIRED` | `FEAS_ECO_NOT_REQUIRED` | NOT_APPLICABLE | `required: false`. **Somebody decided.** |
| `NOT_REQUIRED` on the chip path | `FEAS_ECO_OPTED_OUT_ON_CHIP_PATH` | NOT_APPLICABLE | The same decision, made by a design that is tape-out-bound. Still not overruled — but it is the move somebody would make to get around this axis, so it does not share a code with an opt-out by an IP. |
| `UNREADABLE` | `FEAS_ECO_DECLARATION_UNREADABLE` / `FEAS_ECO_REQUIREMENT_EMPTY` | **UNDETERMINED** | A requirement was stated and cannot be parsed, or says `required: true` and then states nothing checkable. Refused, never waived. |
| `NOT_DECLARED_ON_CHIP_PATH` | `FEAS_ECO_NOT_DECLARED_ON_CHIP_PATH` | **UNDETERMINED** | Nothing declared, and the flow routed this design to the chip terminal. **[CANNOT CHECK], never a silent pass.** |
| `NOT_APPLICABLE_ON_IP_PATH` | `FEAS_ECO_NOT_APPLICABLE_ON_IP_PATH` | NOT_APPLICABLE | Nothing declared, and the design terminates at `37.5ip`. A hardmacro delivery owes no spare population of its own; the die that integrates it does. |
| `PATH_UNDETERMINED` | `FEAS_ECO_PATH_UNDETERMINED` | **UNDETERMINED** | Nothing declared, and no route was established — no router artefact, both at once, or a flow that could not be read. **A design that has not been shown to be an IP delivery must not be treated as one.** |
| `NOT_DECLARED` | `FEAS_ECO_NOT_DECLARED` | NOT_APPLICABLE | Nothing declared **and no project supplied**. Nobody asked. Distinct from every row above, because those are findings about a design and this is the absence of a question. |

The row is on **every** verdict, including the NOT_APPLICABLE ones. An absent
row reads as a satisfied one, which is the failure being fixed.

**A declaration wins wherever it speaks.** The route decides what an *absent*
declaration means and nothing else — an IP that declares it wants spares in its
own macro is held to that, on any path
(`test_M_PATH_6_a_declaration_still_wins_on_either_path`).

### 1.5 Tape-out-bound is the ROUTE, not a declaration

The first version of this work left one hole and said so:
`--eco-declaration` was opt-in, so a tape-out-bound run that simply omitted it
got NOT_APPLICABLE — the pre-fix behaviour, silently. The gate had moved the
problem, not solved it. **The lander's ruling closed it**, and the predicate is
one a design cannot accidentally omit:

> a design routed onto the CHIP path (`0.5ic → 15.5ic → 26.5ic → 37.5ic`) **is**
> tape-out-bound; a design that terminates at `37.5ip` is an IP/hardmacro
> delivery and is not. Do not infer it from the presence of a GDS or from the
> PDK; infer it from the route the flow took.

`_ppa/delivery_path.py` implements exactly that, and it does **not** glob for
router artefacts. It loads the flow document, finds steps `37.5ic` and `37.5ip`,
and drives `flow_compliance_check._check_condition` over the project tree with
**their** conditions — so a renamed router artefact or a fourth route reaches
this module instead of leaving it describing an older flow.
`test_positive_the_predicate_is_the_flows_own_and_is_run_not_retyped` asserts
the conditions used are literally the flow's.

It answers six ways, and only one of them is `CHIP`:

| answer | meaning |
|---|---|
| `CHIP` | `37.5ic`'s condition is met — self tape-out **or** shuttle. Tape-out-bound. |
| `IP` | `37.5ip`'s condition is met. Not tape-out-bound. |
| `BOTH` | Both at once. No silicon corresponds to it; this module will not pick one. |
| `NOT_DETERMINED` | No router artefact. 0.5ic never ran, or ran and the design did not say what it is. |
| `UNREADABLE` | The flow or the tree could not be read. |
| `NOT_SUPPLIED` | Nobody asked. **Not** a finding about the design. |

`is_tapeout_bound()` is a function precisely so that no caller spells the
comparison itself and quietly folds `NOT_DETERMINED` into it. And the search
space tests `!= IP` rather than `== CHIP` — only a design **proven** to
terminate at the hardmacro delivery gets an unbounded spare lever; the other
three non-CHIP answers are routes nobody established, and treating them as IP
is the same guess in a different coat.

The GDS/PDK inference the ruling forbids is made impossible rather than merely
avoided: `test_M_PATH_2_a_gds_and_a_real_pdk_do_not_make_a_design_tapeout_bound`
builds a tree with a streamed GDS and a real PDK and no router artefact, and
asserts `NOT_DETERMINED`.

### 1.6 The axis proves from the flow's own artefacts

An axis nothing produces evidence for reads UNDETERMINED on every real run
however good the design is. That is not a hypothetical: it is the state seven of
the nine physical axes were in before `ppa_signoff_records.py`, in that
program's own words — *"a run that measured DRC, LVS, antenna, IR, EM and LEC
and passed every one of them still adjudicated UNDETERMINED; the evidence
existed and nothing could reach it."*

`eco_readiness` arrived in exactly that state, and it is fixed in the same
place. `ppa_signoff_records.py` — what the flow runs, and what produces the
bundle the gate reads — now also emits the design-for-ECO rows from
`phase3/stage3/pnr/spare_cells.json` and, when the run carries one,
`reports/spare_preservation.json`.

**It does not re-read those artefacts.** `ppa_eco_spare_records.py` already
does, and it holds rules that took measurement to get right: a plan whose
`count` disagrees with its own `instances` list is INVALID *and so is every row
derived from that list*; a missing plan is NOT_MEASURED and never a zero; a
`NO_WITNESS` preservation report vouches for nothing. A second reader would be a
second copy of those rules, and the first time the two disagreed a design would
pass one gate and fail the other with nobody able to say which was right. So the
signoff program owns **where the flow writes them** and the producer owns **what
they say** — and `test_wired_M_the_bundle_has_exactly_one_reader_of_the_spare_plan`
measures that split over the signoff program's AST, with docstrings excluded
(the file's own prose names the keys it refuses to parse, which is how it
explains the rule) and with the detector shown to fire against the reader that
*does* name them.

Measured end to end on a run tree carrying only a spare plan:

```
$ ppa_signoff_records.py <run> --json bundle.json
ppa_signoff_records: 20 record(s), 11 MEASURED, 9 NOT_MEASURED
  MEASURED     design_for_eco.spares.count
  MEASURED     design_for_eco.spares.kind.dff.count        (and six more kinds)
  MEASURED     design_for_eco.spares.distinct_positions.count
  MEASURED     design_for_eco.spares.tie_off.verdict
  MEASURED     design_for_eco.spare_pads.count
  NOT_MEASURED design_for_eco.spares.surviving.count

$ ppa_feasibility_check.py --candidates <bundle + declaration>
  eco_readiness: SATISFIED
```

and the same tree with `--spare-density 0` gives VIOLATED, while a tree with no
plan at all gives UNDETERMINED with every row present and value-less.

### 1.7 Absent is not zero

The producer, `ppa_eco_spare_records.py`, turns the flow's own
`phase3/stage3/pnr/spare_cells.json` into canonical `vibeic.ppa.metric.v1`
records. A plan that is missing, unreadable or not an object produces
`NOT_MEASURED` rows carrying the reason and **no `value` key at all** — never
`count: 0`. The gate then reads UNDETERMINED, and the candidate is not
promotable and not convicted.

`test_M_ECO_2_absent_and_zero_do_not_produce_the_same_verdict` is the
bidirectional pair: absent → UNDETERMINED, measured zero → INFEASIBLE. If those
two ever agree, one of them is wrong.

One case is sharper than it looks. A plan saying `count: 10` while listing zero
`instances` is **INVALID** — somebody looked and the artefact cannot answer —
and *every* row derived from that instance list (kinds, positions, tie-off) is
INVALID too. Marking only the total INVALID and then reporting "0 inverters" off
the same list would convict the design on evidence the producer has just said it
does not believe.

---

## 2. Re-adjudication of the five published runs

The five arms landed on main in **v1.11.66**, so `MANIFEST.json` pins the
**in-tree** published records by sha256 — twenty files — and `readjudicate.py`
verifies every one before it reads a number. (An earlier revision of this
directory carried byte-for-byte copies under `inputs/`, from when the arms were
on an unmerged branch. That was 964 KB of duplicated published record and, worse,
a digest pin that protected the *copy* instead of the record. The copies are
gone.) **No published record is edited.** The published `candidates.json` carried
no ECO metric because no producer existed; the ECO records are emitted from each
arm's own published `spare_cells.json` and appended to a **copy**.

```
$ python3 ppa-crosslayer/eco-readjudication/readjudicate.py
trial  spares  eco(declared)  verdict       eco(no decl,    eco(no decl,
                                            no route)       CHIP route)
b000       10  SATISFIED      UNDETERMINED  NOT_APPLICABLE  UNDETERMINED
p04         0  VIOLATED       INFEASIBLE    NOT_APPLICABLE  UNDETERMINED
u01         0  VIOLATED       INFEASIBLE    NOT_APPLICABLE  UNDETERMINED
z21         0  VIOLATED       INFEASIBLE    NOT_APPLICABLE  UNDETERMINED
z23        10  SATISFIED      UNDETERMINED  NOT_APPLICABLE  UNDETERMINED
```

**Read the last two columns together — that pair is the hole, and the hole
closed.** Both are the same records with the *same absent declaration*. Without
a route, every arm reads NOT_APPLICABLE and the set passes on this axis: that is
the pre-ruling behaviour, and it is a silent pass. With the CHIP route, every
arm reads UNDETERMINED — **including `b000` and `z23`, which kept all ten
spares.** That is correct and it is the point: on the chip path, a design that
declared no ECO requirement cannot be *said* to be repairable, and ten spares
nobody specified is not evidence that ten was enough. The run makes no finding
instead of a flattering one.

The CHIP route in that column is **supplied**, not measured: the five arms' run
directories no longer exist, so no tree could be routed. `summary.json` says so
in the same words rather than letting the column read as a measurement of these
five projects. The design's `L2` names a primary tape-out target, which is why
CHIP is the route it would have taken.

Against the published numbers (`ppa-crosslayer/RESULT.md`, area
`area.design_report.um2` @ `post_route`):

| run | area µm² | post-route power W | spares | published verdict | verdict through the axis |
|---|---:|---:|---:|---|---|
| shipped default `b000` | 6594 | 0.000573 | 10 | UNDETERMINED | UNDETERMINED (eco **SATISFIED**) |
| PnR-only winner `p04` | 6136 (−6.95 %) | 0.000559 | 0 | UNDETERMINED | **INFEASIBLE** |
| cross-layer objective `u01` | 5941 (−9.90 %) | 0.000747 | 0 | UNDETERMINED | **INFEASIBLE** |
| cross-layer Pareto `z21` | 6011 (−8.84 %) | 0.000545 | 0 | UNDETERMINED | **INFEASIBLE** |
| cross-layer ECO-preserving `z23` | 6106 (−7.40 %) | 0.000541 | 10 | UNDETERMINED | UNDETERMINED (eco **SATISFIED**) |

**`u01` and `z21` become INFEASIBLE for a tape-out-bound design and `z23` does
not.** That is the finding the brief asked for, and `p04` — the published
PnR-only winner, the bar everything else was measured against — falls with them.

### Three things about that table that must not be glossed

**1. `z23` is not FEASIBLE; it is UNDETERMINED, and it was UNDETERMINED before
any of this.** All five arms were already UNDETERMINED in their published
reports because `em` and `equivalence` were never established on those runs.
**Every one of the nine published axis statuses is identical before and after**
— `readjudicate.py` compares them against each arm's own published
`feasibility_report.json` and refuses with rc=2 if any of them moves, so
`pre_existing_axes_unchanged: true` in `out/summary.json` is a measurement and
not a claim. What the axis changes
for `z23` is not its verdict but its *record*: it now carries a positive,
evidenced ECO-readiness finding instead of a number in a column. What it changes
for `p04`/`u01`/`z21` is the verdict itself: per candidate a measured VIOLATION
outranks an unmeasured axis, so INFEASIBLE replaces UNDETERMINED.

**2. The control column is what makes the first one mean anything.** The
`no_declaration` arm is the *same records* with no `eco_readiness` block, and
every arm reads NOT_APPLICABLE. So the refusals come from the **design's stated
requirement**, not from a rule that fires on every design regardless — which
would be a gate nobody could ever satisfy and equally useless.
`test_M_ECO_6_the_declaration_is_what_refuses_not_the_gate_itself` pins it.

**3. The declaration is authored, and the design declares nothing.** The
design's own `input/docs/L1..L9` contain **no** design-for-ECO requirement. The
declaration used here is written in
`declaration/tapeout_bound.json`, argued line by line from the repository's own
`skills/design-for-eco/SKILL.md` (≈1–5 % density band starting ≈2–3 %; the
inverter / nand2 / nor2 / dff / mux2 / aoi / oai mix; mandatory tie-off; spatial
distribution). It is **not** inferred from the baseline run — a requirement read
off a baseline says only "do what you already did" and can never be wrong. That
the shipped default happens to carry exactly this population is a coincidence
worth reporting and not the derivation.

That absence is itself the root cause. **Nothing the search could read said the
spare population was required**, so nothing stopped an arm deleting it — and the
axis alone, without a route, says NOT_APPLICABLE and lets all five through. That
is the last column of the table above, and it is why the axis needed the route:
the requirement can be missing, but the *route* cannot.

---

## 3. What I could NOT measure about ECO-readiness, and why

Rule 3 of the brief: the count is not the whole property. Every applicable axis
row carries these in `applicability.not_proved`, so the disclosure travels with
the verdict rather than living here.

**Measured, from the flow's own artefacts:**

| fact | metric | how |
|---|---|---|
| population | `design_for_eco.spares.count` | the plan's `count`, cross-checked against its own `instances` list |
| kind mix | `design_for_eco.spares.kind.<kind>.count` | counted from `instances`; a kind absent from the list has none, and that zero **is** a measurement because the list is the population |
| spatial spread | `design_for_eco.spares.distinct_positions.count` | distinct `(llx, lly)`, via `spare_cell_coverage_check.compute_distribution` — the *same function* the step-18 readiness gate uses, so two gates cannot disagree about what a position is |
| tie-off | `design_for_eco.spares.tie_off.verdict` | the plan's `tie_off` block, which already distinguishes "not measured" from "measured false" |
| reserved pads | `design_for_eco.spare_pads.count` | reported on every arm (all read 0); not required by this declaration |

**Not measured, and why — unconditionally, on every applicable row:**

* **`eco_reachability`.** Whether a metal-only ECO could actually route from a
  given failing net to a given spare depends on the routing resources left
  around **both**, and nothing this flow emits is a routability answer.
  *Distinct placement positions is a spread PROXY and the record says so.* Ten
  spares at ten distinct positions may still all be unreachable from the net
  that needs repairing. This is the largest gap and it is the honest one: the
  axis proves the spares exist, are of the declared kinds, are spread and are
  tied off. It does not prove they are usable.
* **`kind_sufficiency`.** Whether this mix can implement the repairs the design
  will actually need is a judgement about future bugs. The axis checks the mix
  against the declaration and makes no claim the declaration is the right mix.
* **`post_eco_timing`.** Whether a repair built from these spares would still
  meet timing is a question for STA over an ECO netlist that does not exist.

**Not measured on THESE five runs specifically:**

* **`design_for_eco.spares.surviving.count` — survival to the shipped
  artefacts.** This is the fact that actually bears on a post-tape-out repair:
  the insertion count says what the placer put down, and every pass after it
  (CTS, hold fixing, routing, ECO, metal fill) could have stripped them. The
  producer emits it from `reports/spare_preservation.json`, and the declaration
  can require it with `require_preservation: true`. **None of the five published
  arms carries a preservation report**, so on all five the record is
  NOT_MEASURED with that reason, and this declaration does not require it —
  requiring evidence that does not exist would have made all five UNDETERMINED
  and said nothing about any of them. So what §2 establishes is that `z23`
  **inserted** its ten spares and `u01`/`z21`/`p04` inserted none. It does not
  establish that `z23` **shipped** them.

---

## 4. Does the spare-deleting knob belong in the search space at all?

The knob is `spare_cell_density`, applied by `phase3_one_shot_runner.py`'s
`--spare-density`, normalised by `_compute_spare_density` with
`_SPARE_DENSITY_MIN = 0.0`. `ppa_pnr_search_space.py` admitted it — correctly,
because `--spare-density` really is on the runner's CLI — and its own row then
said:

> `0 disables spare insertion, which is a legitimate arm of a search and not the
> same as leaving the flag out`

**The answer: the lever stays, and its domain does not.**

That sentence is not wrong; it is **unconditional**. Disabling spare insertion
is a legitimate arm for a design that has declared it needs no spare population.
For a design that has **declared** one, zero is not a point in the space: it is a
full place-and-route run spent producing a candidate the promotion gate must
refuse. Raising the density is a real search direction — more ECO headroom for
more area — so removing the lever would remove a legitimate dimension to fix an
illegitimate value. What was wrong was not that the knob was searchable; it was
that it was **unbounded below**.

So `ppa_pnr_search_space.py` gains `--eco-declaration`, and with a requirement:

* the lever is admitted with status **`BOUNDED_BELOW`**, not `EXPOSED`;
* any value the runner would **apply** as 0 is refused, rc=1, with the
  declaration cited. The check runs *after* the normaliser round-trip, so `-1`
   — which the runner silently clamps to 0 — is refused too;
* the row publishes the floor, and states what it did **not** enforce: a
  declared floor is a **count** and this lever is a **density**; converting one
  to the other needs the design's placed-cell count, a property of a run that
  has not happened. So a positive density cannot be refused here, and the row
  names `_ppa/feasibility.py`'s `eco_readiness` axis as what enforces the count
  downstream instead of implying it checked;
* a declaration that was **named and could not be read** is rc=2 and **no space
  is published**. Publishing an unbounded space from an unreadable requirement
  is exactly how a search comes to visit the value the requirement forbade;
* `NOT_SUPPLIED` (nobody told this program) and `NOT_REQUIRED` (the design says
  it needs none) are separate states, and neither is silence;
* `audit_space` gains `_audit_eco_floor`, so a bounded lever that fails to
  publish its floor — or publishes a domain that still offers zero — is a
  self-audit failure and not a quiet omission.

The parse is `_ppa/feasibility.eco_requirement_state`, imported. There is
deliberately **not** a second parser: the space and the gate must not drift
apart about what "this design requires spares" means.

**And `--eco-declaration` is no longer optional where it matters.** With
`--project`, the route decides: a design the flow put anywhere other than the
`37.5ip` terminal, with no ECO declaration, is rc=2 and **no space is
published**. Only a design *proven* to terminate at the hardmacro delivery gets
the unbounded lever. Passing no `--project` at all stays rc=0 — nobody asked this
program about a tree, and inventing a refusal from a question nobody put is not
the same as refusing to guess at an answer.

```
chip tree,  no declaration  -> rc=2, no space written
unrouted tree, no decl      -> rc=2, no space written   (not shown to be IP)
both routers,  no decl      -> rc=2, no space written
--project points at a file  -> rc=2, no space written
IP tree,    no declaration  -> rc=0, space written, lever unbounded
no --project                -> rc=0, space written, row says NOT_SUPPLIED
chip tree,  with declaration-> rc=0, space written, lever BOUNDED_BELOW
```

This is the stronger half of the fix, exactly as the brief says: it stops the
candidate being generated rather than catching it after. It is also, on its own,
insufficient — `--eco-declaration` is opt-in, which is §5's first request.

---

## 5. Verification

```
tests/test_ppa_eco_readiness_axis.py    41 passed
tests/test_ppa_eco_delivery_path.py     23 passed, 1 xfailed
```

Arms, per the brief: **positive** (a met requirement is FEASIBLE; the row states
what it did not prove; a design that declares none is not failing; the two ways
of declaring none do not share a code), **negative** (a deleted population, a
wrong kind mix, floating inputs, and the CLI at rc=1), **VACUOUS** (no evidence
at all; a NOT_MEASURED count; `required: true` with nothing checkable; a
declaration that is not an object; the producer on a missing plan emitting no
zero; and the end-to-end join where that absence must survive into the verdict),
**bad invocation** (rc=3 and never 2, for the producer and the space; `--help`
still 0), and **nine mutation arms** M-ECO-1…9 including the measured defect
itself, the absent-vs-zero pair, two waiver mutations, the self-contradicting
plan, the negative control, and three on the search space. Five further tests cover the
`require_preservation` obligation: survived, stripped-after-insertion (where the
insertion count still reads ten and the refusal comes from the shipped
artefacts), required-but-never-measured, not-asked-for-and-disclosed, and a
`NO_WITNESS` preservation report that must not vouch for anything.

The delivery-path suite carries its own arms: **positive** (both chip routes —
self tape-out and shuttle — resolve to CHIP; the hardmacro terminal does not;
the predicate really is the flow's own conditions), **negative** (the chip path
with no declaration is UNDETERMINED, an unestablished route is refused, and the
same end to end through the CLI on a real tree), **vacuous** (no project is not
a finding about the design; a project that is not a directory; the search space
publishing no space at all for a chip tree it cannot bound), and **seven
mutation arms** M-PATH-1…7 — the route alone flipping the verdict with records
and declaration held identical, the forbidden GDS/PDK inference, the both-routers
tree, the three findings never sharing a verdict, the two path vocabularies
agreeing, a declaration still winning on either path, and the control that the
space still publishes for a proven IP delivery.

Seven more cover the **wiring** (§1.6): the bundle carries the ECO evidence, a
real run tree satisfies the axis, a run that deleted its spares violates it, a
run with no plan is UNDETERMINED with every row present and value-less,
preservation is read when the report exists (ten inserted and nine shipped is
VIOLATED against a floor of ten), the one-reader split is measured over the
AST, and an ECO-only tree is still refused by the gate because nine axes have no
evidence in it.

The bad-invocation arm for `--project` found a **pre-existing defect**:
`ppa_feasibility_check.py --help` exits 3 instead of 0 — asking a program what
its flags are is not a bad invocation. It reproduces on `origin/main`, its
one-line fix is `_ppa/cli_exit.parse_or_refuse`, and
`test_ppa_layer_exit_contract._XFAIL_HELP` already pins it `strict=True` under a
stated contract: *the fix and the pin's removal land together, by the lane that
owns them*. Fixing it here would turn that file red and leave someone else's pin
to clean up, so this branch **records** it as its own strict xfail rather than
asserting around it, and REQUESTS names it.

Two source-level guards: the gate's ECO section carries no numeric literal
outside `{0, 1}` (measured over its AST), and the producer names no requirement
at all. `plugin_full_audit.py` D1 + D2 pass, and `source_chip_agnostic_check.py`
passes over 1546 files.

Wider PPA surface, `pytest -k "ppa or spare or feasib or agnostic or
path_step"`: **2519 passed, 13 failed**. All thirteen fail **identically, by
test id**, on `origin/main` at `a00f53f20` (v1.11.66) in a clean detached
worktree — `test_ppa_layer_exit_contract`,
`test_ppa_layer_internal_error_is_not_a_finding`,
`test_ppa_layer_timing_view_dedup`, `test_ppa_runner_extraction_ledger`.
**Zero new red.**

Two of those layer sweeps went red on this branch first, and both were real
findings against this work rather than noise: they parametrise over every
`ppa_*.py` and fail a program that has not declared how it is invoked, so adding
`ppa_eco_spare_records.py` reddened them until its vacuous and junk invocations
were written down. That arm matters more for this program than the general rule
says — a producer that read a missing spare plan as "0 spares" would emit a
MEASURED zero, and a measured zero below a declared floor is INFEASIBLE at the
gate, convicting a run nobody looked at.

Four other tests were updated, each because a mechanism designed to catch this
caught it:

* `test_ppa_feasibility_separation::test_the_gate_has_no_numeric_margin_of_its_own`
  enumerates `FeasibilityPolicy`'s fields **exactly**, so `eco_requirement` and
  then `delivery_path` each had to be argued for in a diff a reviewer sees. The
  arguments are in that test.
* Three tests asserted the axis table was nine **by count**. Two now assert the
  axis **names** instead: a count goes red for an axis that was legitimately
  added and stays green for one that was renamed.

Constraints honoured: nothing pushed to `main`; no version bump; no
`--write-baseline`; no GDS touched, no geometry deleted, no pin moved, no rule
deck relaxed, **and no spare/ECO cell deleted to make a number better**. The
tree was cleaned and `PYTHONDONTWRITEBYTECODE=1` set before every measurement
quoted here. Repo artefacts are English only and name no commercial foundry,
process node, SKU or codename; `sky130A` appears only inside the vendored
published records, verbatim.

---

## REQUESTS TO THE LANDER

1. **ANSWERED, and built.** ~~`--eco-declaration` is opt-in, and that is the
   remaining hole.~~ The ruling: a design routed onto the CHIP path
   (`0.5ic → 15.5ic → 26.5ic → 37.5ic`) is tape-out-bound; one that terminates
   at `37.5ip` is not; infer it from the route, never from a GDS or a PDK.
   Implemented in `_ppa/delivery_path.py` by driving the flow's own condition
   predicate over the two terminal steps (§1.5), wired into the axis, the
   feasibility CLI (`--project`) and the search space (`--project`), and covered
   by 19 tests.

   **What remains of it, much smaller:** `--project` is itself a flag, so a
   caller that passes neither a declaration nor a project gets `NOT_SUPPLIED` →
   NOT_APPLICABLE. That is deliberate — "you did not tell me where the design
   lives" is not a finding about the design, and refusing there would turn every
   record-only adjudication in the corpus (unit fixtures, `ppa-e2e/`, the search
   bridge) UNDETERMINED at once. The clean fix is for the flow's own callers —
   `ppa_search_run.py` and `phase3_one_shot_runner.py` — to always pass
   `--project`, at which point `NOT_SUPPLIED` is only reachable by hand. I did
   not make that change because it is a flow-wiring decision with a corpus sweep
   attached, and this brief did not ask for one.

2. **An opt-out on the chip path is visible but not refused, deliberately.**
   A design that declares `required: false` while the flow has it on the chip
   path is still NOT_APPLICABLE — an opt-out is a decision somebody made and
   this axis does not overrule decisions. It carries its own code,
   `FEAS_ECO_OPTED_OUT_ON_CHIP_PATH`, so every design that made that move is
   findable in one grep. If the ruling is that a tape-out-bound design may
   **not** opt out — that the only legitimate `required: false` is on the IP
   path — that is a one-line change to `eco_applicability` and I would rather be
   told than assume it.

3. **The design under study declares nothing, and it should.** The five arms'
   design ships nine input documents and none names a spare/ECO requirement,
   while `L2` names a primary tape-out target. `L9_constraints_floorplan` is the
   natural home. Until it declares one, `ppa-crosslayer`'s published winners are
   NOT_APPLICABLE on this axis by the axis's own rule — correctly, and
   uselessly. The declaration in
   `eco-readjudication/declaration/tapeout_bound.json` is authored for the
   re-adjudication and is **not** a decision I can make on the design's behalf.

4. **A candidate document can declare away its own axis.**
   `ppa_feasibility_check.py` lets the candidates document stand in for the
   contract when `--contract` is omitted, so a candidate set carrying
   `eco_readiness: {required: false}` disables the one axis that could refuse
   it. I have made the origin **visible** — the report publishes
   `policy.eco_readiness.declaration_origin` as `contract` /
   `candidates_document` / `none`, and the CLI prints it — but visibility is not
   prevention, and this is a pre-existing property of `limits` too. If the
   contract lane should be the only source of an applicability declaration, that
   is a change to the CLI contract and I did not make it unasked.

5. **Should `eco_readiness` be a tenth `FEASIBILITY_TERMS` entry, or a separate
   vector?** I made it the tenth term, so it appears on every search manifest
   and `audit_manifest` sees it (NOT_APPLICABLE is already accepted there
   beside PASS). The cost is that every consumer counting nine terms had to be
   updated, and three tests were. If the search lane's vector is meant to be
   frozen at nine, this belongs in a second vector — but then a search
   manifest's headline eligibility would once again not reflect ECO readiness,
   which is the failure being fixed.

6. **`require_preservation` is implemented and unexercised on real data.** The
   proof is wired (`design_for_eco.spares.surviving.count` against the same
   floor) and covered by five tests, but none of the five published arms carries a
   `reports/spare_preservation.json`, so it has never adjudicated a real run.
   Whether Phase 3 should emit that report on every run — making
   `require_preservation` the default obligation for a tape-out-bound design
   rather than an optional one — is a flow decision. It is the obligation that
   actually bears on a post-tape-out repair, and it is the one this
   re-adjudication could not test.

7. **`ppa_feasibility_check.py --help` exits 3, and I did not fix it.** It is
   pre-existing, it reproduces on `origin/main`, and the one-line fix is to use
   `_ppa/cli_exit.parse_or_refuse` for its own parse the way every other `ppa_*`
   CLI does. I left it because `test_ppa_layer_exit_contract._XFAIL_HELP` pins
   it `xfail(strict=True)` with an explicit contract — *"This pin is strict: it
   goes red the moment the fix lands"* — so the fix and the pin's removal are
   one change belonging to that lane. This branch adds a strict xfail of its own
   naming the defect, because a suite that adds a flag to that CLI and then
   quietly asserts around its broken `--help` is hiding something. Two lines in
   two files whenever you want it; `ppa_pareto_check.py` has the identical bug.

8. **Thirteen pre-existing red tests on `origin/main`.** Listed in §5,
   reproduced in a clean detached worktree at `6dfe15a32`. Not mine, not fixed
   here, and they will show up in any CI run of this branch.
