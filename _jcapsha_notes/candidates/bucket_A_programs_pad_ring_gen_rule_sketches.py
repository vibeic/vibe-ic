# Bucket A — program-rule sketches for programs/pad_ring_gen.py
# Corpus-sweep REQUIRED before merging into programs/pad_ring_gen.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step re-implements an upstream flow's config contract and silently drops one of the inputs that contract declares. The dropped input is the one that closes a branch the step then refuses on, so the refusal is TRUE about what the step read and FALSE about what the distribution declared. Nothing downstream can see the difference, because a step that never looks for an input reports exactly what a step that looked and found nothing reports.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_input_set_pin(sample_text, ports):
    """Pin the INPUT SET of a re-implementation against its upstream. For any module that declares it borrows an upstream config contract, the set of variables upstream declares for that contract must equal the set this module either CONSUMES or explicitly declares UNPERFORMED. A variable in neither list is a silently dropped input. The comparison is a set difference over two enumerable lists, so it is a program's decision and not a reader's."""
    # Expected signal: ERROR
    # Suggested fix action: Parse the upstream config module for the variables it declares in the contract being borrowed, parse this module's own declared-required and declared-unperformed tuples, and refuse on the set difference, naming each dropped variable and the upstream docstring that says what it is for. The refusal must NAME the variables, not count them. A count is not the output: two defensible denominators over this same pair gave 11-of-20 and 13-of-14, so the finding is the list of unaccounted names or it is nothing.
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
