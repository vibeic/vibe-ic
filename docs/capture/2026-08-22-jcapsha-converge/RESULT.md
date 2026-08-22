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

### And the reason is worse than two false positives — the guard does not catch F1

I wrote a control instead of taking the rc 1 at face value
(`evidence/F1_the_guard_does_not_catch_F1.md`). Four absence verdicts, one of
them the ACTUAL pre-fix refusal:

| verdict | guard |
|---|---|
| `PAD_SITE_NOT_FOUND` — the real message, `...(0 site(s) from 1 LEF(s); PAD-class: [])` | **PASSES** |
| `f"{name} is not available"` | **PASSES** |
| `f"{thing} is not available"` | FAILS |
| `"it is not there"` | FAILS |

**The refusal that blocked one design's whole verdict passes the guard written
out of it.** It says `LEF(s)`, and `lef` is in `_LOCUS_WORDS`. The guard is
named `absence_verdict_names_its_search_space` and the property it decides is
`absence_verdict_mentions_a_locus_word`, and the distance between those two
predicates is precisely the defect:

    a locus word is a place that EXISTS.
    a search space is the set of places that were OPENED.
    "0 site(s) from 1 LEF(s)" names a count and a view and is still a
    search space of ONE where the distribution declares in TWO.

The guard's docstring concedes this in advance. It is an honest disclosure and
it is easy to read past; measured, it means the guard is blind to its own
motivating case while reporting two false positives on top. Too lax where it
matters, too strict where it does not — and narrowing the word list fixes
neither, because the word list is not the part that is wrong.

**A claim I nearly published at the wrong size.** Row 2 passes only because
bare `name` is in the vocabulary — a word for the thing SOUGHT, not the place
SEARCHED. `name` is the commonest variable in a refusal message, so the
mechanism suggests a hole most refusals fall through. Control on main's 1279
files, bare `name` dropped: **31 verdicts, 29 naming a locus, 2 FAIL — with it
and without it, identical.** The hole is real on a constructed input and
accounts for zero of main's passes. Latent, not active. Written at the size the
corpus supports.

### What is decidable, for whoever writes it

Not "mentions a locus word", and not "is the search space complete" — the
docstring is right that completeness belongs to the DISTRIBUTION. The decidable
middle:

    an absence verdict must interpolate THE COLLECTION IT ITERATED — the
    actual list of things opened — not a count of it, and not a word that
    sounds like a place.

The pre-fix message carried two counts and no list. A reader handed the LIST
would have seen one path where the distribution declares in two directories,
which is the whole finding. A program can check that a refusal carries the
collection its enclosing scope iterated; it cannot check that the collection
was the right one. That boundary is where Bucket A ends, and it is further
along than the shipped implementation reaches.

### I implemented that rule to measure it, and it is wrong too

Stating a rule for someone else to write is cheap. I wrote it
(`evidence/F1_rule_population_probe.py`, not shipped) and ran it over main:

    absence verdicts                     : 25
    IN SCOPE (a collection was searched) : 24
      carry the collection               : 9
      WOULD BE REFUSED                   : 15

Before writing 15 down as the rule's population I read the refusals it names.
The first two are model disclosures:

    openroad.py:1071    if not d.is_dir():
                            o.refuse("RUN_DIR_ABSENT", f"{d}: not a directory")

    otp_image_check.py:176  if not ver_path.exists():
                                Finding("FILE_MISSING", ..., f"OTP image not found: {ver_path}")

Both name the exact path. There is nothing further to disclose. The probe put
them "in scope" because unrelated things are iterated elsewhere in the same
function — its own printout gives it away, `(scope searched: ['e'])`,
`(scope searched: ['image'])`. **15 is not the rule's population and is not
quoted as one anywhere in this branch.**

So two implementations, wrong in opposite directions, and neither error is
visible from inside itself — the first looks clean because 29 of 31 pass, the
second looks thorough because it finds 15:

