# CONVERGE / CAPTURE / DISTILL of the pad-site recovery

> **READ THIS FIRST — the Bucket-T record in this capture is WITHDRAWN.**
> I filed a defect against a forked EDA tool claiming it applied two named
> rotation arguments to each other's rows. Every measurement behind that claim
> is correct. The inference from them was not: the tool's own documentation, at
> the pinned commit, defines "horizontal" as the horizontally-**oriented pads**,
> which sit on the east and west rows. Under that convention every number I
> measured is documented behaviour. **The tool is right and I was wrong**, and I
> reasoned about what the argument names must mean without fetching the page
> that defines them.
>
> The real defect is **ours and it is worse**: our step's side-to-variable
> mapping is **inverted** with respect to the tool's contract, and the shipped
> pad-ring fix on the un-landed branch is built on that inversion. Sections
> below are corrected; `evidence/f3_bucket_T_WITHDRAWN.txt` has the full
> account.

Agent `jcapsha`, 8HD-d, 2026-08-22.
Branch: **`jcapsha/pad-site-capture`**, off `origin/main` @ `a00f53f20`.
Source read in full before anything was written: `_jpadsite_priv/RESULT.md` on
8hd-3 (476 lines), its `evidence/`, and the whole `origin/main` ->
`origin/jpadsite/pad-site` diff (4 files, 858 insertions).

Deliverable: `recoveries.json` (**7 records — 6 Bucket-A, 1 Bucket-D**)
emitted through
`enhancement_emit.py` into `candidates/`: **`enhancement_emit` rc 0, A=6 D=1,
no unrouted Bucket-A record.** `backlog_sanitize_check` is NOT claimed as a
second green here — see the note in the measured block at the end: since the
Bucket-T record was withdrawn this capture emits no backlog YAML, so that gate
has nothing to read and its rc 0 is vacuous.

---

## The one-line answer per finding

| # | finding | bucket | why it stopped there |
|---|---------|--------|----------------------|
| F1 | the step read the wrong PDK view | **A** | a set difference over the view directories that exist on disk — see the correction below; the rule this table first carried was refuted by its own sweep |
| F2 | the extent came from the oriented footprint | **A** | a taint walk over one function's assignments |
| F3a | ~~the tool does not honour the rotation variable~~ | **D — WITHDRAWN** | refuted by the tool's own documented contract; replaced by F3c |
| F3b | the degradation contract for a knob the tool ignores | **A** | drive the step twice and read the exit code and the report keys |
| F4 | *(found while capturing)* an advertised component form no step id can express | **A** | enumerate the namespace, assert the validator accepts every member |
| F3c | our side↔variable mapping is inverted vs the tool's contract | **A** | two four-entry mappings, compared |
| F3d | the opposite side is a MIRROR upstream and a half turn in ours | **A** | two named transforms, compared — **present at the default** |

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

Two enumerable lists, one subtraction, no judgement — so **Bucket A**. It was
filed as `upstream_input_set_pin`; the corpus sweep further down refuted that
form and the record now ships as
`refusal_on_absence_falsified_by_the_declaration_grammar`. The old name is left
standing in this sentence's history only here, where the correction is named.

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
~~Emitted as a forked-tool backlog.~~ **WITHDRAWN** — the record is now a Bucket-D
discard, so no forked-tool backlog is emitted and the directory no longer exists.
The withdrawal and its reason are in `candidates/bucket_D_discarded.md` and
`evidence/f3_bucket_T_WITHDRAWN.txt`. What follows described the withdrawn record:
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

None of the **six** Bucket-A rules reads a pad or a PDK literal. Stated as what
each one's LOGIC actually consumes, which is the brief's test — not what it was
named after:

* `refusal_on_absence_falsified_by_the_declaration_grammar` — a refused name, a
  set of unread views, and that class's own declaration parser. Reads a
  grammar, never a pad.
* `upstream_correspondence_declared_then_pinned` — a declared upstream file, a
  declared primitive, and an AST. Reads a correspondence, never a dimension.
* `unhonoured_knob_degrades_loudly` — an exit code and a report key.
* `component_vocabulary_admits_its_namespace` — an advertised prefix and the
  namespace it points at, enumerated from that namespace's own source.
