# CONVERGE → CAPTURE → DISTILL on the pad-site recovery

Branch: `jcapsha/converge-capture-distill`. Base: `origin/main` at `a4caccefe`
(v1.11.69). Nothing pushed to main, no version bumped.

Source read in full before anything was written: `_jpadsite_priv/RESULT.md`
(2143 lines, fetched from the host that produced it), its `evidence/` tree (56
files), and the branch `origin/jpadsite/pad-site`.

## Answer in one line

Four Bucket A records, no Bucket T and no Bucket D. The premise of the third
finding is REFUTED by the report I was sent to capture, so the Bucket T
question the brief asked me to think hardest about has a measured answer
rather than a judged one: **there is no tool half.** F2's rule is SHIPPED on
this branch — checker, register and test, green, with three reds behind it.
F1's is not, for a measured reason. And a fourth record exists because the
refutation was published four times across four branches and **the identifier
that asserts the refuted premise is still on main today.**

---

## The thing to read first: F3's premise does not survive its own source

The brief states:

> **F3 — a config variable that the tool ignores.** `PAD_ROTATION_VERTICAL` was
> proven inert by four separate OpenROAD processes.

It is not inert. The refutation is at the TOP of `_jpadsite_priv/RESULT.md`,
under `THREE ORIENTATION DEFECTS FOUND 2026-08-22, AFTER THE FIX HAD LANDED, BY
RE-RUNNING MY OWN PROBE`, and again in section 4 in the ruling itself. Measured
in OpenROAD 26Q3-1581, holding one rotation parameter and varying the other
while watching ALL FOUR sides:

    H=R0  V=R0    ps0=R0    pn0=MX      pw0=MXR90  pe0=R90
    H=R90 V=R0    ps0=R0    pn0=MX      pw0=MX     pe0=R180
    H=R0  V=R90   ps0=R90   pn0=MYR90   pw0=MXR90  pe0=R90
    H=R0  V=MX    ps0=MX    pn0=R0      pw0=MXR90  pe0=R90

`-rotation_horizontal` moves WEST and EAST. `-rotation_vertical` moves SOUTH
and NORTH. **The parameters are named for the ROW AXIS, not the SIDE.** The
original probe varied `PAD_ROTATION_VERTICAL` while observing only WEST and
EAST — the wrong pairing — so across four correctly-isolated processes it
correctly saw nothing change, and the wrong conclusion was drawn from a correct
measurement.

The four separate processes were not the weak part. Running each value in its
own process was the RIGHT call and removed a real confound (a row left behind
by an earlier `make_io_sites` being reused). The observation space was the weak
part, and no amount of process isolation fixes an observation space that omits
half the sides.

**I did not re-run the probe myself.** I have no OpenROAD process behind this
paragraph. What I have is that the branch's own author re-measured, published
the table, named the mechanism, and renamed the shipped schema key
(`rotation_vertical_inert` → `rotation_vertical_not_honoured`, `c56b8e1b1`)
because the old key asserted inertness in the schema itself. I am reporting a
retraction that its author made and evidenced, not a measurement of my own, and
this sentence is here so that distinction is not lost downstream.

### What that does to the ladder for F3

**Bucket T is empty, for a measured reason.** The brief asks which half is the
tool's and which is ours. Answer: none of it is the tool's. The tool honours
the variable and is self-consistent with its own naming convention. A fork
change would mean renaming a tool's CLI flags from the row axis to the side,
which would break every upstream script that drives it — a fix strictly worse
than the defect. The whole of F3 is ours.

**The ruling survives intact and is better founded.** Behaviour does not
change; only the justification does, and it gets stronger:

* weak version (what the flow owner was told): "an author who sets a knob is
  entitled to be told the knob does nothing";
* true version: the knob HAS an effect — it rotates the N/S pads — and THIS
  STEP does not implement it, so honouring the declaration silently would hand
  an author geometry they did not ask for.

So the rule generalises as the brief asked — **generalise the RULE, not the one
variable** — but it generalises from a different and firmer place: not "a knob
the TOOL ignores", which is a claim about the tool, but **"a variable this STEP
declares and does not honour"**, which is a claim about our own contract and is
the one we can actually check.

---

## Main still ships the refuted premise — measured, and it is live

The report says the schema key was corrected in `c56b8e1b1`:
`rotation_vertical_inert` → `rotation_vertical_not_honoured`, "because the KEY
asserted inertness in the schema itself".

    $ git merge-base --is-ancestor c56b8e1b1 origin/main
    NOT an ancestor of main

The object exists; the commit did not land. On `origin/main` at `a4caccefe`,
today:

