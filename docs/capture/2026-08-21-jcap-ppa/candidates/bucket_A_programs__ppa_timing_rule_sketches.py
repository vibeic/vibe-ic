# Bucket A — program-rule sketches for programs/_ppa/timing.py
# Corpus-sweep REQUIRED before merging into programs/_ppa/timing.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A producer fills a measurement-condition key it could not determine with a null rather than leaving it out. The consumer cannot tell an unknown condition from a condition that does not apply, so it refuses -- correctly -- and the refusal names the key rather than the producer that could not resolve it. Detect by requiring every emitted scope key to carry a value, and by refusing the null at the producer where the reason is still known.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_scope_key_the_producer_cannot_establish_is_omitted__not_emitted_as_null(sample_text, ports):
    """A scope key the producer cannot establish is omitted, not emitted as null.

An absent key says the producer did not establish this condition. A null key says the condition is known and empty, which is false, and it survives into every comparison built on the record. Leave the key out and say why in the same place the value would have gone, so the gap is attributable to the step that had the information."""
    # Expected signal: a producer refuses, or omits with a stated reason, rather than emitting a null scope key
    # Suggested fix action: MEASURED, and every party to it has already said this is wrong. The interface document states it in bold -- a scope key that is present and null is worse than one that is absent. The comparison gate refuses on it by name, and a program comment records the size of the residue: 44 occurrences of that refusal on one field alone. The timing module emits it anyway, passing a null for the corner and the clock at 3 call sites, and the corner it cannot establish is the governing setup corner -- so the rows most needed for a sign-off comparison are the ones that carry the sentinel. THE FIX IS ALREADY DEMONSTRATED IN A SIBLING MODULE: the power producer had exactly this defect, and the lane that repaired it left a mutation arm behind -- revert the fix so the keys are emitted as null instead of omitted, and a named test goes red. So the pattern to copy, the test shape to copy, and the interface sentence to cite all exist; what is missing is the same edit one module over. BUILD: at the producer, omit any scope key whose value could not be resolved and record the reason beside the record rather than in the key, and assert it with a reverted-fix arm in the shape the sibling already uses. The predicate is presence of a null in an emitted scope, the population is every scope key every producer writes, and the refusal names the key AND the producer.
    return []  # list of findings — TODO implement
