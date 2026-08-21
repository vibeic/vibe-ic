# CONVERGE / CAPTURE / DISTILL of the pad-site recovery

Agent `jcapsha`, 8HD-d, 2026-08-22.
Branch: **`jcapsha/pad-site-capture`**, off `origin/main` @ `a00f53f20`.
Source read in full before anything was written: `_jpadsite_priv/RESULT.md` on
8hd-3 (476 lines), its `evidence/`, and the whole `origin/main` ->
`origin/jpadsite/pad-site` diff (4 files, 858 insertions).

Deliverable: `recoveries.json` (5 records) emitted through
`enhancement_emit.py` into `candidates/`, both gates green
(`enhancement_emit` rc 0, `backlog_sanitize_check` rc 0, 0 hard violations,
0 soft warnings, no unrouted Bucket-A record).

---

## The one-line answer per finding

| # | finding | bucket | why it stopped there |
|---|---------|--------|----------------------|
| F1 | the step read the wrong PDK view | **A** | a set difference over the view directories that exist on disk — see the correction below; the rule this table first carried was refuted by its own sweep |
| F2 | the extent came from the oriented footprint | **A** | a taint walk over one function's assignments |
| F3a | the tool does not honour the rotation variable | **T** (OpenROAD) | the plugin does not place the rows; anything it did here would be a second guess on top of a wrong one |
| F3b | the degradation contract for a knob the tool ignores | **A** | drive the step twice and read the exit code and the report keys |
| F4 | *(found while capturing)* an advertised component form no step id can express | **A** | enumerate the namespace, assert the validator accepts every member |

Nothing landed in B, C or D. No record needed `why_not_bucket_a`, and none was
discarded.

---

## F1 — and the rule it turned out not to be

**Ladder, T:** no. OpenROAD implements the site-creation command, the upstream
flow declares and consumes the variable, the distribution ships the
declaration. Ours was the only layer that did not read it. A fork change would
have been a fix to something that is not broken.

**Ladder, A:** yes — but not the rule the brief states, and the difference is
measured, not argued.

The stated generalisation is *"a step that cannot find a declared thing must
say WHICH views it read."* I drove the **pre-fix** producer, unmodified from
`origin/main`, at a distribution whose reference view carries only the
site-REFERENCE form and whose tech view carries the declaration
(`evidence/repro_f1.py`). What the refusal record actually contained:

```
verdict = FAIL
reason  = PAD_SITE_NOT_FOUND: PAD_SITE_NAME='io_site' is not a SITE in the IO
          cell library this run resolved (0 site(s) from 1 LEF(s); PAD-class: [])
io_cell_library = { "resolved": true,
                    "lefs": [".../libs.ref/proc_io/lef/io.lef"],
                    "n_masters": 3, "n_sites": 0, "pad_class_sites": [] }
```

It **enumerated the exact file it read**, said how many records it found in it,
and listed the empty result. The disclosure rule was **already satisfied by the
code that carried the bug**. A guard written to that rule would have run clean
on the pre-fix tree — and a guard that does not fire on the defect it was
written for is the mirror of the guard that fires on the state we just shipped.
Both are bugs.

The plugin also already owns that rule four times over, for the neighbouring
verdict: `gate_discloses_denominator_check` (a PASS must say how much it looked
at), `_gate_denominator`, `gate_zero_denominator_refuses_check`, `_sweep_reach`,
and `_shape_refusal` (a refusal that names what arrived). Per the brief's
one-line-reference instruction, that is the whole deliverable for the
disclosure half: **it exists, it is enforced, and it is not this defect.**

What *would* have caught F1 is a set difference — and measuring it myself
turned up the reason the guard's output must be NAMES and never a count.

HARVEST DEFINITION, because the same comparison gives different cardinals under
different defensible ones. Mine: every `PAD_*` token appearing in the upstream
config module, against every `PAD_*` token appearing anywhere in `_pad_ring.py`
(its two declared tuples plus any name the code references):