| where | what it says |
|---|---|
| `pad_ring_gen.py`:246 | artefact key `"rotation_vertical_inert"` |
| `pad_ring_gen.py`:185 | constant `ROTATION_VERTICAL_INERT`, `"honoured": False` |
| `pad_ring_gen.py`:67 | heading: `PAD_ROTATION_VERTICAL` IS INERT, AND SAYS SO OUT LOUD |
| `pad_ring_gen.py`:69 | "The same measurement shows the placer does not read it" |
| `pad_ring_gen.py`:313 | "does not reach this dict because it does not reach the tool either" |
| `_pad_ring.py`:275 | "a CONSTANT of the placer, not a function of the declared rotation" |

Every one asserts, in the schema and in the source, the proposition the
branch's own re-measurement withdrew. **A retraction published in a report does
not reach a reader who keys on a field name.** The behaviour is right — the
step refuses rc 2 on a non-default value — and the name it refuses under says
something false about why.

Two line numbers in the table above were wrong in the first push of this
section — `pad_ring_gen.py`:68 is the `===` underline beneath the heading, not
the sentence, and the `_pad_ring.py` comment is at :275, not :279. Both were
caught by re-reading every citation with `sed -n '<n>p'` before publishing,
which is the check this whole report argues for; they are corrected above. The
anchor STRINGS are the durable form and are quoted in full, so a reader can
find them at any head.

### The consequence I am NOT confirming, and why it is written down anyway

If the re-measured table is right — `-rotation_horizontal` steers WEST and
EAST, `-rotation_vertical` steers SOUTH and NORTH — then main's side map is
**transposed**:

    pad_ring_gen.py:317-318
        "S": cfg["rotation"]["PAD_ROTATION_HORIZONTAL"],
        "N": PR.rotate_cw(cfg["rotation"]["PAD_ROTATION_HORIZONTAL"], 2),
        "W": PR.VERTICAL_SIDE_ORIENT["W"],     # a constant, measured only at
        "E": PR.VERTICAL_SIDE_ORIENT["E"],     # PAD_ROTATION_HORIZONTAL=R0

SOUTH and NORTH are driven by the variable the table says drives WEST and EAST,
and WEST and EAST are hard-coded from a sweep that held the variable that
actually steers them at its default. A design declaring a non-default
`PAD_ROTATION_HORIZONTAL` would then be emitted orientations the placer does
not produce — and the rc 2 refusal guards the OTHER variable, so nothing stops
it.

**I have run no tool.** This follows from someone else's table, and a table is
what the original mistake was made of. It needs ONE OpenROAD run to settle and
must not be acted on before it has one. It is written down because a named
unverified consequence can be checked and an unnamed one cannot — which is the
same rule F1 states about search spaces, pointed at myself.

## The ladder, per finding

Stop at the first YES; the reason for stopping is written down.

### F1 — the step read the wrong PDK view → **Bucket A**

**Bucket T? No.** Upstream has no defect here. librelane declares
`PAD_FAKE_SITES` (`librelane/config/flow.py:494`) and materialises it inside
`read_tech_lef` (`io.tcl:349`) BEFORE its own site lookups run
(`pad_cfg.tcl:40`), so the sites are in the DB by the time any padring script
asks. Ours was the only layer that never opened the declaration. A rule in the
fork would paper over our omission, which is the inversion Bucket T exists to
prevent.

**Bucket A? Yes.** As the brief demands, the exact input and the exact
undecidable decision, named before writing anything:

* **input the program sees:** the module's own AST.
* **decision it makes:** does the call constructing this refusal carry any
  expression naming where the program looked? That is syntax.
* **decision it CANNOT make from that input:** whether the named search space
  is COMPLETE. Completeness is a property of the DISTRIBUTION, not of our
  source — no amount of reading our Python decides whether both views a PDK
  declares a site in were opened. So the rule is scoped to the reachable half:
  refuse an absence verdict that names NO search space at all.

That scoping is the honest half of this record, and it is why "it needs
judgement" was not available as an excuse: the judgement-requiring part was
identified, excluded by name, and the remainder is decidable.

**General-core test: passes.** The logic reads refusal construction. It reads
no pad and no PDK literal. It was written here first, that is all.

### F2 — the extent was measured from the oriented footprint → **Bucket A**

**Bucket T? No.** Upstream's `pad_cfg.tcl` is CORRECT: it measures a cell in
exactly two places and both read `[[$inst getMaster] getWidth]`, on all four
sides, and there is no `getHeight` in its side arithmetic at all. The 4.4x
error — 19 × 350 = 6650 µm summed against a 1500 µm side — was entirely ours.

**Bucket A? Yes.**

