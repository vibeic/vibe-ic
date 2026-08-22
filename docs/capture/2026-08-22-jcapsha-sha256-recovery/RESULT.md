# CONVERGE → CAPTURE → DISTILL on the pad-site recovery

Agent `jcapsha`, 2026-08-22. Branch **`jcapsha/capture-sha256-recovery`**,
cut from `origin/main` @ `81cd5321b`, rebased onto `a4caccefe` (v1.11.69) when
main moved under the lane, and pushed at every step. No version bump; nothing
pushed to `main`.

## Answer first

Three findings went up the ladder. Two stopped at **A** and shipped as programs
with their reds shown. The third stopped at **T** — and **the premise the brief
handed me for it did not survive being measured.**

| | finding | bucket | where it stopped and why |
|---|---|---|---|
| F1 | the step read the wrong PDK view | **A** | not T: the distribution, the flow and the tool are all correct — measured, all three. Ours was the only layer that did not read the view. |
| F2 | the extent came from the oriented footprint | **A** | not T: upstream's arithmetic is right; the drift was entirely ours. |
| F3 | a config variable the tool "ignores" | **T** | the tool does **not** ignore it. It is a live knob wired to the other side-pair, across a vocabulary collision inside the forked toolchain. |

A fourth record, **C**, carries the consequence of F3 for a refusal that is
already landed. A **fifth**, **T**, is a second forked-tool finding of the same
class, found by *writing* one of the pins rather than by running anything — see
"What the pins found" below.

Nothing went to **D**. Neither program reads a pad or a PDK literal, and the
tool finding is about two layers disagreeing on a word.

---

## F3 — the finding that moved, and the measurement that moved it

The brief said: *"`PAD_ROTATION_VERTICAL` was proven inert by four separate
OpenROAD processes… the tool ignoring the variable is the tool's behaviour, but
the fix ruled tonight is ours. Say which half is which."*

I was told to think hardest about this one. Doing so refuted it.

**The argument is not dropped at any interface.** The flow script passes
`-rotation_vertical`, and the tool's own command threads it into the row
builder — dumped from the running tool, not read from documentation.

**Holding one axis and sweeping the other.** With the horizontal option held at
its default, sweeping the vertical option leaves the EAST/WEST rows still and
moves the SOUTH/NORTH rows. Swap which one is held and the complement happens:

    ROTV (H held)   IO_SOUTH  IO_NORTH   IO_EAST  IO_WEST
    R0              R0        MX         R90      MXR90
    R90             R90       MYR90      R90      MXR90
    R180            R180      MY         R90      MXR90
    MX              MX        R0         R90      MXR90

    ROTH (V held)   IO_SOUTH  IO_NORTH   IO_EAST   IO_WEST
    R0              R0        MX         R90       MXR90
    R90             R0        MX         R180      MX
    R180            R0        MX         R270      MYR90
    MX              R0        MX         MXR90     R90

**One call, two distinguishable sites, and the geometry to settle it.** So that
the row names are not taken on trust:

    ROW IO_SOUTH  bbox=(710000 0)       (7290000 710000)   site=SITE_V  orient=R180
    ROW IO_NORTH  bbox=(710000 7290000) (7290000 8000000)  site=SITE_V  orient=MY
    ROW IO_EAST   bbox=(7290000 710000) (8000000 7290000)  site=SITE_H  orient=MXR90
    ROW IO_WEST   bbox=(0 710000)       (710000 7290000)   site=SITE_H  orient=R90

Both the site and the rotation route the same way, in one command:
`-*_horizontal` → EAST/WEST, `-*_vertical` → SOUTH/NORTH. The tool is
internally consistent: it names a row by the axis **perpendicular** to the row's
run. The flow script that passes the variables through names rows by the axis
they **run along**, eleven lines below where it passes them.

So the variable is live and it steers the side-pair opposite to the one its own
layer's vocabulary assigns it.

**Why four separate processes did not see it.** They removed the confound they
were run to remove — a row left over from an earlier pass. They could not
remove a wiring assumption, because every one of the four holds the *other*
rotation at the same value while reading the sides that other rotation
controls. The data is correct. The inference is not.