| implementation | predicate | error |
|---|---|---|
| the prior lane's | message mentions a locus word | passes the real refusal; 2 false positives |
| my probe | message interpolates something the function iterated | refuses 15; the sampled ones are exemplary |

Both cases turn on the one thing neither looks at — **the condition that raised
the refusal**. `if not d.is_dir()` → the subject is `d` and the message names
`d`. `if site is None` → the subject is the lookup that returned None, and the
provenance of THAT is what the pre-fix message never disclosed. The rule is
"an absence verdict must name the subject of the condition that raised it": a
dataflow question from the refusal back to its guard. Still deterministic,
still Bucket A, and real program work rather than a predicate tweak.

**I did not try a third predicate.** Past this point I would be iterating
shapes until one came out green on today's corpus, and a predicate arrived at
that way is fitted to the corpus rather than to the rule.

Shipping it red, or shipping it after quietly widening the word list to swallow
two hits I had already judged false-positive, would both be worse than shipping
the honest gap.

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
    evidence/F1_the_guard_does_not_catch_F1.md   the control: it passes the real refusal
    evidence/F1_two_implementations_wrong_in_opposite_directions.md
    evidence/F1_rule_population_probe.py         my attempt, measured and rejected
    evidence/F2_parity_PASS_on_current_main.txt  rc 0, the blind pass
    evidence/F2_candidate_UPSTREAM_PINS_vacuous.txt    rc 2, population 0
    evidence/F2_candidate_UPSTREAM_MIRROR_vacuous.txt  rc 2, population 0
    evidence/F2_mutation_sweep.md                three reds, and one non-result
    evidence/enhancement_emit_run.txt            the emitter's own output
    evidence/MEASURED_AT_main.txt                the base sha every number above is against


---

## Closed after the clean-tree pass: the register's last gap

`pad_ring.along_the_row_extent` was still `pin=known_gap`, and I had written
that this branch would not close it. It closes
(`evidence/F2_the_last_known_gap_is_closed.md`) because the image the snapshot
records — `ghcr.io/vibeic/vibeic-eda:0.3.24` — is on this host and upstream's
`pad_cfg.tcl` is readable at the recorded sha256, byte for byte.

The gap was more specific than the register's own wording. **Our half was
pinned all along** by `test_pad_ring.py::test_the_spacing_is_upstreams_arithmetic`
— the fixture's master is 75 x 350 against a 1_280_000-unit side, so summing by
HEIGHT does not fit and the test goes red the moment the extent returns to the
oriented footprint. Nobody had written down that it was the pin. **Upstream's
half was a sentence in a comment**, and that is what
`test_upstream_pin_pad_cfg.py` adds: sha256 against the snapshot, both cell
measurements reading `getWidth`, and the master's height reaching nothing but a
`puts`.

That last assertion is the one worth stating carefully: a raw count of
`getHeight` in that file is FOUR and reads as a contradiction. Two are site
dimensions; the other two are the per-cell measurement, and MEASURED, the
resulting `$height` is used in exactly one line of the whole file — a
diagnostic `puts`. The test asserts the USE, not the count, because a count
would have to be explained away and an explanation living in a test is a
comment.

Reds: positive control passes at a custom root; upstream drifted to sum
`$height` → 3 of 4 fail including the sha; no distribution reachable → 4
SKIPPED, naming the missing input, never passing. And a pin naming a test that
was never written is refused by the checker.

    pad_ring.upstream_pad_variables: ... known_gap=0
    pad_ring.along_the_row_extent:   anchors=2, pin=test
    PASS: 2 registered re-implementation(s)

Zero open gaps, and every green in the register now has something behind it.


---

## The register's first non-pad entry, and the general-core test settled empirically

The brief's general-core test asks whether a rule's LOGIC touches a pad or
whether it merely got written here first. For F2 the honest answer was "the
logic is general" — and the register's own contents were the weakest possible
evidence for it: **two entries, both `pad_ring.*`**.