```
upstream config module                         20 PAD_* names
origin/main                names 11 of 20   missing 9, one of which is the
                                            declaration variable F1 is about
origin/jpadsite/pad-site   names 12 of 20   missing 8
```

The source report states this as *13 of upstream's 14*, which is a narrower and
also-defensible denominator (the pad STEP's own declarations, excluding the
library-file and bondpad-geometry variables). Both readings agree on the
finding and disagree on the number, which is exactly why the rule is a set
difference reported as a LIST: a count of a set nobody defined is not a
measurement.

The 8 still unaccounted for on the fix branch — the library-file and
bondpad-geometry variables — are genuinely outside this step. They are also in
NEITHER declared tuple, so nothing records that. That is the other half of the
same rule: out of scope must be *declared* out of scope, not silently absent.

Two enumerable lists, one subtraction, no judgement — so **Bucket A**, as
`upstream_input_set_pin`.

**The exact decision, named as the brief requires:** the input is the upstream
config module's declared variable list and this module's own declared-required
and declared-unperformed tuples. The decision is set difference. There is no
step in it a program cannot take.

---

## F2 — the same rule, one level down

**Ladder, T:** no. Upstream's own side arithmetic is correct and the tool
agrees with it. I did not take that on trust from the source report: I read
`pad_cfg.tcl` out of the pinned image. It computes both a width and a height
per instance and sums **only the width**, inside a loop that does not branch on
side. Our copy took the extent from the oriented footprint, so a side whose
orientation does not swap the axes summed the height.

**Ladder, A:** yes, and it is measured red/green rather than asserted.
`evidence/f2_pin_probe.py` walks the placement function's assignments, taints
every name whose value flows from the orientation-dependent footprint helper,
and asks whether the along-the-row extent is tainted:

```
origin/main                 along-from-oriented-footprint = True   (16 tainted names)
origin/jpadsite/pad-site    along-from-oriented-footprint = False  (2 tainted names)
```

**The exact decision:** the input is the function's AST. The decision is
reachability from one call. Deterministic.

### Why citing upstream is not the same as being pinned to it

Measured on the pre-fix tree, and it is the sharpest form of this finding: the
correct upstream rule was written down **one line above the code that violates
it**.

```
#    on every side: the rotation puts a cell's width along the row.
boxes = [PR.footprint(lib.masters[...], orient, units) for i in insts]
along = [b[0] if axis == "x" else b[1] for b in boxes]
```

The comment is right. The next statement takes the orientation-dependent
extent. The knowledge was present, correct, and cited — it just was not
executable, and nothing compared the prose to the code beneath it.

This is not one module's slip. Verified over program bodies: 6 programs both
reference an upstream tree and use comparison language, and reading all six,
**none** pins one of our computations against upstream's. They cite upstream as
documentation for what to expect — several say "measured out of the pinned
image, not remembered", which is the repo's own good habit — and then the
reading freezes into a comment at authoring time and is never re-checked. That
is exactly the gap this rule closes, and it is why the rule is about making the
citation executable rather than about requiring one.

F1 and F2 are the same rule at two granularities — the **input set** drifted
and the **arithmetic** drifted — which is worth saying plainly, because it means
one guard family closes both and the second instance was already latent when
the first shipped.

---

## F3 — the half that is the tool's, and it is not inertness

This is the one the brief asked me to think hardest about. The answer changed
under measurement.

### What was already recorded, and not chased

`evidence/rotation_probe/MEASURED.txt` in the source report ends with:

> SEPARATE OpenROAD oddity, observed and NOT chased: the SOUTH pad's
> orientation tracked the `-rotation_vertical` argument even though
> `-rotation_horizontal` was held at R0 for every run.

That is not a separate oddity. It is the explanation.

### The decisive second arm

The original probe varied ONE argument and read the vertical sides. I ran both
arms, one argument pair per process so no row could be reused
(`evidence/one.tcl`, `evidence/run.sh`,
`evidence/rotation_two_arm_MEASURED.txt`), and then confirmed row identity by
**die position** rather than by trusting the row names
(`evidence/loc.tcl`, `evidence/rotation_row_identity_MEASURED.txt`):

