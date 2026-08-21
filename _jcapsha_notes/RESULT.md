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
| F1 | the step read the wrong PDK view | **A** | a set difference over two enumerable variable lists |
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

* **No new guard was landed.** All three plugin-side rules would go RED on
  `origin/main` today — correctly, because the defects they guard are fixed on
  `origin/jpadsite/pad-site` and that branch has not landed. Shipping a
  correct-but-red gate would block every push on the repo. They ship as
  sketches, with the ordering dependency stated: **land `jpadsite/pad-site`
  first, then the guards.** For F2 the red/green pair is already measured
  (above) so whoever lands it does not have to re-derive it.
* **F3b's guard has no population yet.** Nothing on `main` declares a variable
  unhonoured, so a gate written to it today would run over zero subjects — and
  this repo's own doctrine (`gate_zero_denominator_refuses_check`) says a gate
  that read nothing must not exit 0. Premature, and stated as such rather than
  landed vacuous.
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