* **input:** a register of {upstream artefact, extraction regex, snapshot of
  the extracted names + that file's sha256, our module} plus our module source.
* **decision:** is every upstream name accounted for in exactly one class, and
  does each class's claim hold against the source? Set arithmetic.
* **why judgement does not block it:** the judgement — which class a name
  belongs in — is made ONCE by a human at registration and then pinned. That is
  what makes it a ratchet rather than a re-derivation, and it is the difference
  between a register and a re-implementation of the thing being registered.

**General-core test: passes.** "Pin a re-implementation against its upstream"
names no pad.

### F3 — a variable the step does not honour → **Bucket A**

Bucket T empty for the measured reason above.

* **input:** the step's declared config contract plus the variable's resolved
  value.
* **decision:** is this name in the not-honoured set, and is its value
  non-default? A lookup and a comparison.

---

## CONVERGE: what was already done, and why the deliverable is not a fourth checker

The brief warns that ~63% of "extractable rules" in an earlier sweep were
already implemented in `programs/` and the skill was merely prose over them. I
grepped first. The finding is worse than that warning and it is about my own
name.

**Five prior `jcapsha` branches exist**, none landed, and among them are
**three independent near-duplicate implementations of F2's single rule**:

| branch | program | measured on `origin/main` `a4caccefe` |
|---|---|---|
| `origin/agent/jcapsha-capture` | `upstream_reimplementation_pin_check.py` (322 l) | **rc 2** — zero modules declare `UPSTREAM_PINS`; population 0 |
| `origin/jcapsha/capture-sha256-recovery` | `upstream_mirror_is_pinned_check.py` (289 l) | **rc 2** — zero modules declare `UPSTREAM_MIRROR`; population 0 |
| `origin/jcapsha/sha256-capture` | `upstream_contract_parity_check.py` (438 l) + register | **rc 0 PASS** — 2 registered re-implementations, 20 upstream names accounted for |

The first two exit NOT DETERMINED over a population of zero and say so
honestly — "zero declared mirrors is a question with no subject, not a clean
answer to it". They are correct and they are also unshippable: a guard with no
subjects is a green over nothing.

So the deliverable for F2 is a **consolidation verdict** — keep the third, drop
the other two — plus one predicate fix, not a fourth checker. That is the
brief's own instruction applied to my own prior lanes. **It is shipped on this
branch**: `upstream_contract_parity_check.py`, its register and its test, taken
from the lane that had the only non-vacuous population, with the blind
predicate fixed and the register corrected to match main.

### And the one that passes, passes partly over a blind predicate

Full working in `evidence/F2_the_PASS_is_partly_blind.md`. In short:

`PAD_FAKE_SITES` is the single name the register classifies `known_gap`. **The
fix that closed that gap is on main** — `_pad_ring.py` carries
`parse_pad_site_declarations` (:497), `discover_io_site_declarations` (:550),
`IoLibrary.resolve_site` (:642). The guard has a rule for exactly this
staleness at :213. It does not fire, and the guard exits 0.

The predicate is why:

    def _mentions(text, name):
        return (f'"{name}"' in text) or (f"'{name}'" in text)

It requires a BARE QUOTED LITERAL. The landed implementation consumes the
variable through a **regex** (`_pad_ring.py:490`), where the name never appears
as `"PAD_FAKE_SITES"`. Positive control — `_mentions` widened to a substring
match, CONTROL ONLY, not shipped, same register, same tree:

    FAIL: 1 unaccounted name(s) ...
      - PAD_FAKE_SITES is classified known_gap and DOES appear in
        programs/_pad_ring.py.

The rule is reachable and correct; the predicate is blind. I did not believe
the guard's silence until I had produced a failure from it.

**This is F1's class one level up.** F1 read one PDK VIEW and said "not found".
This reads one SOURCE FORM and says "not implemented". Both are a search space
narrower than the claim made over it. That recursion is the strongest evidence
this branch has that F1 and F2 are one general rule and not two pad stories.

### F1's implementation is not shippable as-is either

`absence_verdict_names_its_search_space_check.py` on current main: **rc 1**, 31
absence verdicts parsed, 29 naming a locus, 2 flagged —

    _pad_ring.py:778             PAD_CONFIG_VARIABLE_ABSENT
    _ppa/backends/openroad.py:740  ROUTE_WIRELENGTH_BY_LAYER_ABSENT

I read both before touching anything, because the order matters: narrowing a
predicate AFTER seeing a red, to clear the red, is the forbidden move; deciding
first whether the hits are the class is not.

* `_pad_ring.py:778` — "all four side lists are empty — a ring of no pads
  assigns nothing". It names the container it read.
* `openroad.py:740` — "no `Total wire length on LAYER` rows follow the last
  total". It names the search pattern AND the region.

Both say where they looked. Neither is the "says nothing" state the guard
exists to catch. They are false positives of the predicate's 57-word
`_LOCUS_WORDS` list, which contains no word covering either phrasing (verified:
zero locus-word hits in each message).

Per the brief — a guard that fires on the state we just shipped is a bug, and
must be narrowed or dropped. **So F1's checker is NOT shipped on this branch.**
The record carries the rule, the ladder verdict, and the exact reason the
existing implementation is not yet green. Shipping it red, or shipping it after
quietly widening the word list to swallow two hits I had already judged
false-positive, would both be worse than shipping the honest gap.

---

## What is shipped, and its red

One behavioural change: a single `CAPTURE_ROUTING.json` entry for
`phase3.pad_ring`.

**A second entry was written and then removed, and the repo caught it, not me.**
The first version of this branch also registered `repo.upstream_parity` pointing
at `programs/upstream_contract_parity_check.py` — the general home for F2's
rule. That program does not exist on main and this branch deliberately does not
ship it, so the entry was a pointer to nothing.
`test_capture_routing_consistency.py::test_bucket_A_program_paths_exist` failed
on exactly that:

    AssertionError: Bucket A programs in CAPTURE_ROUTING.json missing on disk:
        repo.upstream_parity → programs/upstream_contract_parity_check.py

The test offers two fixes — "add the program or null out the routing entry". I
removed the entry and routed F2's record to `phase3.pad_ring`, the step where
the drift was actually measured, so the sketch lands beside the module that
drifted. I did not null the `bucket_A_program` and keep the step, because a
registered step with a null program is the silent-drop state documented
immediately below, and I would have been shipping the defect I was reporting.

Worth saying plainly: I wrote a route to a program I had already decided not to
ship, in a report whose subject is claims that outrun what was measured. The
gate caught it in 1.23 seconds.

The flow declares the step (`flow/phase1_phase2_phase3.yaml:2986`, "Pad Ring
(chip/IC path only)"). CAPTURE_ROUTING carried **zero** pad entries, and
`default_routing.bucket_A_program` is `null`.

**The red**, measured by reverting that one file to `origin/main` and re-running
the emitter on the same `recoveries.json` (`evidence/RED_routing_entry.md`):

    routing_used: {"bucket_A": []}      bucket_A_files: []      exit 0

Three Bucket A records in, zero sketches out, **exit 0**. Every Bucket A
recovery ever captured from the pad-ring step was dropped on the floor with a
green exit code. With the entry: 2 sketch files, 3 rules.

Two prior lanes of mine independently added the same entry. Three independent
arrivals at one missing entry is the entry being missing.

---

## What I did NOT do, and why

* **Did not ship F1's checker.** It fires false on current main, for the reason
  measured above. The brief's clause is that a NEW guard must run clean before
  it ships, and it does not yet.
* **Did not widen `_LOCUS_WORDS`** to clear F1's two hits. That would be
  relaxing an assertion to make a red go away.
* **Did not re-run the rotation probe.** No OpenROAD process backs the
  refutation from me; I am carrying its author's retraction and have said so.
* **Did not emit a Bucket D record.** Nothing here is a non-generalisable
  over-fit. All three findings are general logic that got written here first.
* **Did not emit a fourth record** for the probe lesson ("a negative result is
  only evidence if the probe could have observed a positive") or for the silent
  routing drop. Both are F1's class again; folded into records 1 and 3 rather
  than emitted as near-duplicate rules, which is the brief's own warning
  applied to my own records.
* **Did not run the full `programs/tests` suite.** Forbidden by the brief.
* **Did not push to main and did not bump the version.**

## Files

    recoveries.json                              4 records, all Bucket A
    candidates/                                  1 sketch file, 3 rules, emitter rc 0
    evidence/F2_the_PASS_is_partly_blind.md      the false PASS + positive control
    evidence/RED_routing_entry.md                the red the routing entry ships with
    evidence/F1_guard_on_current_main.txt        rc 1, the 2 false positives
    evidence/F2_parity_PASS_on_current_main.txt  rc 0, the blind pass
    evidence/F2_candidate_UPSTREAM_PINS_vacuous.txt    rc 2, population 0
    evidence/F2_candidate_UPSTREAM_MIRROR_vacuous.txt  rc 2, population 0
    evidence/F2_mutation_sweep.md                three reds, and one non-result
    evidence/enhancement_emit_run.txt            the emitter's own output
    evidence/MEASURED_AT_main.txt                the base sha every number above is against
