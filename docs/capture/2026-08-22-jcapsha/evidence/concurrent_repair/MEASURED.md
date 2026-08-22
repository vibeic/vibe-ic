# "provably nothing else" — measured, and it is a time window, not a proof

Found while running the host-independence gate against the same worktree this
lane was editing. Not looked for; it destroyed this lane's work twice before
it was identified, which is how it was noticed at all.

## What the gate does

`gate_host_independence_check._repair_checkout` tidies up after each gate it
drives. Its rule, quoted from its own docstring:

    * a TRACKED path that was pristine before and is modified after -- the
      difference was made by the child this loop just ran, so
      `git checkout -- <path>` undoes that and provably nothing else.
      REPAIRED.
    * a path that was ALREADY dirty before the drive -- somebody's in-flight
      work ... it is NAMED and left exactly as it is. REFUSED.

The boundary is drawn deliberately and the docstring says why: "an over-eager
repair here would destroy a maintainer's work in order to tidy up after a
gate." That is exactly the right concern, and the mechanism does not deliver
it.

## Why the rule does not hold

Pristine-before and modified-after does not identify the WRITER. It identifies
a TIME WINDOW. Anything that modifies a tracked file between the two snapshots
matches the rule — including a person or an agent editing the tree while the
gate runs — and `git checkout -- <path>` then takes every uncommitted change in
that file, which is what that command does. It is not an undo of one write; it
is "make this file equal HEAD".

## The live positive control

The gate was already running against this worktree. One line was appended to a
tracked file and the working tree watched:

    10:00:31  probe written                     git diff: 1 file changed, 2 insertions(+)
    10:00:57  probe still present: NO -- REVERTED

Twenty-six seconds, no message to the editor, no prompt, no record on the
editing side. The edit was not recoverable from git: it was never committed,
which is the precondition the rule selects for.

## The tool's own report, and the consequence that is worse than the loss

The run finished after the control above, and it names the file itself
(`gate_own_report.txt`):

    [GATE_CORRUPTED_CHECKOUT] no retired pytest plugin request
        this gate left the WORKING CHECKOUT modified while being driven (it
        exited normally). Every gate declared after it would have measured
        that. Restored: docs/capture/2026-08-22-jcapsha/evidence/
        rotation_axis/hv.tcl.

So the destroyed edit is only half of it. **The misattribution also
MANUFACTURED A FINDING AGAINST AN INNOCENT GATE.** The gate named there did
not modify the checkout; this lane's editor did, in the window while that gate
happened to be the one running. The report says it "left the WORKING CHECKOUT
modified", classifies it `GATE_CORRUPTED_CHECKOUT`, and warns that every gate
declared after it would have measured the contamination.

A maintainer reading that would go and look for a write in a gate that has
none. That is the more expensive failure of the two: lost work is at least
visible to the person who lost it, while a false accusation is delivered to
somebody with no way to tell it from the five real ones beside it in the same
list.

It also means the enclosing verdict is not clean data. This run reported
`[FAIL] 17 of 81 probed corpus gate(s) ... 6 GATE_CORRUPTED_CHECKOUT,
11 HOST_DEPENDENT_VERDICT`. Exactly one of those six is this lane's editor and
not a gate. The other sixteen are not judged here and nothing above should be
read as a claim about them.

## What makes this the same shape as the rest of this bundle

The docstring states an attribution as a proof — "provably nothing else" — and
nothing re-checks it. That is the same defect as the one this lane converged
on: a module header asserted what an upstream tool would do, the assertion was
wrong, and it kept a refusal firing for the life of the step. A sentence
somebody wrote down is not a measurement, and the more carefully it is written
the longer it survives unexamined.

## The fix, and it is deterministic

The gate cannot attribute a write by timing alone, and it does not need to:
it needs to stop CLAIMING it can.

  1. REFUSE rather than repair whatever it cannot attribute. The repo state at
     the start of the drive is already captured; capture it again immediately
     before each `checkout --` and refuse the repair if the path's content
     changed a second time, because a file being written twice inside one
     drive is not a file only the child touched.
  2. Make the repair OPT-IN for a repo root the run does not own. In its
     designed setting -- a quiet tree in CI -- repair is right. Given an
     arbitrary `repo_root` argument, which is how it is invoked, the safe
     default is to NAME what changed and leave it.
  3. Whichever is chosen, SAY IT. The repaired paths and the assumption behind
     the attribution belong in the output. An editor whose work is discarded
     currently learns it from a later failure, if at all.

None of the three needs judgement. All three are the honest-undetermined rule
this repository already applies everywhere else: a check that cannot attribute
a change has not attributed it.

## Scope, stated

This does NOT reproduce in the gate's designed setting: a tree nobody is
editing has no second writer, and the attribution is then correct. It needs a
concurrent editor, which on this fleet is the normal condition -- several
agents share one repository and the dispatch doctrine tells each to work in a
worktree of it. This lane hit it by running the gate on the tree it was
working in, which is exactly what "run the gate on your change before you
push" asks for.
