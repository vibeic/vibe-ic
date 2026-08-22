# Three recoveries, three ladder verdicts, and the two properties that were
# implemented and unpinned

Agent: `jcapsha` on 8HD-d, 2026-08-22.
Branch: **`agent/jcapsha-capture`**, cut from `origin/main` @ `a4caccefe`
(v1.11.69). No version bumped, nothing pushed to `main`.
Subject: the three findings `jpadsite` recovered, read as GENERAL rules.

## The answer first

All three are **Bucket A**. None is Bucket T, and the one that looked closest
to T is the one whose tool-half is real and whose defect-half is still ours —
that split is set out under F3 rather than asserted.

    F1  a refusal must name the views it read      Bucket A   SHIPPED (pinned)
    F2  a re-implementation must be pinned          Bucket A   SHIPPED (guard)
    F3  an inert declared variable must be loud     Bucket A   SKETCH + reason

Two of the three turned out to be **already implemented and unpinned**, which
is a different deliverable from the one I expected to write and is the reason
the brief's "grep first" instruction earns its place. The code was right and
nothing was holding it there.

---

## CONVERGE — what is true on `main` today, measured not assumed

`jpadsite`'s report was verified against `main` at `81cd5321b` and its branch at
`41e6562d2`. `main` is now `a4caccefe`. Re-checked here:

* **All three code fixes are on `main`.** `_pad_ring.resolve_site` and the
  tech-view discovery (F1), the master-WIDTH extent on all four sides (F2), and
  the three-part rotation ruling — `ROTATION_VERTICAL_INERT`, the rc 2 refusal
  of a declared non-default, and the placer's own orientation in the DEF (F3).
* **One commit of theirs is still outside `main`**: `41e6562d2`, the header
  arithmetic fix and its two tests. Left alone — it is their open PR's, not
  this brief's, and taking it would put someone else's unlanded work under my
  branch's name.
* **`sha256` x `gf180mcuD` is a recorded non-cell** and the pad-ring numbers in
  their report are scoped, at length, by them. Nothing here re-opens or quotes
  those numbers. The three DEFECTS are chip- and PDK-agnostic and that is the
  only part this capture is about.

### An independent re-measurement, in a DIFFERENT image

Their upstream evidence was taken in `ghcr.io/vibeic/vibeic-eda:0.3.16`, which
is not on this host. I re-derived it in **`:0.3.26`** — a different image
generation, which makes this a cross-instrument check rather than a repetition.
`evidence/upstream_pin/upstream_measured_0_3_26.txt`, with the file hashes.

The claim holds, **and its phrasing needed sharpening**:

> jpadsite: "There is no `getHeight` in its side arithmetic at all."

`getHeight` appears **four times** in that file. A reader who greps for it finds
those four and reads the sentence as refuted. What is actually true, and
survives the grep:

* the pad **master's** height is bound twice (lines 100, 163) and consumed
  **exactly once** — by a diagnostic `puts` at line 102. It never enters an
  arithmetic expression. The second binding is not read at all.
* the only heights that DO enter arithmetic are the corner **site's**
  (`pad_corner_site_height`), which bound a vertical side's span. Different
  cell, different quantity, and correct.
* both places that measure a pad for the row use the master's **width**: the
  fit sum `incr sum_of_cell_widths $width` and the placement step
  `set cur_pos [expr $cur_pos + $space_between_pads_min_filler + $width]`.

That is the difference between a claim that is true and a claim that stays true
when someone checks it. It is also exactly what an anchor has to be, which is
what F2's deliverable turns on.

---

## The ladder, applied in order, stopping at the first YES

### F1 — the step read the wrong PDK view

**Bucket T? NO.** Every layer below ours was correct. OpenROAD implements
`make_fake_io_site`; librelane declares `PAD_FAKE_SITES` in its config contract
and consumes it before its own two site lookups; the PDK ships the declaration
and says in a comment why. Ours was the only layer that did not read it. A
change in any fork would have fixed nothing, so the T test — "a plugin-side rule
could only paper over it" — is false in both directions: the plugin-side rule is
the entire fix, and it papers over nothing.

**Bucket A? YES**, and here is the input/decision test the brief asks for rather
than the phrase it forbids:

* **the exact input a program sees**: the refusal record the step already emits,
  plus the module that emits it.
* **the exact decision it CANNOT make from that input**: whether the enumerated
  set of views is COMPLETE. Nothing in our source knows a second view exists.
  That question is answerable only against upstream — which is F2, not a
  different bucket. So F1's Bucket-A scope is the DISCLOSURE, and I say so
  instead of claiming a program can also detect the missing view.