```
ROTH=R0  ROTV=R0    pw0 xMin=26.0    -> genuinely the WEST row (the 26 um offset)
                    ps0 yMin=26.0    -> genuinely the SOUTH row
ROTH=R90 ROTV=R0    pw0 MXR90 -> MX,  pw1 R90 -> R180     WEST/EAST MOVE
                    ps0 R0,   ps1 MX                      SOUTH/NORTH UNCHANGED
ROTH=R0  ROTV=R90   pw0 MXR90, pw1 R90                    WEST/EAST UNCHANGED
                    ps0 R0 -> R90,  ps1 MX -> MYR90       SOUTH/NORTH MOVE
```

**The two arguments are applied to each other's rows.** `-rotation_horizontal`
drives the vertical rows; `-rotation_vertical` drives the horizontal ones.
OpenROAD 26Q3-1607-g27fd905b8a; the source report's table was taken on
26Q3-1165, about 440 commits earlier, and shows the same vertical-side
constancy — so it reproduces across two builds.

The tool's **script layer is correct**: dumping the command body out of the
running binary shows each argument bound to its own variable and passed to the
compiled row builder in the documented order. The crossing is below it.

### Why this changes the ladder answer, and the ruling it does not overturn

*"The variable is inert"* and *"the variable is misrouted"* are different
defects. Inert is harmless at the default. Misrouted is not: at the default both
arguments carry the same value, so the two wrong assignments are
indistinguishable from the two right ones, and nothing fires **until someone
sets exactly one of them** — which is the case the ruling was written to catch.

**F3a is Bucket T, OpenROAD.** It is inside a forked tool; the plugin does not
place the rows; anything the plugin did here would be a correction stacked on a
wrong one. That is Bucket T's own test, taken literally.
Emitted: `candidates/bucket_T_forked_tool/ORGANIC-20260822-io-row-rotation-arguments-applied-to-opposite-rows.yaml`,
with `golden_sample` (derived, and labelled as derived — the tool ships no
reference output) and `bad_sample` (the measured table).

**F3b is Bucket A, and it is ours.** The degradation contract — proceed and
disclose at the value indistinguishable from never having set it, exit 2 NOT
DETERMINED at a deliberately declared one — is right whether or not the fork is
ever fixed, and it must not wait on it. The ruling stands exactly as made.

### The residual hole the measurement exposes, stated because it is mine to state

The shipped fix pins the vertical sides to the constant `{W: MXR90, E: R90}`
and refuses rc 2 when `PAD_ROTATION_VERTICAL` is declared non-default. Both are
correct **while `PAD_ROTATION_HORIZONTAL` is at its default**. Measured above, a
run that declares `PAD_ROTATION_HORIZONTAL=R90` and leaves the other alone
passes the guard, and the tool then places the west pad at MX — 350 um along a
vertical row where the step recorded 75. The guard is on the variable that was
measured; the geometry moves with the one that was not.

This is why record F3b generalises the rule to **the tool call** rather than to
the variable: every variable carried in the same call is in scope, not only the
one somebody happened to probe. That is the brief's own instruction —
*generalise the RULE, not the one variable* — applied to a fact the ruling did
not yet have.

---

## F4 — found while capturing, and deliberately left red

`backlog_sanitize_check` advertises four component forms, one of which is
`flow:<step>`. Its character class is `[\w_-]+`, and every step id in both
namespaces is dotted. Measured:

* capture-routing table: **0 of 39** step ids expressible as `flow:<step>`;
* canonical flow: **6 of 69** inexpressible — `0.5ic`, `1.6x`, `15.5ic`,
  `26.5ic`, `37.5ip`, `37.5ic`. One of the six is the step this whole capture
  is about;
* shipped backlog corpus: **no record uses the form at all**, which is what an
  unusable form looks like from outside — not an error, an absence.