**Which half is which**, answered as asked:

* **The tool's half** is that two option families named for axes govern the
  side-pairs the caller's own vocabulary assigns to the other one, with nothing
  on either side of the boundary declaring which convention is in force and no
  error raised. That is inside the forked toolchain; a plugin-side rule could
  only paper over it. **Bucket T.**
* **Our half** is a refusal that is *already landed on main* and prints, as its
  reason, that the placer does not read the variable. The refusal may still be
  the right behaviour — a knob that crosses to the other side-pair is arguably
  worse than an inert one — but the reason beside it is the part a reader acts
  on, and it is false. **Bucket C**, because the choice between "keep the
  refusal and restate the reason" and "drop it" is a ruling about a shipped
  verdict, it was escalated once and ruled on the premise now refuted, and
  taking it unilaterally inside a capture brief is the scope creep the brief's
  own rules forbid.

Evidence and the four scripts that reproduce all of it:
`evidence/rotation_axis_vocabulary.md`, `evidence/probe_row.tcl`,
`probe_row2.tcl`, `probe_site.tcl`, `probe_bbox.tcl`, `probe.def`.
Image `ghcr.io/vibeic/vibeic-eda:0.3.25` (`b9124fe1778a`), OpenROAD
`26Q3-1655-g2b33daff56`.

---

## F1 — shipped: `absence_verdict_names_its_search_space_check`

**Why not T.** All three upstream layers behave correctly, measured rather than
assumed: the distribution declares the site with its size in its tech view, the
flow declares the variable that carries it and consumes it before its own
lookups, and the tool implements the call that creates it — I drove that call
myself in every probe above. A fork change here would have been a fix aimed at
working code.

**Why A, with the exact input and the exact undecidable named.** The input is
the refusal call site. The decision "does this name where it looked" is
syntactic and needs no judgement. The decision it **cannot** make from that
input is whether the address is **complete**, because completeness is a
property of the distribution and not of our source.

**AND THAT MATTERS MORE THAN IT LOOKS, SO IT IS STATED FLAT: this gate would
NOT have caught F1.** The pre-fix refusal *did* name a locus — it said
`0 site(s) from 1 LEF(s)`. It named one view and counted inside it, and the
count is what made it read as thorough. What this gate closes is the reachable
half: a refusal that names **nowhere at all**. The other half needs the
artefact to record which view each resolved value came from, which the landed
resolver now does.

**The predicate was narrowed four times, by measurement, never to clear a red.**
An environment read is not a refusal (that flagged a test hook whose whole job
is to force the honest-degrade path); `tests/` is excluded (a fixture refusal is
deliberately minimal, and the rule would have flagged the tests that prove it);
a locus bound one line above the call counts; a refusal nested inside the report
that carries the paths counts. Each removed a *measured* false positive, and
each is pinned by a test named for the shape it came from.

**The red, and the two real ones.** Against those two files as they stand on
`main`: 7 absence verdicts, 5 naming a locus, `rc 1`, naming
`_pad_ring.py:780` and `_ppa/backends/openroad.py:740`. Both are fixed here by
**adding** information — nothing relaxed:

* the pad-config refusal now names the file and the four variables it found
  empty (driven live, not inferred: *"all four side lists are empty in
  `phase3/stage3/pnr/pad_assignment.json` (PAD_SOUTH, PAD_EAST, PAD_NORTH,
  PAD_WEST) …"*);
* the per-layer wirelength note now names the character **window** it searched
  and its size. "No rows matched" and "the window I matched in was 8 characters
  long" print the same today and are different findings — the second is a bug in
  the block bounds above it.

Same two files after: 7 of 7, `rc 0`. Whole tree: **31 of 31 over 1277 files,
`rc 0`.** An absent directory and an empty population are both `rc 2` NOT
CHECKED — never a quiet pass.

---

## F2 — shipped: `upstream_mirror_is_pinned_check`, and it refuted its own brief

**Why not T.** Upstream's per-side arithmetic is correct. The drift was ours.

**Why A.** The input is the module's declaration and the pin file; the decision
— does the named test exist and does it read upstream — is syntactic.

**The gap was real and open on `main`.** Our half of the invariant *was* pinned
(`test_a_vertical_side_sums_the_master_width_not_its_height`). Zero tests read
the upstream artefact. Run against `main`, the gate answers `rc 2` NOT CHECKED
and lists three modules whose own prose claims a borrowing while declaring
nothing — which is the state it exists to end, printed rather than assumed.

**THE PIN FOUND THE DOCUMENTED EVIDENCE WAS WRONG, WHICH IS THE POINT OF IT.**
The mirror was documented with *"there is no `getHeight` in its side arithmetic
at all."* Run against the real file, that **failed**: upstream reads the
master's height **twice** inside the side loop, at both places it reads the
width.

    set width  [expr [[$inst getMaster] getWidth] / $units]
    set height [expr [[$inst getMaster] getHeight] / $units]
    puts "$master_name: $width $height"
    incr sum_of_cell_widths $width

`$height` is read, **printed**, and never used in arithmetic. The conclusion the
mirror rests on is sound; the sentence it was written with is not — and an
unused local named `height` one line under the used `width` is exactly the shape
that invited the confusion. The pin asserts what is true: the fit sum
accumulates the width, the along-the-row step advances by the width, and the pad
master's height reaches no arithmetic at all.

**Three states, all run:**

    real upstream, in the image ................ 3 passed
    MUTATED upstream, `incr … $height` ......... 1 failed   <- the red
    this host, no upstream on it ............... 1 passed, 2 skipped BY NAME,
                                                 the reason naming the missing input

**The gate found a defect in its own first pin**, and the fix went into the
*predicate*, not the pin: a pin that takes the path **from** the declaration
rather than repeating the literal is the better pin — one copy of the fact, so
the two cannot drift the way the mirror did. Accepting that form is a
correction, not a relaxation, and a pin mentioning neither the path nor the
declaration still fails, with a test pinning that.

---

## What the pins found — and the gap I said was follow-on is now closed

The first version of this report left the mirror gate at a population of ONE,
with two named candidates and a note calling them follow-on. That note was an
accurate disclosure and a poor stopping point, so both are now declared and
pinned. **Declared mirrors: 3. Undeclared candidates: 0.**

    _pad_ring.py            -> the per-side pad arithmetic
    digital_hardmacro_gen.py-> the LEF-write sequence and its three defaults
    die_finishing_gen.py    -> the seal-ring generator contract

All three pins pass against the real upstream in the image (**11 passed**), and
each goes RED under a mutation of the thing it pins — an upstream default
flipped, an upstream index transposed, an upstream accumulator switched to the
other dimension. On a host with neither PDK nor upstream they skip by name.

**AND WRITING THE THIRD PIN FOUND A SECOND TOOL DEFECT.** The seal-ring step
dispatches on PDK name into two branches. The die rectangle is declared as four
corner coordinates — `"x0 y0 x1 y1"` — so index 2 is an x and index 3 a y. The
two branches pass them in opposite orders:

    generic branch   --die-width  DIE_AREA[2]      # x1   correct
                     --die-height DIE_AREA[3]      # y1   correct
    other branch     width=       DIE_AREA[3]      # y1
                     height=      DIE_AREA[2]      # x1

This is not a naming ambiguity that could be argued either way. The receiving
generator documents its own parameters — *"width: Width (X-Axis)"*,
*"height: Heigth (Y-Axis)"* — so one branch is simply wrong. It has survived
because the script's own usage example, and every fixture anyone would reach
for, is a **square** die, on which the transposition is invisible. Filed as the
fifth record; **not** patched here, and the pin is deliberately scoped to the
branch this repo drives so that it neither blesses the transposition nor
reddens over a defect in a path we do not use.
`evidence/sealring_width_height_transposed.md`.

That is the same class as F3: a dimension crossed at a boundary between two
layers, invisible under the symmetric case everybody tests with, silent when
wrong.

## A verification of my own that was wrong, and how

**I reported three emitted backlog YAMLs as passing `backlog_sanitize_check`.
They were failing.** The command was

    python3 backlog_sanitize_check.py --file "$f" | tail -4; echo "RC=$?"

and `$?` there is `tail`'s exit status, which is 0 whatever the checker said.
Re-run so the checker's own status is what is read, all three returned rc 1:
`component` must match `skill:<name>` | `program:<name>` | `mcp:<tool>` |
`flow:<step>`, and mine were free text. Now corrected at the source and
re-verified with the checker's own exit status — **all three rc 0**.

Two things worth keeping from it. The first is that the earlier commit message
carries the wrong claim; it is corrected here rather than quietly fixed,
because a commit message is not editable and a reader will meet it first. The
second is that `flow:<step>` cannot name most steps in this flow: the pattern
is `[\w_-]+`, and this repo's step ids carry a dot (`15.5ic`, `26.5ic`). I did
NOT widen that regex — widening a pattern to clear my own red is the one move
that is never available — and used the accurate `program:` form instead. The
vocabulary gap is an observation, not a change.

## A pre-existing failure I ran into and did not cause

`test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged` fails
on this host with *"magic did not complete: watchdog reported launch_error
after 0s"*. Measured, not assumed: it fails identically with my declaration
REMOVED (reverse edit, re-applied afterwards, diff back to +21 lines), and the
whole file is **24 passed** inside the image. So it is host-dependence, green
where the flow actually runs. Worth a note only because of what it does on the
host: it FAILS rather than SKIPPING, which is the opposite of the convention
the rest of this lane's tests follow — a question that could not be put should
say so by name.

## Grep first — what was already there

Checked before writing either program, per the brief:

* `gate_discloses_denominator_check` — a PASS must disclose how much it
  examined. **The sibling, not the same question**: F1 asks it of a *refusal*,
  and the measured defect *satisfies* the denominator rule while being wrong.
* `_shape_refusal` — a refusal must name **what arrived**. Adjacent and
  distinct: that is present-but-wrong-shape; F1 is where-did-you-look.
* `silent_decline_audit` — a remedy that declines must say so. About
  *declining*, not about *absence*.
* `digital_hardmacro_gen` already writes `"mirrors": "<upstream path>"` into an
  artefact — a real precedent for F2's declaration, and the reason the field is
  named `mirrors`.

So neither program is a near-duplicate, and both cite the neighbours they sit
next to.

---

## Limits, stated

* **The F1 gate would not have caught F1** (above). It closes the reachable
  half.
* **The F2 gate does not decide which modules ought to declare a mirror.** It
  counts the candidates and prints them every run, PASS or FAIL. That count is
  now **0** — the two it named have been declared and pinned — but the gate
  still cannot decide the question for a module added tomorrow, and it does not
  fail on a candidate: turning a prose scan into a blocking predicate is how a
  checker earns a reputation for firing on correct code.
* **The F3 tool finding is measured on ROWS.** The prior lane measured placed
  **pads**; the two agree where they overlap (`W=MXR90`, `E=R90` at the
  horizontal option's default). I did not re-measure placed pads.
* **`main` carries the pad-site work up to `495350370` only.** Two later
  commits on that lane's branch — a precedence test and two header-count tests —
  are **not** ancestors of `main`. Anyone reconciling the two should check that
  rather than assume the branch landed whole.

## What I did not do

No version bump. Nothing pushed to `main`. No baseline written and
`--write-baseline` never used. No assertion relaxed, no regex widened to clear
a red, no test deleted. No GDS touched, no pin moved, no rule deck relaxed. The
full `programs/tests` suite was NOT run — standing measured load constraint;
host load was 42 at entry. The landed rc=2 refusal and the ruling behind it were
left exactly as they are, and the case for re-reading them is filed rather than
taken.

**RETRACTED, AND REPLACED BY WHAT WAS ACTUALLY WRONG.** An earlier version of
this report said the `pre-push` hook still runs two gates as
`--tree benchmark-data`, that the tree left this repository at v1.10.56, and
that a flow owner should look at the wiring. **That is false for `main`, and I
published it after measuring a stale artefact.** Measured properly:

    the hook that RAN on my pushes ....... 9 gates, two of them --tree benchmark-data
    the hook TRACKED at current main ..... 7 gates, ZERO occurrences of benchmark-data

The repository had already removed those two gates when the corpus moved. My
"finding" was the absence of a fix that was in fact present.

**WHAT WAS ACTUALLY WRONG IS THE HOOK RESOLUTION, and it is general.**
`core.hooksPath` is set to the SHARED `.git/hooks`, and that directory's
`pre-push` is a symlink into the **primary checkout's working tree**:

    core.hooksPath = /home/reyerchu/vibe-ic/.git/hooks
    .git/hooks/pre-push -> /home/reyerchu/vibe-ic/tools/git-hooks/pre-push
    that checkout is on a branch at 886bb4a14 — before the corpus move

So a push from ANY worktree runs whatever version of the hook the primary
checkout happens to have checked out, not the version its own commits are
based on. The gate set is a property of somebody else's working tree. Here it
meant two retired gates ran against my push; it could equally mean a gate that
`main` ADDED does not run at all, which is the direction that actually costs
something.

**AND MY WORKAROUND WAS COMPENSATING FOR THAT, NOT FOR A REPO GAP.** I pushed
with `VIBE_IC_BENCHMARK_DATA` pointed at a local clone of the corpus so the
retired gate could run for real rather than be bypassed. That was the right
move in the moment — it never used `--no-verify` — but the reason I gave for
needing it was wrong.

**RE-VERIFIED against the gate set my commits are actually supposed to face.**
Pushed through `-c core.hooksPath=<this worktree>/tools/git-hooks` to a
throwaway ref, with **no** corpus environment variable set: all seven gates
passed, the push succeeded, and the throwaway ref was deleted. So the branch
satisfies current `main`'s real gates unaided.

I did NOT change `core.hooksPath`. It lives in the shared config, so setting it
would change hook resolution for every other worktree and every other agent
pushing from this repository — a fleet-wide change, made from inside one lane,
to fix a thing that is not this brief's. The correct invocation is recorded
above for anyone who needs it, and it is `-c core.hooksPath=...`, never
`--no-verify`.

## Files

    docs/capture/2026-08-22-jcapsha-sha256-recovery/
      recoveries.json                      4 records
      candidates/                          enhancement_emit output
      evidence/rotation_axis_vocabulary.md the F3 measurement, in full
      evidence/probe_*.tcl, probe.def      the four scripts that reproduce it
    programs/absence_verdict_names_its_search_space_check.py   + 16 tests
    programs/upstream_mirror_is_pinned_check.py                + 11 tests
    programs/tests/test_upstream_mirror_pad_cfg.py             pin 1
    programs/tests/test_upstream_mirror_magic_lef.py           pin 2
    programs/tests/test_upstream_mirror_klayout_sealring.py    pin 3
    programs/digital_hardmacro_gen.py, die_finishing_gen.py    UPSTREAM_MIRROR
    programs/_pad_ring.py                  UPSTREAM_MIRROR + one enriched refusal
    programs/_ppa/backends/openroad.py     one enriched note
    benchmark/CAPTURE_ROUTING.json         three new steps

Ran, on the final tree, with each verdict read from the program's OWN exit
status and never from a pipe:

    both new gates ................................................. rc 0
    the 8 suites incl. all three pins, pad-ring, emit, sanitize ..... 203 passed, 15 skipped
    the two newly-declared modules' own suites ..................... 100 passed, 26 skipped,
                                                                     1 pre-existing host-only
                                                                     failure (above)
    all three pins against real upstream, in the image ............. 11 passed
    each pin against a MUTATED upstream ............................ red, per mutation
    the eight `ppa` backend suites ................................. 53 passed
    the three emitted backlog YAMLs vs backlog_sanitize_check ...... rc 0, rc 0, rc 0
    the branch through current main's OWN 7-gate pre-push .......... all passed,
                                                                     no corpus env var

The full `programs/tests` suite was NOT run — standing measured load
constraint; host load was 42 at entry and ~50 at exit.
