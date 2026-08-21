# Bucket A — program-rule sketches for programs/plugin_change_pytest_gate.py
# Corpus-sweep REQUIRED before merging into programs/plugin_change_pytest_gate.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A suite parametrises over a population it DISCOVERS (a glob, a registry walk) but drives each member with an invocation it DECLARES (a hand-maintained table). The guard against an empty population is written as a floor — at least N — with N frozen at the count on the day the two numbers happened to agree. The floor then passes forever while the two sets drift apart, so a member added later is silently uncovered, and an entry left behind for a member since deleted is invisible in the other direction. The guard's own message keeps quoting the old count.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_population_guard_asserts_equality_not_a_floor(sample_text, ports):
    """A population guard over a discovered set must assert EQUALITY against the declared set and print the symmetric difference, never a lower bound. A lower bound answers a question nobody asked — is the population non-empty — while the question that matters is whether every discovered member is declared and every declared member still exists. A floor cannot see either drift, and it reads as coverage while holding neither."""
    # Expected signal: ERROR
    # Suggested fix action: Replace the floor assertion with a set-equality assertion between the discovered population and the declared invocation table, whose message prints both counts and both directions of the difference. Emit it ONCE for the whole population rather than once per member, so the reader gets the list instead of N single names. Where two declared tables cover one discovered population, assert both against it and assert the two tables agree with each other.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A suite that enforces a LAYER-wide property selects its population with a filename-prefix glob, because in the layer's first week the prefix and the layer were the same set. They stop being the same set as soon as the layer gains a module inside its own package, or a program that imports the layer under a different name. Every such executable is outside the population, so the layer property is unenforced on it — and the defect the suite exists to catch survives there untouched, with the suite green.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_layer_membership_is_declared_not_inferred_from_a_filename_prefix(sample_text, ports):
    """Membership of a layer is a RELATION — the executable imports the layer's package, or cites the layer's interface document — and it must be computed from that relation, never from how the file happens to be named. A naming convention standing in for a boundary silently shrinks the population every time the layer grows in a direction the convention did not anticipate, and the shrinkage is invisible because the members that fell out were never counted."""
    # Expected signal: ERROR
    # Suggested fix action: Define the population as every executable that imports the layer's package or cites the layer's interface document, and take the prefix glob as one contributor rather than as the definition. Assert that the relation-derived population is a superset of the glob-derived one, and drive every arm of the layer property over the relation-derived set.
    return []  # list of findings — TODO implement