**I did not fix it.** The fix widens a regex, and it would widen the regex that
had just refused a record of mine. A red is never made to go away by relaxing
what asks the question, and that binds hardest when the red is my own. The
record carries the measurement; my own Bucket-T record uses
`program:pad_ring_gen`, which is true on its own terms — it is the program whose
verdict the tool defect blocks — and the `generating_step` field already
carries the step.

---

## The general-core test, applied

None of the five rules reads a pad or a PDK literal:

* `upstream_input_set_pin` — two variable lists and a subtraction.
* `upstream_arithmetic_pin` — one AST and a reachability question.
* `unhonoured_knob_degrades_loudly` — an exit code and a report key.
* the Bucket-T record — two symmetric arguments and which case each selects.
* `component_vocabulary_admits_its_namespace` — a regex and an enumeration.

They were written here first. That is all that is pad-shaped about them.

---

## What was NOT done, and why

* **No new guard was landed, and the four Bucket-A rules are red for three
  different reasons.** Stated one by one rather than as a group, because they
  do not share a fix order:
  * **F1 and F2** would go RED on `origin/main` today, CORRECTLY — the defects
    they guard are fixed on `origin/jpadsite/pad-site` and that branch has not
    landed. Shipping a correct-but-red gate would block every push on the repo.
    Ordering dependency: **land `jpadsite/pad-site` first, then these two.**
    For F2 the red/green pair is already measured above and does not need
    re-deriving; for F1 the unaccounted-name lists for both trees are in
    `evidence/upstream_input_set_MEASURED.txt`.
  * **F3b** is RED, on **4 true positives**. An earlier version of this
    document said it had no population and was premature to land. That claim
    was made without measuring and it is wrong — see the correction below.
  * **F4** is red on `main` and stays red: nothing on any branch fixes it, and
    I declined to fix it tonight for the reason given in its own section.
* **F3b's guard has a population of 4, and that is the argument for it.**
  Corrected below; the earlier text here claimed the opposite without measuring.
* **No `--write-baseline`, on any gate.** No assertion relaxed, no regex
  widened, no test deleted, no baseline rewritten — including the one regex it
  would have been convenient to widen. No GDS touched, no pin moved, no rule
  deck relaxed.
* **The full `programs/tests` suite was not run** (standing measured-load
  constraint). What was run: `enhancement_emit` and `backlog_sanitize_check` on
  the emitted artefacts, the pre-fix reproduction, the AST predicate against
  both trees, and ten OpenROAD processes in the pinned image.
* **Not pushed to `main`. No version bumped.** The lander assigns it.

## Where the numbers came from

Every figure above is from a command run on this host tonight, not from the
source report. Where the source report and my measurement agree, I re-derived
it; where they disagree — `PAD_ROTATION_VERTICAL` being inert — the measurement
is in `evidence/` and the disagreement is the finding.

---

## CORRECTION — F1's Bucket-A rule, refuted by its own corpus sweep

The brief says a new guard must run clean on the current repo, and that a guard
which fires on the state we just shipped is a bug to be narrowed or dropped. I
swept the F1 rule over its whole population before proposing it further, and it
does not survive. Recording that here because the earlier version of this
document proposed it, and a wrong rule that was published as measured is worse
than one that was never written.

**The rule as first written:** *a re-implementation must account for every input
its upstream declares*, caught by a set difference. It fails in both directions
at once.

**Population** — programs that declare an upstream contract AND cite it by
path: **5 of 1232**.

| scoping of "upstream's input set" | unaccounted | modules that fire | catches the defect? |
|---|---|---|---|
| variables read by the CITED upstream files | 43 | 4 / 5 | yes, buried in 42 others |
| narrowed to upstream's own `pdk=True` set (145 of its 406) | 19 | 3 / 5 | **no — control on the pre-fix tree returns []** |
| the upstream STEP's declared inputs (20, introspected from the running library) | — | — | **no — the variable is not in the list** |

The narrowing in row 2 is not one I invented to fit the answer: it is upstream's
own `pdk=True` flag, which separates facts about the distribution from harness
plumbing, and it correctly removes `SCRIPTS_DIR` / `STEP_DIR` / `DESIGN_NAME` /
`CURRENT_GDS` without anyone deciding they should go. It still fails.

