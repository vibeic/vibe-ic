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

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: The whole purpose of turning a recovery into a deterministic rule is that the next run recovers it with no agent present. That holds only if something invokes the program the rule lands in. Routing is chosen by naming the program that OWNS the subject, which is the right criterion for correctness and says nothing about whether anything runs it — and the tree separately tracks gates that no automatic verdict consults. Nothing joins the two, so a capture can be perfectly routed, perfectly implemented, and silent forever, while the record and the routing table both read as complete.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_distilled_rule_must_be_routed_into_a_program_some_verdict_consults(sample_text, ports):
    """Routing a rule to the program that owns its subject is necessary and not sufficient: the program must also be one that something invokes. A rule in a program no verdict consults is indistinguishable, from every artefact the capture produces, from a rule that fires and finds nothing — and it is worse than an unwritten rule, because the record asserts the class is now covered. Join the routing table to the wiring census at emit time and refuse the pairing, rather than discovering it when a later run does not catch the thing the record promised."""
    # Expected signal: ERROR
    # Suggested fix action: At emit time, resolve each record's target program through the routing table and check it against the wiring census the tree already maintains — the one that lists gates no automatic verdict consults, together with its standing baseline. Refuse a record whose target is unwired, naming both the record and the program, and say which of the two must change: wire the program, or route the rule to one that runs. MEASURED on this batch: 21 Bucket-A records resolve to 15 distinct programs and NONE of them is unwired, so the batch passes the check it is proposing — which is the result to want and not the one to assume, because I did not verify it until I wrote this rule. The census on this tree reports 619 gates with 61 unwired against a baseline of 59, and names three as newly unwired; one of those three is a program of the very layer this batch is about, so the pairing was reachable rather than hypothetical.
    return []  # list of findings — TODO implement