Third entry, same register unchanged
(`evidence/F2_a_non_pad_entry_and_two_mutations_that_were_not.md`):

    digital_hardmacro.lef_write_route
      ours      programs/digital_hardmacro_gen.py
      upstream  librelane/scripts/magic/lef.tcl
      sha256    067772b6… verified equal in ghcr.io/vibeic/vibeic-eda:0.3.24

Upstream has two routes; `MAGIC_LEF_WRITE_USE_GDS` picks between them and its
default is FALSE — read the views and the DEF, not the GDS alone. The producer's
own docstring records what the other route cost on a real signed-off run: an
abstract with an outline, obstructions and **zero pins**, because the port
labels sit on layers the PDK's Magic technology does not map. Geometry from the
GDS, ports from the DEF.

Both halves pinned, both reds live and independent: upstream's default route
losing `read_def` → sha + two-routes fail; our producer dropping `def read` →
our half fails. No distribution reachable → skips, never passes.

    pad_ring.upstream_pad_variables:   ... known_gap=0
    pad_ring.along_the_row_extent:     anchors=2, pin=test
    digital_hardmacro.lef_write_route: anchors=3, pin=test
    PASS: 3 registered re-implementation(s)

Three entries, two subsystems, one with no pad in it, zero open gaps.

### Two more mutations that were not mutations

The first attempt at both reds reported the properties SURVIVING. Both readings
were false: I commented the lines out, and `# read_def` still contains
`read_def`, so the assertions were right and my mutations were no-ops with
respect to the property while looking like real edits. This is the second and
third time tonight — the earlier one at least raised a `ValueError` I could
see; these ran clean and produced greens that read as evidence. Every mutation
in this branch now carries an assertion that the property actually changed, and
prints `MUTATION APPLIED` only after it passes.

A control also failed for a harness reason — I had mangled a cached copy of the
upstream file by stripping a `sha256sum` header with `sed`/`tail`. Re-extracted
with `docker run --rm --entrypoint cat`, it round-trips byte-exact. **A control
that fails is a claim about the harness until proven otherwise.**

### And a third borrowed fixture

Registering the entry turned three unrelated tests red with `assert 2 == 1`,
because `_fake_root` built a distribution from a hard-coded list of two pad
files. The tests were right and the checker was right; the helper knew a fixed
list. It now reads the register, so the next entry costs nothing. Proven not
hollowed out by disabling the checker's sha guard — message deliberately left
in place so the mutation could not pass by deleting the string the test greps
for — which turns exactly one test red.

That is the third fixture on this branch borrowed from live data rather than
constructed. The pattern deserves its name: **a test that reaches into the
shipped artefact for its fixture asserts today's contents, and fails the day
the artefact legitimately changes — which is the day the register is doing its
job.**


---

## F1 closed: three predicates, three wrong, and the third refuses the exemplar

The previous section ended by prescribing a rule for whoever writes it. I wrote
that one too (`evidence/F1_three_predicates_three_wrong.md`,
`evidence/F1_rule_population_probe2.py`): walk from the refusal up to the `if`
that guards it, require the message to name that condition's subject.

On main it flags all four `PAD_SITE_NOT_FOUND` sites — the original defect,
which the word-list predicate passed. That looked like the answer. Then I read
what it refuses, and it refuses `pad_ring_gen.py:712` — the POST-FIX message
that F1's own fix wrote, which names BOTH PDK views with counts of each and is
the gold standard for this rule. It is rejected because the guard's subject is
`site` while the message names `lib.sites`, `lefs`, `lib.declared_sites`.