**Why no scoping contains it, structurally.** The dropped variable is declared
in upstream's PDK variable table and consumed in a COMMON helper sourced by many
steps. It is in neither the pad step's own scripts nor its `config_vars` —
upstream's model does not attach it to the step at all. It is a fact about the
distribution that any step touching pads inherits implicitly, so a set
difference over *this step's declared inputs* cannot contain it under any
reading of that phrase.

### What survives — after a second formulation that I adopted and then had to drop

The rule below is the **third** formulation. The second one is worth recording
because I adopted it *before* sweeping it, which is the exact mistake this
section exists to document.

> ~~A refusal on absence must have **read every view** the distribution ships.~~
> **DROPPED.** It fires on the defect and both fixture arms looked clean — but
> sweeping it afterwards: population 14, of which 10 refuse after a lookup into
> a distribution view, and **8 of those 10 read exactly one view, for good
> reasons**. A rule that fires on 8 of 10 correct programs is formulation 1's
> bug arrived at from the other side.

> **A refusal that a declared name is ABSENT must be FALSIFIED against the
> views that were not read.**

It fires only when the refused **name** is actually findable in a view the step
did not open — a grep over directories that exist, for a string the step itself
chose. There is no judgement in it, and it **cannot** fire on a step that read
one view and was right, because the name is not there. It refuses the
*refusal*, never the design.

Measured, both arms, **with the negative control formulation 2 never had**
(`evidence/f1_final_probe.py`):

```
PDK declares the name in the other view   refused 'io_site'
                                          unread   [libs.tech]
                                          findable libs.tech/.../config.tcl  -> FIRES

PDK declares it NOWHERE  (the control)    refused 'io_site'
                                          unread   []
                                          findable none                     -> silent
```

The second arm is the one that matters: a genuine absence stays a genuine
absence, and the guard never converts a correct refusal into a finding.

`recoveries.json`'s F1 record now carries this rule and a `supersedes` field
naming what it replaced. F2's record is untouched: its pin is a taint walk with
its own measured red/green, and it does not depend on any variable set.

**What this costs the general claim.** F1 and F2 are no longer "the same rule at
two granularities" — that was the earlier version of this document and it was
wrong. F2's arithmetic pin works because our module cites the upstream file and
the file can be read. F1's input-set pin does not work, because the input that
was dropped is not attached to the step in upstream's own model. The general
lesson that survives is narrower and more useful: **a re-implementation can be
pinned against upstream where upstream's artefact is CITED and READABLE, and
cannot be pinned against upstream's implicit distribution-wide facts at all —
those have to be caught on the output side, by asking what the step read.**

---

## CORRECTION — F3b has a population of four, and the repo has absorbed none of them

I wrote that nothing on `main` declares a variable the tool does not honour, so
a guard would run over zero subjects. I had not measured it. Measuring it: the
class has **four independent instances on the current tree, in four different
subsystems**, found by sweeping all 1232 programs for a not-honoured claim whose
subject is a NAMED TOOL rather than one of our own gates (77 raw hits narrow to
12, and 12 read by hand give 4).

| instance | the input the tool does not honour |
|---|---|
| a synthesis techmap module | a declared cell map that silently does not bind |
| a timing-diagnosis module | a delay target the mapper silently ignores |
| two analog layout modules | a declared placement construct the stream-out does not honour |
| the pad ring | the rotation arguments, crossed inside the tool |

**Contract compliance across the four: 0 of 4.** None carries the non-honouring
as a machine-readable record; all four wrote the lesson as prose in whichever
module happened to find it.

### The signature, and why the class survives review

Measured across the instances, they share one shape: **the artefact is
indistinguishable from never having set the input.** One of them produced a
BYTE-IDENTICAL netlist, and cost 22 % of a timing path before anyone looked. The
pad ring produces an identical ring at the default, because the two crossed
arguments carry the same value there. There is nothing in the output to review,
which is exactly why four separate people had to rediscover it.