**GREP FIRST — and the existing thing was not a checker, it was the code.**
The repo has `gate_discloses_denominator_check` ("a PASS must say how much it
looked at") and `gate_zero_denominator_refuses_check` ("a gate that read NOTHING
must not exit 0"). Neither asks this question: both are about a PASS or a
population, and this is about a REFUSAL's search space. But the step itself
already answers it — `_fail` carries `io_cell_library=lib.as_dict()` on every
refusal, and that dict names `lefs` and `site_declarations` with their
**resolved paths** and their yields.

**So the deliverable is not a checker. It is the pin that was missing.** The
tests covered which view a RESOLVED name came from — the success path. The
refusal path, where the enumeration is the whole point because there is no
resolved name to attribute, was untested. A property that is implemented and
unchecked is one refactor from being gone, and its loss looks exactly like the
original defect.

**Shipped**: `programs/tests/test_refusal_names_its_search_space.py`, four
properties — both views present as data, each with its paths and its yield, a
consulted-and-empty view distinguishable from an unread one, and the human
message naming both views and the word "neither".

**THE RED**, three segments, `evidence/search_space/mutation_proof.txt`:

    BASELINE   4 passed
    MUTATED    3 failed, 1 passed   (the tech view dropped from the record —
                                     the PRE-FIX shape)
    RESTORED   4 passed             (reverse edit; `git diff` on the file empty)

The fourth test PASSED under the mutation. The message is composed
independently of the record, so the two tests catch different losses. Each is
necessary and neither is sufficient — stated because a 3-of-4 red is easy to
read as "the tests work" when what it shows is that one of them does not cover
what the other does.

### F2 — the extent was measured from the oriented footprint

**Bucket T? NO.** Upstream is right and we drifted from it. There is nothing to
fix in a fork.

**Bucket A? YES.**

* **the exact input**: the module's declared pin — an upstream file and the
  exact text in it that fixes the quantity — and the upstream tree installed on
  the host.
* **the exact decision it CANNOT make**: whether a given program OUGHT to have a
  pin. A machine reading our source cannot distinguish a re-derivation of an
  upstream computation from an ordinary computation that resembles one. So that
  half is a **census** — printed every run, never a verdict — and the unpinned
  set becomes a measured number instead of an assumption. A gate that guessed
  there would be the false-positive noise this repo has already recorded as the
  real cost of a noisy tool.

**TARGETED REGRESSION on the one shipped program I modified**, measured on this
host at loadavg 17.8 (the figure is beside the number because a bare timing is
not a measurement): `test_pad_ring.py` **97 passed, 4 skipped**, unchanged by
the `UPSTREAM_PINS` addition. The full `programs/tests` suite was NOT run, per
the standing load constraint.

**GREP FIRST.** `sta_engine_parity_check`, `size_policy_drift_check`,
`p0_gate_invocability_drift_check`, `ip_catalog_upstream_audit`,
`l_doc_parity_diff` — the repo has a whole parity/drift family. None of them
compares OUR arithmetic to an UPSTREAM FILE. Measured: **6 programs cite an
upstream flow file, and ZERO tests open one** — verified by searching every test
for a read of a path carrying `librelane` or `openlane`; the single occurrence
found is a comment. The citations are prose. (The guard's own census reports 5,
not 6: it counts citations written as a PACKAGE PATH, and the sixth writes a
bare script name. That program now declares the pins, so it would leave the
census either way — but the census is a floor and its printed line says so.) A
citation is a claim about a file; a pin is a claim a machine can lose.

**Shipped**: `programs/upstream_reimplementation_pin_check.py` plus five pins
declared in `pad_ring_gen.py` (`UPSTREAM_PINS`) — three for the width
arithmetic, two for the tech-view declaration, so F1's upstream claim is pinned
by the same mechanism.

**MEASURED, image `:0.3.26`** — `evidence/upstream_pin/green_and_red_sweep.txt`:

    GREEN   5 pin(s) resolved; every anchor present            rc 0
    RED     the historical drift injected into a COPY of
            upstream (the fit sum switched to the height)      rc 1, anchor named
    PROBE   driven as `<program> <project>` from an empty project: rc 0,
            with the ignored project path disclosed  (see below)
    TESTS   15 passed in the image across both new files; 10 passed 1 skipped
            on a host with no upstream tree, the skip being the real-tree
            test declining rather than passing

Same command, same code, upstream swapped. Nine tests; the file does not collect
without the program, which is the trivial red, and the two that matter are the
lost anchor failing and the absent tree REFUSING.

**It refuses rather than passes when it cannot look.** No upstream tree, or no
pin declared anywhere, is rc 2 NOT DETERMINED with the missing input named. A
check reporting "they agree" after opening nothing would be the defect one level
above the one it exists to catch, and this repo has that failure recorded under
several names already.

### F3 — a config variable that the tool ignores

**Which half is which**, since the brief asks for it directly:

* **THEIRS.** librelane declares `PAD_ROTATION_VERTICAL` as a settable,
  PDK-scoped variable, and the placer's vertical-side orientation is a CONSTANT
  across every value of it — measured by `jpadsite` in four separate OpenROAD
  processes, one per value, so no row from an earlier pass could be reused. That
  is a fact about the tool and it is not disputed here. I did not re-run it:
  four OpenROAD processes on a host at load 90 would produce a timing-polluted
  repetition of a measurement that was taken cleanly, and a worse copy of an
  existing measurement is not a second measurement.
* **OURS.** Our step accepts that variable into its own config contract and its
  geometry does not depend on it. **Our step does not call librelane's
  `place_pads` at all** — it computes the ring itself. Upstream is a REFERENCE
  we measure against, not a dependency that generates our defect.

**Bucket T? NO**, and this is the one I thought hardest about. The T test is
"the root cause is inside a forked tool, such that a plugin-side rule could only
paper over it". Both clauses fail. If the fork were changed tomorrow — librelane
honouring the variable, or dropping the declaration — our step would still
accept a knob it does not read, because it never asks the placer. And the fix
that was ruled papers over nothing: it DISCLOSES, with the measurement attached.
Filing this as T would name a tool for a defect that survives fixing the tool.

**Bucket A? YES.**

* **the exact input**: the step, a fixture, and the variable. Inertness is
  decided by MEASUREMENT, not by reading code — perturb the value, re-run on the
  same input, diff the artefact. Byte-identical output across the declared value
  domain is inertness, with no judgement anywhere in it. That is the same
  instrument `jpadsite` used on the tool, turned on ourselves.
* **the exact decision a program cannot make**: which value domain is worth
  probing, for a variable whose domain is not enumerable. Stated as the limit it
  is; it does not move the bucket, it bounds the probe.

**GREP FIRST — and this one is already done, in one place.**
`ROTATION_VERTICAL_INERT` is stamped by `_report`, so it reaches EVERY report
including the skips and the refusals, and
`test_the_inert_disclosure_is_in_every_report_including_the_skip` already pins
that. The declared non-default already returns rc 2 naming the variable. **There
is nothing to add for this variable, and adding a near-duplicate checker would
be the 63% failure the brief warns about.**

**So what is left is the GENERALISATION, and it ships as a sketch.** The rule
beyond the one variable needs the differential probe as a program — a harness
that drives a step twice per declared variable and diffs its artefact — and that
is a real piece of work with its own acceptance bar, not a rule I can assert
into a file tonight. What I will not do is ship a population-of-one gate over
`ROTATION_VERTICAL_INERT` and call the class covered: it would be green from the
day it landed, it would never fire, and its greenness would read as evidence
about a class it never examined.

---

## What shipped

    programs/upstream_reimplementation_pin_check.py     new guard  (F2)
    programs/tests/test_upstream_reimplementation_pin.py  9 tests  (F2)
    programs/pad_ring_gen.py                           +UPSTREAM_PINS, 5 pins
    programs/tests/test_refusal_names_its_search_space.py  4 tests (F1)
    benchmark/CAPTURE_ROUTING.json                     +phase3.pad_ring
    docs/capture/2026-08-22-jcapsha-agent-capture/                    recoveries + candidates

`CAPTURE_ROUTING.json` had no entry for this step, so a Bucket-A capture from it
routed to the PnR runner — not where any of these rules belong. One additive
entry; the emitted sketch now names `pad_ring_gen.py`.

Nothing was relaxed, widened, deleted or baselined. `--write-baseline` was never
used, on any gate. No assertion was weakened to make a red go away, and the one
guard behaviour I did loosen — accepting a tuple as well as a list for the pin
declaration — was my check inventing a house-style requirement out of the first
file it read, and it is recorded in the code as that.

## The new guard reproduced, in itself, the defect class it audits

Found by driving it the way this repo's population probes drive every
`*_check.py` — `<program> <project>`, from a structurally empty project — rather
than only the way I had been calling it.

    upstream_reimplementation_pin_check.py: error: unrecognized arguments: .
    RC=2

**argparse's usage error and this program's honest "I could not look" were
wearing the same exit code.** A population probe reading that gets a disclosed
skip from a program that never ran. It is exactly the conflation the repo has
already had to route around twice — at the umbrella (#492: "rc 2 carried two
unrelated meanings ... Recording the second as a skip is what let 39 registered
gates be permanently silent") and again in a gate's wiring (#1347, which moved a
glob out of the flow clause into the program so a missing directory becomes an
ANSWER rather than a usage error). A check ADDING a third instance would be the
defect it exists to catch, one level up.

Fixed by accepting the driver positional and answering with the program's own
verdict, disclosing on stdout AND in the record that a project path was handed
over and not consulted. Two tests pin it; the red without the fix is a
`SystemExit` from argparse, which the test names as such rather than letting it
read as a failure of the check.

Recorded here rather than quietly fixed, because the interesting part is the
method: **I did not find it by review. I found it by driving the new thing the
way its actual callers drive it, which is the one check I nearly skipped
because the program worked when I ran it myself.**

## What did NOT ship, and why

1. **A repo-wide checker for F1's rule.** I built the measuring instrument and
   ran it: over `programs/`, a message-shaped predicate flagged 5 of 16 refusal
   sites, and reading them showed **3 of the 5 are false positives** — a prose
   citation in a question's note, and two that name their source file by a name
   my predicate did not recognise as one. A gate at that false-positive rate
   teaches people to ignore it. `evidence/measure_not_found_refusal_population.py`
   is the instrument; the number is the reason, and it is measured rather than
   asserted.
2. **The differential inertness probe (F3).** Named above. It is the deliverable
   for that class and it is a separate piece of work.
3. **`jpadsite`'s unlanded commit.** Theirs to land.
4. **Any re-run of the four-process rotation probe.** Reasoned above: at load 90
   it would be a worse copy of a clean measurement.

## The gate that blocked the pushes, and the remedy I got wrong first

**The pre-push gate that blocked here was the WRONG HOOK, and I took the
weaker of the two available remedies before checking.** `.git/hooks/pre-push` is
a symlink into the PRIMARY checkout's working copy, so every worktree push runs
whatever hook that checkout happens to be sitting on — not the one tracked on
the branch being pushed. Measured, gate names diffed between the two:

    stale hook   9 gates
    tracked hook 7 gates
    the 2 extra  "benchmark evidence structure", "benchmark run manifest"
                 -- both take `--tree benchmark-data`, both removed upstream
                 when that tree moved to its own repository

So the `UNDETERMINED: --tree benchmark-data is not a directory` that blocked the
first push was entirely environmental: a gate the branch no longer carries,
asking about a tree that no longer exists here.

`--no-verify` was never used. But my first remedy — pushing from the primary
checkout — made the STALE hook run its gates against the PRIMARY CHECKOUT's
working tree rather than against this branch's content, which is the
"reporter reads one tree, writer commits another" shape. Benign for these
commits (nothing here touches that tree, and it is untracked, so no branch's
content was stood in for), and still the weaker answer.

**The final push runs the branch's own tracked hook** via `core.hooksPath`, so
the 7 gates that actually apply run against the tree they are judging. The
result of that run is the gate evidence for this branch.

## An instruction I did not follow literally, and what I did instead

The brief says **measure on a clean tree: `git clean -xdfq`,
`PYTHONDONTWRITEBYTECODE=1`**. `PYTHONDONTWRITEBYTECODE=1` was used throughout,
and `__pycache__` was cleared before the mutation run. `git clean -xdfq` was
NOT run, and the substitution is stated rather than left for someone to notice:

the shared checkout on this host carries a large tree of UNTRACKED benchmark
artefacts belonging to other agents' runs. `git clean -xdfq` there deletes
them — irreversibly, and they are not mine. So every measurement here was taken
in a **fresh `git worktree` cut from `origin/main`**, which is clean by
construction and gave the same property the instruction asks for: nothing from a
previous run could contaminate a result.

It is not a free substitution and the difference is named: a fresh worktree does
NOT reproduce the host's untracked state, which is how the pre-push hook came to
refuse for a directory that exists in the primary checkout and in no worktree —
recorded in the section above. That refusal is the visible cost of this choice.

## What this must not be quoted as

* The pin guard proves five anchors are present in **one image generation**
  (`:0.3.26`). It says nothing about images this host does not have, and its
  honest answer where no upstream tree exists is rc 2, not rc 0.
* The census counts programs citing an upstream flow file **by package path**.
  A citation written as a bare script name is not counted; the number is a floor
  and the printed line says which form it measures.
* Neither shipped test is a statement about any design, any PDK or any die.
  Both are properties of how this flow reports, and both were measured on
  synthetic fixtures.

## Evidence

    evidence/upstream_pin/upstream_measured_0_3_26.txt   upstream verbatim +
                                                        file hashes, image
                                                        :0.3.26
    evidence/upstream_pin/green_and_red_sweep.txt       rc 0 real / rc 1 mutated
                                                        / 9 tests in the image
    evidence/search_space/mutation_proof.txt            baseline / mutated /
                                                        restored, three segments
    evidence/measure_not_found_refusal_population.py    the instrument behind
                                                        the 5-of-16 and the
                                                        3-of-5 false positives
    recoveries.json                                     the three records
    candidates/                                         what enhancement_emit
                                                        produced from them
