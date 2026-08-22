# Bucket A — program-rule sketches for programs/pad_ring_gen.py
# Corpus-sweep REQUIRED before merging into programs/pad_ring_gen.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step concludes a named thing is ABSENT after consulting one of the several views a distribution ships for that class of thing, and reports the conclusion as a fact about the distribution rather than as a fact about what it read. The disclosure is not what is missing -- such a step routinely names the files it opened and the zero it found in them -- so a reader auditing the artefact sees a complete, honest, wrong answer. What is missing is the comparison between the views that exist and the views that were opened.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_refusal_on_absence_falsified_by_the_declaration_grammar(sample_text, ports):
    """A refusal that a declared name is ABSENT must be falsified against the views the step did not read -- and the falsification must ask through the DECLARATION GRAMMAR for that class of thing, never through a free-text search. It fires only when the refused name is actually DECLARED in a view the step did not open. The step already owns a parser for that grammar, so the check reuses it rather than inventing a search."""
    # Expected signal: ERROR
    # Suggested fix action: On any verdict asserting a declared name is absent, take the name from the step's own artefact, enumerate the view directories of the resolved tree, subtract the ones the artefact says were read, and run the step's OWN declaration parser over the remainder. A declared hit means the refusal is false and names the file. No hit means the refusal stands and the check is silent.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step re-implements an upstream computation and its arithmetic drifts from upstream's, in a direction no test covers because both agree on the inputs the tests use. The drift surfaces later as an unrelated refusal rather than as a wrong number, so it is attributed to the thing that refused instead of to the arithmetic. Here the along-the-row extent was taken from the ORIENTED footprint while upstream takes the master's width in both places it measures, on all four sides.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_correspondence_declared_then_pinned(sample_text, ports):
    """A re-implementation must DECLARE which upstream computation it mirrors and which primitive that computation measures with; the declaration is then checkable, and the check is a program. Detection without the declaration is NOT a program -- see the generality sweep -- so the deterministic work is the declaration format plus the checker that reads the named upstream file, confirms the named primitive is what it uses, and asserts our function does not transform it before aggregating."""
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

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A step re-implements a tool's interface and inverts one of its CONVENTIONS -- which of two symmetric cases a named input applies to. Both names exist on both sides and both sides accept both values, so nothing type-checks and nothing errors. It is invisible wherever the two inputs carry the same value, which is the default, so the defect ships and waits for the first author who sets exactly one of them. Every downstream artefact is then internally consistent and disagrees with the tool.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_convention_not_inverted(sample_text, ports):
    """A re-implementation must not invert its upstream's convention. Where an upstream input selects between two symmetric cases, the case our step applies it to must be the case the upstream documents it for. The comparison is between two enumerable mappings and it is a program's decision once the upstream mapping is declared -- which is the same declare-then-check shape the arithmetic pin in this batch arrives at."""
    # Expected signal: ERROR
    # Suggested fix action: Declare the upstream mapping beside our own and assert they agree, and take the upstream half from the tool's DOCUMENTED contract rather than from the argument names. Here, measured side by side: ours sends the horizontal-named variable to the south and north sides and the vertical-named one to the west and east sides; the tool documents the opposite for both. The two mappings are four entries each, so the check is a dict comparison.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A re-implementation derives the opposite of a symmetric pair with the wrong TRANSFORM -- a half turn where the upstream mirrors, or the reverse. For a rectangular footprint the two occupy the SAME bounding box, so every geometric check downstream agrees under both and the defect passes fit, spacing, abutment and coverage alike. What differs is where the cell's PINS end up. The artefact is internally consistent, passes its own gates, and faces the wrong way.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_opposite_side_transform_matches_upstream(sample_text, ports):
    """Where a step derives one member of a symmetric pair from the other, the transform must be the transform the upstream uses. Mirroring and half-turning are interchangeable for a bounding box and are not interchangeable for a cell. The check compares two named transforms and is a program's decision once the upstream one is declared -- the same declare-then-check shape the other pins in this batch arrive at."""
    # Expected signal: ERROR
    # Suggested fix action: Declare the upstream transform beside ours and assert they agree. Upstream derives the opposite side by MIRRORING on both axes -- north from south by a flip about X, east from west by a flip about Y -- and states it in two lines of its own source. Ours applies a half turn on both axes through a helper whose docstring says 'one quarter turn clockwise'. Any bounding-box-based test will pass under either, so the test that pins this must compare the ORIENTATION TOKEN, never the extents. And the pinning test must compare the ORIENTATION TOKEN, never the extents: an extent-based assertion passes under both and reads as coverage.
    return []  # list of findings — TODO implement