| attempt | asks | why it is wrong |
|---|---|---|
| 1 (prior lane's) | message mentions a locus WORD | passes the pre-fix refusal; 2 false positives |
| 2 (mine) | interpolates something the FUNCTION iterated | attributes unrelated iterations; refuses paths that name themselves |
| 3 (mine) | names the SUBJECT of the guarding condition | refuses the exemplar |

Three different wrong questions, not three bugs. The subject is the thing
SOUGHT; the disclosure is about where it was SOUGHT. What a reader needs lives
one hop back, inside the lookup that produced the subject — a
reaching-definitions walk across a method boundary. Deterministic, still Bucket
A in principle, well past what a predicate over one call site decides.

**No fourth shape was tried.** After three failures that were each invisible
from inside the implementation and obvious within ten minutes of reading its
output, a fourth would be selected by whether it comes out green on today's 25
call sites — fitting to the corpus, not to the rule. That is the thing this
whole branch is about.

F1's status is therefore a measured verdict and not a deferral. The rule is
correct, and its exemplar is already in the tree at `pad_ring_gen.py:712` — a
rule with a working instance and no checker is in better shape than a checker
with no working instance, which is what the other two attempts would have
shipped.


---

## I ran the probe myself, and two things changed

Every section above carried F3's refutation as SOMEONE ELSE'S measurement and
said so. That caveat is withdrawn
(`evidence/rotation_reprobe/MEASURED_BY_JCAPSHA.md`).

Four SEPARATE `docker run` processes, image 0.3.24, **OpenROAD 26Q3-1607 — a
different build from either prior lane**:

    ##### H=R0  V=R0   ps0=R0   pn0=MX     pw0=MXR90  pe0=R90
    ##### H=R90 V=R0   ps0=R0   pn0=MX     pw0=MX     pe0=R180
    ##### H=R0  V=R90  ps0=R90  pn0=MYR90  pw0=MXR90  pe0=R90
    ##### H=R0  V=MX   ps0=MX   pn0=R0     pw0=MXR90  pe0=R90

Identical value for value. `-rotation_horizontal` steers the VERTICAL sides;
`-rotation_vertical` steers the HORIZONTAL ones. Independently confirmed.

**And the consequence I had flagged but refused to act on is confirmed too**,
from the other side as well — driving main's own producer and reading its DEF:

| side | main emits | tool produces | |
|---|---|---|---|
| SOUTH | `N` | `N` | match |
| **NORTH** | **`S`** (a 180° rotation) | **`FS`** (a MIRROR) | **DIFFERS** |
| WEST | `FW` | `FW` | match |
| EAST | `W` | `W` | match |

Main emits no `FS` and no `FN` anywhere. **I did not fix it**: the verified fix,
with an A/B showing 21 orientations changed and positions identical, is already
on `origin/jpadsite/pad-site` (`6c3ebe447`, `725f9352f`), which is not an
ancestor of main. Re-implementing it would be the near-duplicate this branch
exists to warn about. What is added is independent confirmation that it is live.

## Two disclosures about my own F4 work

**The rename is a near-duplicate.** `c56b8e1b1` on that same branch makes it,
with the same names and the same reasoning. I arrived at it independently and
did not check the sibling branch first — the exact failure I documented in the
F2 case, committed by me, three sections later. The lander should take
`jpadsite/pad-site` as the vehicle; it is the bigger verified change set.

**And my general guard was fitted to my own prose.** Its first version scanned
every string literal for "inert" and excluded the phrases I happened to have
written. Measured three ways:

    origin/main (the defect)              FAIL
    jpadsite/pad-site (independent fix)   FAIL   <-- wrong
    this branch (my fix)                  PASS

It failed the independent fix because that docstring retracts the claim by
QUOTING it: `THIS SECTION SAID "IS INERT" … AND BOTH WERE …`. **A retraction has
to be able to name what it retracts.** A guard whose pass condition is
"contains the author's own sentences" is fitted to one edit, which is what this
whole branch is about — and I had done it in the test written to enforce the
rule.

Narrowed to what the rule is actually about — `ast.Name` ids, `def`/`class`
names, and string literals used as DICT KEYS, never prose:

    origin/main (the defect)              FAIL  [name: ROTATION_VERTICAL_INERT,
                                                 schema key: 'rotation_vertical_inert']
    jpadsite/pad-site (independent fix)   PASS
    this branch (my fix)                  PASS

A guard satisfied by an implementation it has never seen, and refusing the tree
both implementations were written against, is the strongest evidence available
that it enforces the rule and not the edit. It was only obtainable because a
second independent fix existed to test it against.


---

## This branch composes with the sibling branch, measured

A lander wants both: this one for the parity register, the pins, the routing
entry and the general guard; `origin/jpadsite/pad-site` for the NORTH and
CORNER orientation fixes I independently confirmed are live on main. They touch
the same three files, so I merged them in a scratch worktree rather than
assuming (`evidence/COMPOSES_WITH_THE_SIBLING_BRANCH.md`).

**Six conflict hunks, and every one is the same correction written twice** —
the retraction of the inertness claim, reached independently on both branches.

Resolved per file, after reading every hunk, because taking one whole side
blind is a silent revert:

* `_pad_ring.py` → **theirs**. They renamed the table to `SIDE_ORIENT` and
  ADDED the `S`/`N` entries — the NORTH fix, real code. Mine only re-words the
  comment above it. Keeping mine would throw away a fix to preserve a paragraph.
* `pad_ring_gen.py` → **theirs**. Both rename to exactly the same names; theirs
  additionally drives all four sides from the table.
* `tests/test_pad_ring.py` → **both**. Theirs tests the NORTH and CORNER fixes;
  mine adds the identifier guard and the report-key test. Neither rewords the
  other; choosing would drop real coverage. 92 test functions after grafting.

The merged tree:

    197 passed, 16 skipped, rc 0      suite_write_guard: wrote nothing
    upstream_contract_parity_check    PASS, 3 entries, rc 0
    -k "asserts_inertness or refuted_premise"   ->  2 passed

That last line is the load-bearing one: **my general guard passes on THEIR fix,
inside a real merge.** Third independent confirmation that it enforces the rule
and not my edit.

**Recommendation for the lander.** Take `jpadsite/pad-site` as the vehicle for
the pad-ring source — six commits, it fixes NORTH and two CORNERS with an A/B,
and my rename duplicates its `c56b8e1b1` without adding to it. Take this branch
for the register, the pins, the routing entry, the capture and the guard.


---

## F1's rule found its author

I went looking for whether my two pin tests SKIP in CI — a pin that never runs
where the gate matters is decorative. That question stays open (there is no
`.github/workflows/`, and env-skipping has precedent here: `test_pad_ring.py`
:851 skips with "no `PDK_ROOT` on this host"). The search turned up something
worse, in code I shipped on this branch
(`evidence/F1_RULE_APPLIED_TO_MY_OWN_CHECKER.md`).

`upstream_contract_parity_check.py` re-reads the upstream file only when
`--distribution-root` is given. Without one, the register's own snapshot is the
denominator. **The verdict was byte-identical in both modes**, so a reader could
not tell

    "our re-implementations agree with UPSTREAM"

from

    "our re-implementations agree with OUR OWN RECORD of upstream"

and only one of those is a statement about upstream. That is F1's class exactly
— "not found" versus "not looked for" — in the program written to enforce the
lesson.

Fixed with a BASIS line printed at EVERY verdict, including failing ones,
because a disclosure only on the happy path is not one:

    BASIS: the register's RECORDED SNAPSHOTS for all 3 entry/entries. Upstream
           was NOT re-read on this run — pass --distribution-root …

    BASIS: upstream re-read under /usr/local/lib/python3.12/dist-packages for
           3 of 3 entry/entries.

**A result falls out of it:** the second form is the first time all three
entries have been re-verified against a live distribution in one pass — 3 of 3,
PASS, inside `ghcr.io/vibeic/vibeic-eda:0.3.24`. Every recorded sha256 in the
register is byte-current with the shipped image.

Three tests, and the mutation removes the CALL while deliberately leaving the
helper in the source, so it cannot pass by deleting the string the tests grep
for: 3 failed / 22 passed, restored 25 passed, checker byte-identical.

Every other instance of this class on this branch was in code someone else
wrote. This one is mine, in the program whose entire purpose is to stop a claim
about upstream from going unchecked.
