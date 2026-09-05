# A gate may not enforce a precondition its published contract omits

`benchmark_dispatch` publishes the review envelope that an AI reviewer must satisfy,
including `challenge_supersessions`. That clause stated one condition: a fresh
semantic PASS proving an inherited challenge contradicts the prompt. The gate also
required the named target to validly FAIL, or be structurally INVALID on, the
candidate under review -- a precondition that appeared nowhere in the tree except
the refusal message, which a reviewer reads only after the review has already been
rejected.

A reviewer obeying the published contract exactly could therefore name a challenge
that contradicts the prompt but still passes the current candidate, and lose the
whole run on a criterion never advertised. That is the reported experience behind
issue #2033, and it explains that issue's conclusion that a passing inherited
challenge is categorically ineligible. The mechanism was sound; the contract was
not.

The published clause now states the precondition, that a still-passing challenge is
not blocking acceptance and must not be named, that naming one rejects the whole
review, that each target is named at most once, and that a replacement must differ
from its target. The refusal names the remedy rather than restating the rule alone,
and keeps its prior substring.

The audit behind it was enumerated rather than sampled: every literal refusal reason
in the three review validators was extracted and the seven belonging to the
supersession validator checked against what the task publishes. Five were already
published; two were not. Publication is owed to a rule a COMPLIANT reviewer can trip
over, not to every rule: the neighbouring anti-tamper requirement that a verification
test not be a symlink is deliberately left unpublished.

Nothing about acceptance changes. A still-PASSING inherited challenge remains
unsupersedable. That the predicate is untouched is checkable rather than asserted:
parse both revisions, blank every string constant, compare the ASTs -- they are
identical, and the same method detects a one-token predicate edit.

Test source and program changes are versionless; release assignment and any
subsequent main rebase belong to the Gatekeeper.
