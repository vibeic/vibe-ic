# Bucket A — program-rule sketches for tools/phase1_engine/ingest.py
# Corpus-sweep REQUIRED before merging into tools/phase1_engine/ingest.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: An extractor reads English specification prose and either ignores denial polarity or applies it uniformly. Uniform application is wrong wherever the denial is constitutive of the extracted concept rather than a negation of it, so a correct guard needs two things: the span the denial governs, and a table separating constitutive idioms from negating ones. Adding the guard without the table converts a false negative into a false positive and reads as a fix.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_denial_that_constitutes_the_value_it_appears_to_negate(sample_text, ports):
    """A polarity guard that treats every denial as a negation inverts the sentences in which the denial IS the value. A specification saying that a quantity is not stated is granting freedom, not withholding a number, and an extractor whose subject is freedom must read that sentence as a positive. Applying a blanket denial check to such an extractor silently drops the freedoms the specification granted — the same disease as ignoring polarity altogether, pointing the other way."""
    # Expected signal: ERROR
    # Suggested fix action: Give the shared polarity module a table of constitutive idioms keyed by the concept the calling extractor extracts, alongside its existing negating-denial patterns. Scope each denial to the value span with the module's existing scoping helper before classifying it. In the consultation gate, require every prose-reading extractor either to consult the module or to carry a declaration that its input is a grammar in which a denial cannot be spelled, and require that declaration to name its reason. Refuse a blanket denial check applied to an extractor whose extracted concept appears in the constitutive table.
    return []  # list of findings — TODO implement
