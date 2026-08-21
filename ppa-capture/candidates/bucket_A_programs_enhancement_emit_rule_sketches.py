# Bucket A — program-rule sketches for programs/enhancement_emit.py
# Corpus-sweep REQUIRED before merging into programs/enhancement_emit.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: One tool WRITES a document and a second tool VALIDATES it. The writer's own schema documents a field as free text; the validator requires that field to match a fixed prefixed form. Each side is self-consistent and each side's tests pass. The writer accepts and emits the malformed document with no complaint, so the refusal arrives later, from a different tool, in a different run, and only if somebody thinks to run it — by which time the document has been filed and the author has moved on.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_writer_enforces_the_field_shapes_its_declared_consumer_requires(sample_text, ports):
    """A writer that produces a document for a declared validator must apply that validator's field-shape rules AT WRITE TIME, not leave them to be discovered downstream. The two rule sets must come from one place: a shape restated in a second file is a shape that will disagree with the first. Measured cost of the split: the writer's own documentation gave no hint the field was constrained at all, so the natural reading produced a document its sibling refused."""
    # Expected signal: ERROR
    # Suggested fix action: Import the validator's field-shape rules into the writer and apply them to every field the validator constrains, before the file is written; refuse with the validator's own message so the two tools cannot disagree about what is wrong. State the constrained shape in the writer's schema documentation as well, since an author reads the writer's contract and never the validator's. Add a two-directional test: a well-shaped field writes and validates, and a free-text field is refused BY THE WRITER rather than only by the validator. MEASURED: 6 of the 29 backlog records already filed in this tree fail the shape rule their own validator enforces, and both records this lane emitted were refused on first write — by an author reading the writer's contract, which documents the field as free text.
    return []  # list of findings — TODO implement
