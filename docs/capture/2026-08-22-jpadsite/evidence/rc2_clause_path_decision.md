# DECISION REQUESTED: the rc=2 mapping at `flow_compliance_check.py:3134`

Written in the shape the standing authority asked for: both sides, what each was
trying to achieve, options WITH MEASURED COSTS. **I am not blocked on this** —
the frozen branch neither needs nor touches it.

## CORRECTION TO THIS DOCUMENT, made after it was first written

I framed the exposure as "182 clauses / 140 programs" and found TWO pieces of
prior art (#492 at :7220, and :3134's own `_VACUOUS_HINT_PREFIX`). THERE IS A
THIRD, AND IT IS THE LARGEST: `_vacuous_exit.py` (#515) routes a gate's exit
code from the gate's OWN STRUCTURED CONCLUSION, and 61 programs in the tree use
it. Its header records the same discovery -- five gates announcing a skip in
stdout and exiting 0 anyway, four others already exiting 2 for the identical
situation, "both conventions live at once".

Measured against the clause path, that changes the number that matters:

    140  distinct programs invoked by the 182 clauses
     17  route through _vacuous_exit  (#515's router)
    123  do not
     93  of those 123 EMIT rc=2 BY HAND
     30  cannot return 2 at all -- unaffected either way

SO THE EXPOSURE IS 93 HAND-ROLLED rc=2 SITES, not 140 programs. Each decides on
its own what "2" means, and :3134 credits all of them identically. That is a
smaller and much more actionable number, and it also names the remedy shape the
repo already chose: #515's router, adopted by 17 of the 140 so far.

## The two sites, and the asymmetry

    :7220   P0 umbrella    10 gates      #492 SEPARATES the two meanings here
    :3134   clause path    182 clauses,  never given the same treatment
                           140 distinct programs

`#492`, in the code at :7220: rc 2 carried *"there was no input to check"* (a
benign verdict FROM the gate) and *"you called me wrongly"* (a defect IN THE
CALLER), and recording the second as a skip *"is what let 39 registered gates be
permanently silent while the umbrella advertised that all of them ran."*

That reasoning is not specific to the umbrella. It applies at :3134, which
covers **eighteen times as many gates**.

## What each side was trying to achieve

* **:3134's author** wanted a gate with no applicable input not to redden a run,
  and DID disclose it: the return carries `_VACUOUS_HINT_PREFIX` so a reviewer
  can see which gate passed vacuously. This is deliberate and documented, not an
  oversight.
* **#492's author** wanted a caller-side defect to stop hiding inside a benign
  verdict, because it had already cost 39 silent gates.

Both are right. They collide only because one exit code carries both meanings.

## Options, with costs

(a) **Do nothing.** Cost: 140 distinct programs can be silent-and-credited by
    the same mechanism #492 records as having silenced 39 gates. Benefit: zero
    churn.

(b) **Separate at :3134 as #492 did at :7220.** Cost: every step's label can
    move at once; needs its own flow-change-acceptance run with a corpus sweep.
    UNKNOWN AND LOAD-BEARING: how many of the 182 clauses return rc=2 in a REAL
    run. I do not have that population — my only sample is a constructed project
    where 1 of 2 gates returned rc=2, which is far too thin to rule on.

(c) **CENSUS FIRST.** Do not change the mapping. Emit a record counting, per
    real run, how many clauses returned rc=2 and which meaning each was.
    Cost: near zero, blocks nothing, and it PRODUCES THE DENOMINATOR (b) needs.

## Recommendation, and it is already ruled

(c). And it does not need a new ruling: the standing authority has already
decided this exact shape — *"the wide-population version becomes a CENSUS that
records debt and is never wired as blocking."* :7220 is the GATE that can
refuse; :3134's 182-clause population is the wide one, so it becomes a census.

**What I would do under that ruling, in `next/`:** a census program that reports
the rc=2 population per run, split by meaning, wired ADVISORY. Not the mapping
change — that waits for the denominator the census produces.
