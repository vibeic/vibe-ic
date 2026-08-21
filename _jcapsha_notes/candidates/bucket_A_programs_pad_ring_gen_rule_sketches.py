# Bucket A — program-rule sketches for programs/pad_ring_gen.py
# Corpus-sweep REQUIRED before merging into programs/pad_ring_gen.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step concludes a named thing is ABSENT after consulting one of the several views a distribution ships for that class of thing, and reports the conclusion as a fact about the distribution rather than as a fact about what it read. The disclosure is not what is missing -- such a step routinely names the files it opened and the zero it found in them -- so a reader auditing the artefact sees a complete, honest, wrong answer. What is missing is the comparison between the views that exist and the views that were opened.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_refusal_on_absence_falsified_against_unread_views(sample_text, ports):
    """A refusal that a declared name is ABSENT must be falsified against the views the step did not read. It fires only when the refused NAME is findable in a view that was not opened -- a grep over directories that exist, for a string the step itself chose. It cannot fire on a step that read one view and was right, because the name is not there, and it refuses the REFUSAL rather than the design."""
    # Expected signal: ERROR
    # Suggested fix action: On any verdict asserting a declared name is absent, take the name from the step's own artefact, enumerate the view directories of the resolved distribution tree, subtract the ones the artefact says were read, and search the remainder for that name. A hit means the refusal is false and the step must look there before it may refuse. No hit means the refusal stands, and the check is silent.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step re-implements an upstream computation and its arithmetic drifts from upstream's, in a direction no test covers because both agree on the inputs the tests use. The drift surfaces later as an unrelated refusal rather than as a wrong number, so it is attributed to the thing that refused instead of to the arithmetic. Here the along-the-row extent was taken from the ORIENTED footprint while upstream takes the master's width in both places it measures, on all four sides.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_arithmetic_pin(sample_text, ports):
    """Pin the ARITHMETIC of a re-implementation against its upstream. Where this repo re-implements an upstream computation, the measurement primitive upstream uses must be the one ours uses. Deterministic form: the value our side-fit sums must not flow from an orientation-dependent quantity, because upstream's own loop is orientation-independent. Implemented as a taint walk over the function's assignments: the name bound to the along-the-row extents must not trace to a call that swaps axes by orientation."""
    # Expected signal: ERROR
    # Suggested fix action: Walk the placement function's assignments and taint every name whose value flows from the orientation-dependent footprint helper. Refuse if the along-the-row extent is tainted. The upstream source that fixes the expected primitive is read from the pinned image at run time, not quoted from memory, and the gate returns NOT DETERMINED rather than PASS when it cannot read it.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step accepts a config variable the tool underneath does not honour as named, and proceeds without saying so. The author who set it is told nothing, and the artefact records a value that did not reach the geometry. The mirrored failure is a step that discloses the defect for the ONE variable it happened to measure and leaves the sibling variable, which is the one the tool actually mis-applies, unguarded.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_unhonoured_knob_degrades_loudly(sample_text, ports):
    """The degradation contract for a config variable a step accepts but cannot honour. At the value indistinguishable from never having set it: PROCEED, and carry the non-honouring record, with its measurement, in EVERY report the step emits INCLUDING its skips, because a disclosure present only on the happy path is not a disclosure. At any deliberately declared other value: exit 2 NOT DETERMINED naming the variable, never 0 and never 1, because being unable to honour a request is neither a pass nor a finding about the design. The rule is the contract, not the one variable: every variable the same tool call carries is in scope, not only the one that was measured."""
    # Expected signal: ERROR
    # Suggested fix action: Require, for any step that declares a variable unhonoured: the non-honouring record is a key of the BASE report template rather than of one branch, so it survives every early return; a deliberately declared value exits 2; and the guarded set covers every variable passed in the same tool call as the measured one. Drive the step's skip path and its proceed path and require the key in both, and drive it with a declared value and require exit 2.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A validator advertises an accepted vocabulary of the form PREFIX:IDENTIFIER, one prefix per namespace, and its character class cannot express the identifiers of one of those namespaces. The advertised form is then unusable for every member of that namespace, and the failure is invisible from the validator's side: it reports a well-formed refusal naming the very form the author used, so the author reads it as their own mistake and substitutes a different prefix. Nobody files it, because each individual author works around it in one line.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_component_vocabulary_admits_its_namespace(sample_text, ports):
    """Every prefix a component-vocabulary validator advertises must accept the identifiers of the namespace that prefix names. Deterministic form: for each advertised prefix, enumerate the namespace it points at from that namespace's own source of truth, and require the validator to accept every member. A prefix whose namespace is empty or unenumerable is refused as unverifiable rather than assumed fine."""
    # Expected signal: ERROR
    # Suggested fix action: Enumerate each namespace from its declared source and assert the validator accepts every member, as a test that fails when either the regex or the namespace changes. Do NOT simply widen the character class in isolation: the test is what keeps the two in step, and the widening without it would drift again the next time a namespace gains a character.
    return []  # list of findings — TODO implement
