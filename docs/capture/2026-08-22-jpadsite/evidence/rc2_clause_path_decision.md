# DECISION REQUESTED: the rc=2 mapping at `flow_compliance_check.py:3134`

Written in the shape the standing authority asked for: both sides, what each was
trying to achieve, options WITH MEASURED COSTS. **I am not blocked on this** —
the frozen branch neither needs nor touches it.

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
