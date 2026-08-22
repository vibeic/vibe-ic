# Three findings, one missing mechanism — and the third one was not what it said it was

*(Four by the end. The fourth was measured on this lane's own working tree, by
being on the receiving end of it, and is at the bottom.)*

Lane `jcapsha`, 2026-08-22. Branch **`jcapsha/sha256-capture`**, cut from
`origin/main` @ `81cd5321b` (plugin **v1.11.68**). Version-less; nothing pushed
to `main`.

Input: the pad-site lane's report and its branch `jpadsite/pad-site`
@ `b95dd8a9f` (PR #1765, OPEN, version-less), plus its evidence tree.

## What this lane changed about its own input

The brief handed down three findings. Two of them survived converging on them
unchanged. **The third did not, and the correction matters more than the
capture.**

F3 arrived as *a config variable that the tool ignores* — "proven inert by four
separate OpenROAD processes: neither orientation nor extents depend on it, at
any value." That measurement is correct and it reproduces. The variable is
still not inert.

The lane that made it swept four values of ONE flag while holding the other at
the identity rotation, and recorded a second observation in its own notes,
marked *"SEPARATE OpenROAD oddity, observed and NOT chased"*: a pad on a
horizontal side tracked the flag named for the vertical axis. Those are not two
observations. A two-by-two varying both flags, one process per cell, says:

    ROTH  ROTV | IO_SOUTH  IO_NORTH | IO_WEST  IO_EAST
    -----------+--------------------+------------------
    R0    R0   | R0        MX       | MXR90    R90
    R0    R90  | R90       MYR90    | MXR90    R90
    R90   R0   | R0        MX       | MX       R180
    R90   R90  | R90       MYR90    | MX       R180

The horizontal rows follow the flag named for the vertical axis. The vertical
rows follow the flag named for the horizontal one. **Each flag has a real,
reproducible effect. Neither is ignored. Each acts on the axis the other one
names.**

The positive control is the part that makes it a measurement rather than a
reading of orientations. The same command takes a site per axis, so the same
question can be asked with two DISTINCT sites and no orientation reasoning at
all — the row report simply names which site landed in which row:

    IO_NORTH  site=SITE_FED_TO_VERTICAL_FLAG
    IO_EAST   site=SITE_FED_TO_HORIZONTAL_FLAG

Same crossing, same direction, a different pair of flags.

That is why F3 moves to **Bucket T**, and it is why the ruling made on it is
better justified than when it was made — not "the knob does nothing" but "the
knob rotates the pair of sides you did not name."

`evidence/rotation_axis/`.

## The ladder, applied in order, with where each one stopped

### F1 — the step read the wrong PDK view → **Bucket A**

**Not T, and this is measured, not assumed.** The tool implements the site
creation. The upstream flow declares the variable that drives it and consumes
it before its own lookups. The distribution declares the site, with its size,
in the view that variable points at. Every layer below us did its job. Ours is
the only one that did not read it, so there is nothing in a fork to fix.

**A, and here is the input and the decision.** The brief asks for the exact
input a program would see and the exact decision it cannot make from it.

    INPUT      the upstream flow's declared variable set, extracted by a regex
               from the upstream config module — either live under a supplied
               distribution root, or from a recorded snapshot carrying the
               content hash of the file it was read from — and our module's
               own declared contract.
    DECISION   a set difference, and a classification completeness check in
               both directions. There is no judgement in it.
    CANNOT     whether a re-implementation exists that nobody registered. The
               only evidence that a piece of our code mirrors upstream is the
               intent of whoever wrote it. That is a reader's call, the program
               does not make it, and the docstring says so where a reader meets
               it rather than leaving the scope to be inferred from a pass.

Note what the *cannot* is NOT. It is not "whether the omission mattered" —
that is decided the moment the name is in no class. The omission that cost a
whole verdict had never been written down anywhere, on either side: our
artefact never listed what we left out, and upstream has no idea anyone is
mirroring it. That gap is entirely mechanical to close.

### F2 — the extent measured from the oriented footprint → **Bucket A**

**Not T.** Upstream's script measures a cell in exactly two places — the fit
sum and the along-the-row step — and both read the master's WIDTH, on all four
sides. Read line by line in the pinned image rather than counted, because a
raw count of `getHeight` in that file is four and would read as a
contradiction:

    63-67  the SITE's own width and height, and the corner site's. Not a cell.
    99-100 the master's width AND height are both computed...
    103    ...and only the width is summed: `incr sum_of_cell_widths $width`
    162-163 the master's width AND height are both computed again...
    169    ...and only the width steps the position along the row

So the master's height is computed at BOTH measurement sites and used at
NEITHER — a dead local, twice, sitting beside the value that is used. That is
worth naming, because it is the shape that makes this particular divergence
easy to introduce and invisible afterwards: the wrong dimension is already in
scope, already named, and already correct-looking.

(Upstream does use a height in the side arithmetic in exactly one place — the
CORNER SITE's, when stepping a vertical side, because a corner site is not
always square. That is a different quantity from the pad master's height and
it is used correctly.)

Upstream is right and ours diverged.

    INPUT      the register entry naming our module, the upstream file, the
               anchor STRINGS the computation is recognised by, and the pin
               test.
    DECISION   does a pin test exist and does it define the function it names;
               does each upstream anchor still occur in the upstream file.
    CANNOT     whether our formula equals upstream's semantically. Nothing
               short of running both can, which is exactly what the pin test
               is for. The program checks the pin EXISTS and never that it is
               a good test, and says so.

**F1 and F2 are the same missing mechanism**, which is the distillation this
lane exists to produce. One is an upstream INPUT that went unread; the other is
an upstream COMPUTATION that diverged. Both are ways a re-implementation drifts
from the thing it re-implements, and in both the drift produced no failure of
its own — it surfaced much later as a refusal about something else, on a brief
that was not about it. They ship as one program with two entry kinds.

### F3 — the crossed rotation flag → **Bucket T** *and* **Bucket A**, and here is which half is which

**The T half.** The root cause is the tool's own argument routing. A
plugin-side rule cannot put a rotation on the axis the caller named; it can
only decline to ask. That is not papering over — but it is also not a fix, and
the fix belongs in the fork. Tool: OpenROAD. Emitted as a forked-tool backlog
with the measured behaviour, the positive control, and a concrete enhancement
that covers BOTH flag pairs, since resolving one and not the other would leave
the command self-contradictory.

Stated honestly, and in the record: this measurement establishes that the flags
act on the opposite axis from the one they name. It does **not** establish
which side of the swap the tool's authors intended — the naming may follow an
unstated convention where the word describes the orientation a placed cell
takes rather than the axis of the row it sits in. The tool's own help prints
the flag names and no axis semantics. The fix is the same either way: exchange
them, or state the convention where a caller reads it, because the consumer
that ships with the tool documents the opposite.

**The A half.** The flow-owner's ruling — proceed and disclose at the value
indistinguishable from never having set it, refuse NOT DETERMINED when the
value is declared — is ours, and it is right whether the cause is inertness or
crossing. Generalised as the brief asks, the rule is not about that variable:
*a knob an author can set that changes nothing is a lie the flow tells.*

**It is Bucket A and it did not ship tonight, and the reason is not that it
needs judgement.** The input is fully named — the step's declared contract,
two runs differing in one variable, and the observable each produces — and the
decision is "did the observable move", which is a comparison. What is missing
is the SUBJECT: on this tree no step carries an honoured-versus-not-honoured
classification at all, and the ruling that creates the first one is in an open,
unlanded branch. A guard shipped tonight would fire on the tree it shipped on,
which the brief calls a bug and not a guard; a guard narrowed until it stopped
firing would no longer ask the question. Both are refused. The record carries
the sequence: land the ruling, add the classification to the register this
bundle ships, then wire the check to drive the two runs and compare.

The one thing that must not happen is the classification being written as a
claim nobody measured — which is the same defect one layer up.

## Before writing a new program: the existing ones, checked

The brief warns that in an earlier sweep about 63% of "extractable rules" were
already implemented and the skill was merely prose over them. Grepped first,
and two shipped gates sit close enough to have to be ruled out by reading them
rather than by their names:

    gate_discloses_denominator_check   a PASS must say HOW MUCH it looked at
    gate_zero_denominator_refuses      a gate that read NOTHING must not exit 0

**Both pass the refusal this lane is about, and both are right to.** It named a
count of the files it opened, and the count was not zero. A cardinality is
exactly what those two gates require and exactly what cannot distinguish "not
found" from "not looked for" — the missing view is, by definition, the one the
count does not include. So the rule is not a third denominator gate. It is the
one question a denominator cannot answer: *was the search space the whole of
the declared contract?* — and that is answerable only against the upstream that
declares it.

Also read and ruled out: an engine-capability parity gate (two binaries must
offer the same commands — a different question), an IP-catalogue upstream audit
(manifests against remote repositories over the network), a vendored-source
attribution gate, and the reference-flow boundary module. No register of our
re-implementations against their upstreams existed.

    measured population: 13 modules carry a `*_NOT_FOUND` refusal, 15 distinct
    codes. The class is small and the variance in what those refusals disclose
    is real, which is why the rule is anchored to the upstream contract rather
    than to the wording of a message.

## What shipped

    programs/upstream_contract_parity.json         the register
    programs/upstream_contract_parity_check.py     the check
    programs/tests/test_upstream_contract_parity.py  22 tests
    benchmark/CAPTURE_ROUTING.json                 +2 step entries

The check enforces ONE property: **no name inside a registered entry is
unaccounted for.** Every variable the upstream declaration carries is in
exactly one recorded class — implemented, declared-unperformed, omitted with a
reason, or a known gap with a reference. It cross-checks every `implemented`
name against our own module source, so the register cannot claim an
implementation the code does not contain. It refuses a known gap with no
reference, and it refuses a known gap the module NOW IMPLEMENTS, so a closed
gap cannot linger in the count of what is still wrong — a register that drifts
that way drifts toward looking worse than it is until nobody believes it.

Given a distribution root it re-measures: a name upstream has gained, a name
upstream has dropped, a content hash that no longer matches, an anchor that no
longer occurs. An unreadable register, an entry with no upstream names, or an
unreachable distribution is **NOT DETERMINED, never a pass**.

On this tree:

    pad_ring.upstream_pad_variables: upstream_names=20, implemented=8,
        declared_unperformed=3, omitted_by_design=8, known_gap=1
    pad_ring.along_the_row_extent:   anchors=2, pin=known_gap
    PASS: 2 registered re-implementation(s)

The denominator is printed at every verdict, including the failing ones.

**The 11-of-20 count was re-derived here, not transcribed.** Extracting
upstream's declaration independently gives 20; our contract plus our recorded
unperformed list names 11 of them; the 9 remaining are 8 view lists and
bond-pad dimensions plus the one that cost a verdict. That is the pad-site
lane's own corrected figure, reached by a second instrument.

**Two known gaps, both referencing the same open PR, and that is the honest
state of `main`** — the fix for both is unlanded. `rc 0` here means every name
is ACCOUNTED FOR, not that everything is implemented. The distinction is the
whole point.

**One finding the register surfaced that nobody had written down.** Two
bond-pad dimension variables belong to the same operation the module already
marks as not performed, and they are not in that list. Recorded as an
inconsistency in our own declaration rather than smoothed into a clean
omission. Not patched here: that file is the subject of an open PR and this
lane does not touch it.

### The red, shown

The guard's own predicates were mutated one at a time, each run on a cleared
`__pycache__`, each restored by REVERSE EDIT and never by `git checkout --`,
with the file verified byte-identical at the end:

    BASELINE  rc=0  22 passed
    12 mutations, 12 RED, 0 survived
    RESTORED  rc=0  22 passed

Every one of the twelve is a predicate a reader would want to believe: the
unaccounted-name difference, the reverse difference, the module cross-check in
both directions, the reference and reason requirements, the double
classification, the empty-register refusal, the NOT-DETERMINED path, the
anchor check, the content-hash check, and the pin-test existence check. A
suite that only ever observes red cannot tell a working detector from one that
refuses everything, so each test also asserts the restored green.

`evidence/mutation_sweep.txt`, `evidence/mutation_sweep.py`.

### Corpus sweep — the guard runs clean on the tree it ships on

    same verdict from 4 unrelated working directories       rc 0, identical text
    against the pristine origin/main plugin (no register)   rc 2 NOT DETERMINED
    against the live distribution, pinned image             rc 0
    against an older image                                  rc 0 (same upstream)
    against the image tagged latest                         rc 0 (same upstream)
    against a root with no distribution under it            rc 2 NOT DETERMINED

The two `rc 0` results across three images are a TRUE NEGATIVE, not a silent
detector: the upstream file is byte-identical in all three, and the freshness
arm is separately proven to fire by two tests that the mutation sweep kills.

`gate_is_wired_check` was run because a new gate nothing invokes produces no
verdict. It FAILS on this branch — and it fails identically on pristine
`origin/main`: the same three gates, `unwired: 61` against a baseline of 59, on
both sides. Mine adds a gate (624 → 625) and adds no unwired one, because it is
routed. **The baseline was not written**, on this or any gate, including where
the tool suggested it.

## A fourth finding, not in the brief, measured on this lane's own tree

The host-independence gate was run because a new gate belongs under it. It
destroyed this lane's work twice before it was identified — two edits to
tracked evidence files reverted between one command and the next, with nothing
said.

`gate_host_independence_check._repair_checkout` restores any tracked file that
was clean before a drive and dirty after, and its docstring states the
attribution as a proof:

    the difference was made by the child this loop just ran, so
    `git checkout -- <path>` undoes that and provably nothing else

Clean-before and dirty-after identifies a TIME WINDOW, not a writer, and
`git checkout --` is not an undo of one write — it makes the file equal the
committed state, taking every uncommitted change with it.

**The live positive control, while the gate was still running:**

    10:00:31  one line appended to a tracked file
    10:00:57  gone — reverted, silently, unrecoverably

Twenty-six seconds. Nothing on the editing side: no message, no prompt, no
record. It was not recoverable, because being uncommitted is precisely the
condition the rule selects for.

**And the destroyed edit is the smaller half.** The run's own report, after it
finished, names the file:

    [GATE_CORRUPTED_CHECKOUT] no retired pytest plugin request
        this gate left the WORKING CHECKOUT modified while being driven ...
        Restored: docs/capture/.../rotation_axis/hv.tcl

The misattribution MANUFACTURED A FINDING AGAINST AN INNOCENT GATE. The gate
named there wrote nothing; this lane's editor did, in the window while that
gate happened to be running. A maintainer reading that report would go hunting
for a write that does not exist. Lost work is at least visible to whoever lost
it — a false accusation is delivered to somebody with no way to tell it from
the real ones beside it in the same list.

That also bounds what this run's verdict is worth: it reported `[FAIL] 17 of 81
... 6 GATE_CORRUPTED_CHECKOUT, 11 HOST_DEPENDENT_VERDICT`, and exactly one of
those six is this editor. The other sixteen are not judged here and nothing
above claims anything about them.

**It is the same shape as F1**, which is why it belongs in this bundle rather
than in a note. A sentence somebody wrote down stood in for a measurement; it
was careful, well-reasoned prose, and the care is what kept it unexamined. F1's
root cause was a module header asserting what an upstream tool would do, and
the assertion kept a refusal firing for the life of the step. The word doing
the damage here is *provably*.

The gate's boundary is drawn deliberately — its own docstring says an
over-eager repair "would destroy a maintainer's work in order to tidy up after
a gate", which is exactly the right concern. The rule simply does not deliver
it. Note also that this does NOT reproduce on a quiet tree: it needs a second
writer, which is the normal condition on a fleet where several agents share one
repository and each is told to work in a worktree of it.

Captured as Bucket A with three deterministic fixes named, and NOT patched
here: the gate is shared, an instance was executing, and a change to a restore
path needs its own acceptance run rather than a same-night edit inside a brief
about something else. `evidence/concurrent_repair/`.

## What was NOT done, and why

1. **The plugin version — not bumped.** The brief forbids it; the lander
   assigns it.
2. **Nothing pushed to `main`.** Branch only.
3. **The pad-ring module — not touched.** Its fix is an open PR. Editing it
   from here would create a conflict and would take credit for a lane that
   already did the work.
4. **The loud-degradation guard — not shipped.** Reasoned above at full
   length: its subject does not exist on this tree yet. Bucket A, sketched,
   with the ordering it needs.
5. **The full `programs/tests` suite — not run.** Standing measured load
   constraint. `test_upstream_contract_parity.py` was run, with its own
   `--basetemp`, and the suite's write guard reports the session wrote nothing
   `git status` would show.
6. **The whole-repo host-independence gate RAN, and its verdict is not clean
   data.** It reported `[FAIL] 17 of 81`, and one of those 17 is this lane's
   own editor rather than a gate — see the fourth finding. It named no
   host-dependence in the guard this bundle ships. The property that concerns
   this change is measured directly and independently in the cwd sweep above:
   four unrelated directories, identical verdict, identical text.
   The remaining 16 findings are pre-existing to this branch and are not
   adjudicated here.

## Evidence

    evidence/rotation_axis/MEASURED.md          the crossing, the 2x2, the
                                                positive control at a second
                                                flag pair, and what it does
                                                NOT establish
    evidence/rotation_axis/HV_MEASURED_raw.txt  four separate processes, raw

Both probes WRITE the DEF they read, so this bundle tracks no tool output and
the reproduction needs only the two `.tcl` files and the image. Both were
re-run from the committed copies after that change and reproduce the captured
measurement byte for byte.
    evidence/rotation_axis/hv.tcl               the 2x2 probe
    evidence/rotation_axis/axis.tcl             the positive control
    evidence/rotation_axis/axis_control.txt     its complete row report, all
                                                eight rows, not a grep of four
    evidence/mutation_sweep.txt                 12 of 12 killed, restored green
    evidence/mutation_sweep.py                  the sweep, reverse-edit restore
    recoveries.json                             4 records: 3 A, 1 T
    candidates/                                 what enhancement_emit produced

Emitted with:

    python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py \
        --records docs/capture/2026-08-22-jcapsha/recoveries.json \
        --out-dir docs/capture/2026-08-22-jcapsha/candidates/

Accepted with no refusal and no unrouted record. The forked-tool backlog it
wrote passes `backlog_sanitize_check` at rc 0.

## For whoever reads this next

The pad-site lane closed its report with a warning: a refusal that names a
missing input, and explains convincingly why the input is missing, can still be
ours — because the explanation is a claim somebody wrote down, not a
measurement, and nothing in the flow re-checks it.

This lane is the same warning one level up. F3 arrived as a finished finding
with four processes behind it, and the number of processes was never the
problem — the problem was that every one of them varied the same single flag.
**A sweep that moves one input cannot tell you that the other input is the one
that moves your output.** The observation that would have caught it was
already written down, in the same notes, marked as an oddity for later.

The cheapest check, in the order that found it: when a sweep concludes that
something has NO effect, ask what the other arguments were doing while it ran —
and if any of them was held constant, vary it once before believing the
conclusion.
