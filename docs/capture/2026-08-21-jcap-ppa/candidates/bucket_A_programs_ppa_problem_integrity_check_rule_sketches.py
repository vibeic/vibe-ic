# Bucket A — program-rule sketches for programs/ppa_problem_integrity_check.py
# Corpus-sweep REQUIRED before merging into programs/ppa_problem_integrity_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A scheme partitions a run's artefacts into named identities and one of them carries a written membership prohibition. The others carry none, so what belongs in them is inferred from the examples that happen to exist. A run whose shape the examples do not cover is then judged by the reader's inference rather than by the scheme, and two readers infer differently. Detect by requiring a stated membership rule for each declared identity, not only for the one whose violation was noticed first.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_every_identity_a_scheme_declares_must_state_what_may_not_sit_in_it(sample_text, ports):
    """Every identity a scheme declares states what may not sit in it.

A partition with one written rule and several unwritten ones is not a partition; it is one rule plus a convention. The unwritten members are the ones a novel run will land in, because the covered case is the one somebody already hit. State the prohibition for each identity, so a run of an unanticipated shape is judged by the scheme rather than by whoever reads it."""
    # Expected signal: the identity scheme is refused when a declared identity carries no stated membership rule, naming the identity
    # Suggested fix action: MEASURED on the interface document that declares the scheme: it names 5 identities, and exactly 1 carries a bold prohibition saying what may not sit in it -- the one whose violation had already been found. The other 4 have none. The concrete cost is a request this lane's own source made and this batch had not recorded: a cross-layer search must place the specification in the problem identity and the rewritten design in the implementation identity, and because that membership rule is unstated, the obvious reading of the document makes the integrity checker refuse every legitimate cross-layer comparison. The rule was not missing because nobody thought about it -- it is stated, in bold, one identity over, in the same section. BUILD: enumerate the declared identities from the document that declares them, require each to carry a membership rule in the same form as the one that exists, and refuse the scheme naming any identity that does not. The predicate is presence of a stated rule per declared identity, the population is the identity list itself, and the refusal names the identities lacking one. Start from the wording the source proposes: an artefact the search is permitted to rewrite may not sit in the problem identity.
    return []  # list of findings — TODO implement