* `upstream_convention_not_inverted` — two four-entry mappings, compared.
* `opposite_side_transform_matches_upstream` — two named transforms, compared.

The last two are the sharpest evidence for the brief's own point. They are
named for sides of a pad ring and their logic contains **no side and no pad**:
one asks whether a re-implementation inverted a documented convention, the
other whether it substituted a rotation for a mirror. Both are questions about
any symmetric pair — a differential pair, a bidirectional bus, a mirrored
macro. They were written here first, and that is all that is pad-shaped about
them.

THE LIST PREVIOUSLY READ "five rules" AND NAMED THE BUCKET-T RECORD as a member.
Both were wrong by the time anyone could read them: the T record was withdrawn
to D — so the general-core test was being applied to a finding that no longer
existed — and two rules were added after the count was written.

---

## What was NOT done, and why

* **No new guard was landed, and the six Bucket-A rules are red for four
  different reasons.** Stated one by one rather than as a group, because they
  do not share a fix order. (This read "four" while two more records — F3c and
  F3d — were added below it. A count in a summary describing a list that is
  still growing, which is the defect this whole capture is about, landing on
  the capture's own prose for the second time.)
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
  * **F3c and F3d** are red on `main` **and red on the fix branch too**, which
    is a different status from F1/F2 and changes the landing order for them:
    landing `jpadsite/pad-site` does NOT turn these green, because that branch
    does not repair what they guard. MEASURED by running each predicate against
    `git show <ref>:<file>` on both refs — no checkout, no tree touched:

    ```
    F3d  origin/main               N = rotate_cw       E = rotate_cw
         origin/jpadsite/pad-site  N = rotate_cw       E = (NO CALL AT ALL)
    F3c  origin/main               HORIZONTAL -> [N,S]  VERTICAL -> [E,W]
         origin/jpadsite/pad-site  HORIZONTAL -> [N,S]  VERTICAL -> (nothing)
         the tool's contract       HORIZONTAL -> [E,W]  VERTICAL -> [N,S]
    ```

    The `(no call at all)` is the finding rather than a detail of it: the fix
    branch was built on the conclusion that the variable is inert, so it
    REMOVED that variable's effect instead of routing it to the sides the tool
    documents it for — making genuinely inert a variable that was merely
    misrouted, which is the one outcome that makes the original diagnosis true
    after the fact. This is NOT a reason to hold that branch: its site fix is
    real, verified on four PDK trees, and independent of all of this. These two
    are the argument for a FOLLOW-UP.
    `evidence/f3cd_red_on_both_trees_MEASURED.txt`.
* **F3b's guard has a population of 4, and that is the argument for it.**
  Corrected below; the earlier text here claimed the opposite without measuring.
* **No `--write-baseline`, on any gate.** No assertion relaxed, no regex
  widened, no test deleted, no baseline rewritten — including the one regex it
  would have been convenient to widen. No GDS touched, no pin moved, no rule
  deck relaxed.
* **The full `programs/tests` suite was not run** (standing measured-load
  constraint). What was run: `enhancement_emit` on the emitted artefacts, the
  pre-fix reproduction, the AST predicate against both trees, and ten OpenROAD
  processes in the pinned image. `backlog_sanitize_check` is deliberately NOT
  in that list any more — it has no input left to read.
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
| ~~the pad ring~~ | ~~the rotation arguments~~ — **NOT A MEMBER**; see below |

**Three distinct defects across four modules.** Contract compliance: **0 of 4.** None carries the non-honouring
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
| F2: the arithmetic pin generalises | the shape it keys on occurs at **224 sites** |
| F4: (implied) a general vocabulary rule | population is **1** — a single instance, not a class |
| F1 formulation 3 is silent on the rest "by construction" | over-fires on real PDKs — that was an argument, not a measurement |
| F1 is a general rule | its population is **1 of 10** — a correct single-site rule |

None of the seven was visible from the one case that motivated it. All seven took
a single sweep to expose. Two are sharpest: **F2**, because I wrote the lesson
into this document and then did not apply it to F2 for two more rounds; and
**formulation 3's "by construction"**, because a by-construction argument is
the exact shape of a claim that feels too obvious to measure. That is the durable lesson of this capture, and
it is worth more than any of the five rules in it:

> **A rule is not a rule until it has been run over its own population.**
> A rule measured only on the case that produced it has been measured on the
> one input it cannot fail.

It applies to this document too — which is why the F1 record carries a
`formulation_history` field naming both rules it replaced, rather than
presenting the surviving one as if it had been the idea all along.

---

## CORRECTION — F2 does not generalise, and what that changes about the rule

I swept F1's rule three times, F3b's, and F4's population. I did not sweep F2's,
and I had written the lesson about exactly that into this document two rounds
earlier. Sweeping it now.

The predicate I measured red/green is written for ONE computation: it knows the
along-the-row extent must not be orientation-transformed, and that knowledge
came from reading upstream, not from the code's shape. Over the population of
modules that cite an upstream computation by path, the shape it keys on — a
value flowing through a transform into an aggregate — occurs at **224 sites**.
That is simply what ordinary code looks like. **A program cannot pick the 1 site
of 224 that matters.**

### Applying the brief's own anti-excuse test, rather than retreating to judgement

The brief is explicit that *"it needs judgement"* is the most over-used excuse
to skip the program work, and that before accepting it I must name the exact
input and the exact decision. Named:

* **Input the program would see** — the AST of our module, and the text of the
  upstream file.
* **The decision it cannot make from that input** — the **correspondence**:
  which of our functions re-implements which upstream loop. Neither text
  declares it. Our function does not say which upstream loop it mirrors; the
  upstream loop does not say what re-implements it.

And that is where it stops being an excuse, because **the missing input is
declarable, not unknowable.** The information already exists in the module — as
prose. It cites the upstream file by path, and on the pre-fix tree the comment
one line above the defect names the correct primitive. So the rule changes
shape rather than dropping:

> **A re-implementation must DECLARE which upstream computation it mirrors and
> which primitive that computation measures with. The declaration is then
> checkable, and the check is a program.**

The deterministic work is the declaration format plus a checker that reads the
named upstream file, confirms the named primitive, and asserts our function does
not transform it before aggregating. It stays **Bucket A** — the program work is
real and it is not a heuristic detector. What was wrong was believing detection
alone could be the program.

The one-computation red/green measurement stands and is unaffected; what it
never established — and what an earlier version of this document claimed it
did — is that the same predicate generalises.

## CORRECTION — F4's population is one

Swept for validators carrying a `PREFIX:IDENTIFIER` alternation: **exactly one
in 1232 programs.** F4 is a real defect with a real measurement, but it is a
single instance, not a class with a corpus. Recorded as such rather than left to
read as a general rule by sitting in a list of them.

---

## CORRECTION — "silent by construction" was an argument, and it was wrong

Having adopted formulation 3, I wrote that it is silent on the other eight
in-scope programs *by construction*, because the refused name would not be in
the views they skipped. That is an argument. The measurement disagrees.

Formulation 3 as I implemented it greps the unread views for the refused name.
Run on **both real open PDKs**, with a step that read the reference view and
refused:

```
                                         gf180mcuD                    sky130A
real site declared in the tech view      FIRES (correct)              FIRES (correct)
name that exists nowhere                 silent (correct)             silent (correct)
SHORT generic name  'io'                 FIRES on a node-info file    FIRES on a node-info file
plausible-but-absent 'core'              FIRES on a device-model file FIRES on a simulator init
```

Two false positives on each PDK. A bare substring search finds a short name
everywhere, and nothing about "construction" prevents that.

### The amendment, and where it comes from

> **The falsification must ask through the DECLARATION GRAMMAR for that class
> of thing, never through a free-text search.**

The step already owns a parser for that grammar — it is how the fixed producer
reads the declaration in the first place — so the check reuses the step's own
parser instead of inventing a search. Asking the same question that way, on the
same two PDKs, all four probes:

```
declared-in-unread-view names   gf180mcuD: [GF_COR_Site, GF_IO_Site]
                                sky130A:   [sky130_io, sky130_io_corner]

real site declared in tech view  FIRES, with its size      FIRES, with its size
exists nowhere                   silent                    silent
SHORT generic name  'io'         silent                    silent
plausible-but-absent 'core'      silent                    silent
```

Clean on both, on every probe. The rule survives; the implementation of it that
I published did not.

---

## CORRECTION — F1's population is one, and it is not the general rule I kept calling it

The amendment above says the falsification must use the step's **own**
declaration parser. That has a consequence I did not check when I wrote it: the
rule applies only where such a parser exists.

Measured over the 10 in-scope modules — those that refuse on a named absence
after a lookup into a distribution view — **exactly one owns a declaration
parser.**

So after four formulations, a measured red/green pair, and a clean
false-positive profile on two real distributions, the honest description of F1
is: **a correct, well-measured, SINGLE-SITE rule.** Not the general one this
document called it in every earlier version. It sits beside F4, which is also a
population of one.

### The widening I did not take, named so it is not lost

There is a stronger reading available: instead of *use the parser you have*,
demand that **any** step refusing on absence **own** a parser for the
declaration grammar of the thing it refuses about. Under that reading the
population is 10 and the rule fires on 9.

I did not adopt it, and the reason is this document's own history: 9-of-10 is
the exact shape that has been wrong six times here, and I have not measured
whether those nine refuse about things that have a declaration grammar at all —
several refuse about our own artefacts, which have none. It is recorded as
**UNSWEPT**, so that nobody adopts it the way I adopted formulation 2.

### What the capture actually delivers, stated plainly

Of the five rules proposed, measured honestly:

| rule | status after sweeping |
|---|---|
| F1 | correct, single-site (population 1 of 10) |
| F2 | does not generalise as detection; becomes *declare the correspondence, then check it* |
| F3a | **WITHDRAWN** — the tool was behaving as documented; replaced by the convention-inversion record, which is ours |
| F3b | **population 1**, and that one already implements half the contract by hand — not the class I claimed. Its motivating case is not a member either. The unowned half (the exit-code tier) is still real |
| F3c | our side-to-variable mapping is **inverted** against the tool's documented contract — the real defect the withdrawn Bucket-T record was masking |
| F4 | correct, single instance (population 1 of 1232) |
| F3d | the opposite-side transform: a mirror upstream, a half turn in ours — **present at the default**, and it passes every geometric gate because the two share a bounding box |

The item most worth someone's time is **F3d**. It is the only finding here
that needs no declaration to occur — it is present at the default, on both
axes — and the only one that is invisible to every gate the step owns, because
the gate reduces orientation to an extent and a half turn and a mirror share
one. F3b, which I called this three times, is a population of one that already
does half of itself.

---

## CORRECTION — the Bucket-T record is withdrawn, and the real defect is ours

I called this "the strongest item in the capture". It was the weakest, and it
was weak in the way that matters most: the numbers were real and the reading of
them was mine.

**What the tool documents**, fetched at the exact pinned commit:

| argument | documented meaning |
|---|---|
| `-horizontal_site` | the site for the horizontal pads — **east and west** |
| `-vertical_site` | the site for the vertical pads — **north and south** |
| `-rotation_horizontal` | applied to the horizontal sites; default `MXR90` **when the same site is given for both** |
| `-rotation_vertical` | applied to the vertical sites; default `R0` for the southern row |

"Horizontal" names the horizontally-**oriented pads**, not the horizontal rows.
Under that convention **every number in my two-arm table is the documented
behaviour** — including the `MXR90` I measured on the western pad at the
default, which the table above predicts exactly, because the caller passes the
same site to both arguments. The source assigns rows the same way and is not
crossed.

**How I got it wrong.** I dumped the tool's script layer, confirmed it passes
the two arguments in declared order, and then reasoned about what the argument
*names* must mean — without ever fetching the page that defines them. Calling
that "measured" because the numbers beneath it were measured is the failure.

### What is actually wrong — and it is ours

```
ours   PAD_ROTATION_HORIZONTAL -> SOUTH / NORTH      PAD_ROTATION_VERTICAL -> WEST / EAST
tool   rotation_horizontal     -> EAST  / WEST       rotation_vertical     -> NORTH / SOUTH
```

**Inverted on both axes**, on the current tree and on the fix branch alike, and
invisible at the default because both variables carry `R0` there. That is the
same class as the other two findings — a re-implementation drifting from its
upstream — this time on the **convention** rather than the input set or the
arithmetic. It is now its own Bucket-A record.

### What this does to the shipped fix, stated plainly

The pad-ring fix on the un-landed branch is built on the inverted premise. It
concludes the vertical-named variable is **inert** because changing it did not
move the west and east sides. Correct observation, wrong conclusion: it moves
the north and south sides, exactly as documented. The fix then pins the west and
east orientation to a measured constant and **refuses `rc 2`** when that
variable is declared non-default — refusing a run the tool would have honoured.

The geometry it produces at the default is still right. The reason recorded for
it is not, and the refusal is wrong. This **supersedes my own earlier claim**
that the shipped fix merely guards the wrong one of the two variables; the
premise underneath it is what is wrong.

---

## CORRECTION — F3b's motivating case is not a member of F3b's class

The withdrawal above has a consequence for the rule I called the most valuable
item in this capture, and it must be said rather than left for a reader to
notice.

F3b is the contract for *a config variable the tool underneath does not
honour*. The case that produced it — the pad rotation — **is not an instance of
that class.** The tool honours that variable exactly as it documents; what was
wrong was our own mapping of it to the wrong pair of sides.

So the honest provenance is: **the class was discovered from a false premise,
and then validated by a sweep that found three genuine members which have
nothing to do with pads** —

| instance | the input the tool does not honour |
|---|---|
| a synthesis techmap module | a declared cell map that silently does not bind |
| a timing-diagnosis module | a delay target the mapper silently ignores; produced a **byte-identical netlist** and cost 22 % of a timing path |
| two analog layout modules | a declared placement construct the stream-out does not honour |

Three distinct defects, four modules, **0 of 4 carrying the non-honouring as a
machine-readable record.**

The rule stands — on those three, not on the case that suggested it. Anyone
weighing whether to build it should weigh it on them. Earlier text in this
document counted the pad ring as a fourth instance; it is not one, and a rule
whose population is padded by a refuted member is exactly the shape this
document has spent nine corrections learning to distrust.

---

## The finding that only appeared once I RAN what I had been reading

F3c — our side-to-variable mapping is inverted — was supported by reading: our
code, the tool's documentation, the tool's source. It was never *run*. Running
it turned up a second divergence in the same function, and a worse one.

```
at the DEFAULT — nothing declared at all:

  ours   SOUTH = R0     NORTH = R180   <- rotate_cw(..., 2), a half turn
  tool   SOUTH = R0     NORTH = MX     <- north = south.flipX(), a MIRROR
```

The tool states the rule in its own source, for both axes:

```cpp
north_rotation_ver = south_rotation_ver.flipX();
east_rotation_hor  = west_rotation_hor.flipY();
```

Ours applies a half turn on both, through a helper whose docstring says "one
quarter turn clockwise". **A mirror is not a half turn.**

### Why nothing caught it, and why it is the worst finding here

For a rectangular footprint a half turn and a mirror occupy the **same bounding
box**. So the fit sum, the spacing arithmetic, abutment, and BTerm coverage all
agree under either — every geometric gate this step owns passes. What differs is
which edge the cell's **pins** face: a mirrored pad and a rotated pad present
their bond pad and their core-side signal on opposite edges. The ring is
internally consistent, passes its own checks, and faces the wrong way.

And unlike everything else in this capture, **it needs no declaration to appear.**
Every other finding here waits for somebody to set a variable. This one is
present at the default, with no pad configuration written, on both axes.

It is the fourth instance of the one class this capture keeps finding: a
re-implementation drifting from the upstream whose behaviour it claims to
reproduce — on the **input set**, on the **arithmetic**, on the **convention**,
and now on the **transform**.

### The lesson, restated in the form this one taught it

Earlier this document arrived at *a rule is not a rule until it has been run
over its own population.* This finding sharpens the same edge one notch:

> **A finding is not a finding until the thing it describes has been RUN.**
> Reading our code, reading the tool's source, and reading its documentation —
> all three agreeing — still missed a divergence that one execution exposed
> immediately.

---

## The one change to shipped plugin content, and its red

This branch changes exactly one shipped file: it adds a `phase3.pad_ring` entry
to the capture-routing table. Its red, shown by removing the entry and
re-running the same emit:

```
WARNING: 6 Bucket-A record(s) had no routable `bucket_A_program`
  - step='phase3.pad_ring' rule='refusal_on_absence_falsified_by_the_declaration_grammar'
  - step='phase3.pad_ring' rule='upstream_correspondence_declared_then_pinned'
  - step='phase3.pad_ring' rule='unhonoured_knob_degrades_loudly'
  - step='phase3.pad_ring' rule='component_vocabulary_admits_its_namespace'
  - step='phase3.pad_ring' rule='upstream_convention_not_inverted'
  - step='phase3.pad_ring' rule='opposite_side_transform_matches_upstream'
```

RE-DERIVED 2026-08-22. The block above previously showed FOUR records under two
rule names that no longer exist — the two F1/F2 rules were renamed by the
corrections below, and F3c and F3d were added after this transcript was taken.
Re-run by removing the entry and restoring it with a reverse edit, never
`git checkout`; `git status` was empty afterwards.

Every Bucket-A sketch in this capture is skipped without it, and no
Bucket-A file is written at all. The step needed its own entry because its
producer and its gate are `pad_ring_gen` / `pad_ring_check`, so it must NOT
inherit its floorplan neighbour's routing to the PnR runner. The four suites
that read the table are green with the entry in place (above).

---

## Landing readiness, verified against current `main` (not against the fork point)

`main` has moved **30 commits** since this branch forked (`a00f53f20` →
`81cd5321b`), and it touched the one shipped file this branch changes — someone
added 8 routing entries (`ppa.*`, `capture.*`, `repo.*`) while I added one.

A clean merge proves nothing about semantics, so the merged tree was built and
**run**, in a throwaway worktree, not inspected:

```
merge onto origin/main @ 81cd5321b     rc 0, zero conflict markers
routing table after merge              47 steps — my phase3.pad_ring present,
                                       all 8 of main's new entries preserved
pytest on the MERGED tree              87 passed, 4 skipped
enhancement_emit on the MERGED tree    rc 0, A=6 / D=1, routed to
                                       programs/pad_ring_gen.py, nothing unrouted
```

RE-RUN 2026-08-22 against `origin/main` still at `81cd5321b` (checked, it has
not moved), from branch head `eede2f5d9`. Every line above is from that re-run,
not carried forward — the `A=4 / T=1` it replaces was measured before the
Bucket-T record was withdrawn to D and before F3c and F3d were filed, so it
named a bucket this capture no longer emits. Split by suite, with the load
beside each, because one of them is load-dependent:

```
three routing suites          80 passed, 4 skipped   9s    load 45.8 -> 43.7
test_issue1130_..._parity      7 passed             69s    load 41.7 -> 39.6
                                                    -----
                                                    87 passed, 4 skipped
suite_write_guard             PASS on both — the session wrote nothing
```

The load-dependent suite **passed at load 41.7**, where the session below
records it timing out at load 64.1 and passing at ~4.8.

CARRIED FORWARD TO THE TIP, AND THE CARRY IS PROVEN RATHER THAN ASSUMED. Those
numbers were measured at branch head `eede2f5d9`; three commits landed after
it. Re-running at the tip was attempted and abandoned at load **104.6 on 32
cores** — 3.3x oversubscribed, where the harness bound is mine and not a
verdict about the code. So the question was answered the cheap way instead:

```
files changed eede2f5d9..HEAD    _jcapsha_notes/PROGRESS.md
                                 _jcapsha_notes/RESULT.md
                                 _jcapsha_notes/evidence/f3cd_..._MEASURED.txt
referenced by the four suites    0 of 4, for each of the three
```

Three markdown/text files inside the capture bundle, and no suite names any of
them. The measurement cannot have moved. This is the one carry-forward in this
document that is allowed, and only because the reachability was checked instead
of the plausibility. A third point at an
intermediate load is worth more than the two extremes: it is the observation
that would have been missing had the bound simply been raised.

Neither side's entries were lost and neither displaced the other — the two
additions are at different points in the same object. The branch is landable on
`main` as it stands today.

---

## One of these four suites is LOAD-DEPENDENT, and I reported it green without saying so

Late in the session the suite went red. It is worth writing down because I had
published "87 passed, 4 skipped" several times without the one number that
makes it reproducible.

```
                                     elapsed   load average (32 cores)
suite green, repeatedly this session    33s     ~4.8
suite RED                              113s     64.13
the timing-out program alone           117s     64.13   (its documented
                                                         baseline: 18.9-20.3s)
```

The failure is `subprocess.TimeoutExpired` at the 55s bound in
`test_issue1130_wiring_population_parity`, **not** an assertion. That test
documents its own basis — the program was measured at 18.9–20.3s and 55s is
~2.7× the slowest observed. At load 64 on 32 cores the program runs ~6× its
baseline, which the oversubscription fully accounts for.

**Attribution, proven rather than assumed:** this branch changes exactly one
shipped file, and the program that timed out contains **zero** references to it.
The change cannot reach it.

**What I did not do: raise the timeout.** The bound is an assertion about how
long the program may take. Raising it to turn a red green is the one move
forbidden here, and most of all when the red is environmental and the bound is
correct.

**Established by a positive control, not asserted.** Wall clock is the wrong
instrument on a contended host, so I measured CPU time, which does not inflate
the same way — and it came back at ~2× the program's documented baseline, which
pointed *away* from the load explanation. Only a control settled it: the sibling
program in the same test, which **passed**, is inflated ~1.76× on the same host
against its own baseline, versus ~2.02× for the failing one. The control is
inflated too, by a comparable factor, so the failing program is not anomalous
against a passing one; the residual 15 % tracks its 592 MB peak RSS.

So the status of that one suite is **environmental, established** — not green on
a loaded host, and not a regression. Worth noting what the detour bought: had
the control come back near its baseline, the same red would have been a real
performance regression on `main`, and my first write-up would have shipped
"environmental" straight over the top of it. The other three suites and
every gate in this capture are unaffected and were re-run green. A reader
reproducing this on a busy host should expect the same timeout and should read
the load before reading the verdict.

---

## Reproduce

On a clean tree (`git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`):

```
# the capture itself
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py \
    --records _jcapsha_notes/recoveries.json --out-dir _jcapsha_notes/candidates
# (no forked-tool backlog is emitted any more -- the record was withdrawn to
#  Bucket D. `backlog_sanitize_check` is the gate that would read one.)

# the pre-fix reproduction and the AST pin
python3 _jcapsha_notes/evidence/repro_f1.py
python3 _jcapsha_notes/evidence/f2_pin_probe.py origin/main origin/jpadsite/pad-site

# the two-arm tool measurement (needs the pinned image; --skip FIRST)
docker run --rm -v <evidence>:/w <image> --skip bash /w/run.sh
docker run --rm -v <evidence>:/w <image> --skip bash /w/run2.sh
```

Measured this session, all on a clean tree:

```
enhancement_emit                                     rc 0   A=6 D=1, 0 unrouted
backlog_sanitize_check                    rc 0 BUT VACUOUS — DO NOT COUNT IT
    This line used to read "on the emitted record  rc 0  0 hard, 0 soft" and
    was true when the Bucket-T record emitted a backlog YAML. That record was
    withdrawn to Bucket D, so `candidates/` now holds no `bucket_C_backlogs/`
    at all and the gate's population is EMPTY. Measured rather than reasoned:

        $ backlog_sanitize_check.py --dir <the emitted backlog dir>
        {"pass": true, "files_checked": 0, "note": "no YAML files found"}
        rc 0

    A green over nothing. It is left in this list, struck, instead of being
    deleted, because silently dropping it would leave the earlier claim
    standing unexplained in the two places above that cited it — and because a
    capture whose subject is the empty denominator should not quietly retire
    its own instance of one.
pytest: the four suites that read the routing table  rc 0   87 passed, 4 skipped
    test_capture_routing_consistency, test_enhancement_emit,
    test_issue1130_wiring_population_parity, test_tracked_json_yaml_parses_check
    -- MEASURED AT load average ~4.8 on 32 cores, in 33s. The load belongs
       beside the number: see the load-dependence note below.
suite_write_guard                                    PASS   the session wrote
                                                            nothing into the tree
```

The Bucket-A sketch reproduces byte-identically from the committed
`recoveries.json`. The emitted record's `submitted_at` will not: it is the
instant the record was filed, and it is a measurement rather than a constant.

The full `programs/tests` suite was NOT run — standing measured-load
constraint. The four suites above are the ones that read the file this branch
changes.