### What this changes

The guard is not premature — it is overdue. It is still RED on `main`, but the
red is **4 true positives**, not a false one, and the population is the work
list for whoever lands it. The landing constraint is the same as F1 and F2's and
the reason is much better: the contract is worth having precisely because the
repo has found this class four times and absorbed it zero times.

`recoveries.json`'s F3b record now carries the population, the failure
signature, and this landing status.

---

## What this whole exercise actually taught, stated once

Three of the rules I proposed in the first pass did not survive contact with
their own populations, and every one of them was refuted by the same cheap move:
**run the rule over its population before proposing it.**

| claim I published | how it died |
|---|---|
| F1: pin the input SET against upstream | over-fires 4/5; narrowed, stops catching the defect |
| F1 again: a refusal must have READ every view | over-fires 8/10 — adopted before it was swept |
| F3b: the unhonoured-knob rule has no population | it has four instances, in four subsystems |

None of the three was visible from the one case that motivated it. All three
took a single sweep to expose. That is the durable lesson of this capture, and
it is worth more than any of the five rules in it:

> **A rule is not a rule until it has been run over its own population.**
> A rule measured only on the case that produced it has been measured on the
> one input it cannot fail.

It applies to this document too — which is why the F1 record carries a
`formulation_history` field naming both rules it replaced, rather than
presenting the surviving one as if it had been the idea all along.

---

## The one change to shipped plugin content, and its red

This branch changes exactly one shipped file: it adds a `phase3.pad_ring` entry
to the capture-routing table. Its red, shown by removing the entry and
re-running the same emit:

```
WARNING: 4 Bucket-A record(s) had no routable `bucket_A_program`
  - step='phase3.pad_ring' rule='upstream_input_set_pin'
  - step='phase3.pad_ring' rule='upstream_arithmetic_pin'
  - step='phase3.pad_ring' rule='unhonoured_knob_degrades_loudly'
  - step='phase3.pad_ring' rule='component_vocabulary_admits_its_namespace'
```

Every Bucket-A sketch in this capture is skipped without it, and no
Bucket-A file is written at all. The step needed its own entry because its
producer and its gate are `pad_ring_gen` / `pad_ring_check`, so it must NOT
inherit its floorplan neighbour's routing to the PnR runner. The four suites
that read the table are green with the entry in place (above).

---

## Reproduce

On a clean tree (`git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`):

```
# the capture itself
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py \
    --records _jcapsha_notes/recoveries.json --out-dir _jcapsha_notes/candidates
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/backlog_sanitize_check.py \
    --file _jcapsha_notes/candidates/bucket_T_forked_tool/*.yaml

# the pre-fix reproduction and the AST pin
python3 _jcapsha_notes/evidence/repro_f1.py
python3 _jcapsha_notes/evidence/f2_pin_probe.py origin/main origin/jpadsite/pad-site

# the two-arm tool measurement (needs the pinned image; --skip FIRST)
docker run --rm -v <evidence>:/w <image> --skip bash /w/run.sh
docker run --rm -v <evidence>:/w <image> --skip bash /w/run2.sh
```

Measured this session, all on a clean tree:

```
enhancement_emit                                     rc 0   A=4 T=1, 0 unrouted
backlog_sanitize_check on the emitted record         rc 0   0 hard, 0 soft
pytest: the four suites that read the routing table  rc 0   87 passed, 4 skipped
    test_capture_routing_consistency, test_enhancement_emit,
    test_issue1130_wiring_population_parity, test_tracked_json_yaml_parses_check
suite_write_guard                                    PASS   the session wrote
                                                            nothing into the tree
```

The Bucket-A sketch reproduces byte-identically from the committed
`recoveries.json`. The emitted record's `submitted_at` will not: it is the
instant the record was filed, and it is a measurement rather than a constant.

The full `programs/tests` suite was NOT run — standing measured-load
constraint. The four suites above are the ones that read the file this branch
changes.
