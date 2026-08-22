# Bucket A — program-rule sketches for programs/ppa_search_run.py
# Corpus-sweep REQUIRED before merging into programs/ppa_search_run.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A placeholder implementation carries an explanatory string saying WHY it cannot answer, and that string names a module or artefact as not yet present. The named thing lands later, in a different change, and the string is never revisited — it is a literal in a file nobody had reason to reopen. The stale claim is then copied verbatim into every document the placeholder publishes, where it reads as a current statement about the tree and is believed, because a provenance note is exactly the field a reader does not audit.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_published_absence_claim_is_rechecked_against_the_tree(sample_text, ports):
    """A published explanation that asserts a named artefact is ABSENT must be re-evaluated against the tree at the moment it is published, not written as a literal. Where the claim can be reduced to a path, the check is a file test and the refusal is unambiguous. Where it cannot, the string must not make the claim at all: a placeholder may say it has no evidence without saying why the evidence does not exist, and the version that says less is the version that cannot go stale."""
    # Expected signal: ERROR
    # Suggested fix action: Extract every repository-relative path mentioned in a published reason string, together with the absence verb attached to it. Refuse to publish when a path asserted absent resolves to an existing file. Apply it at the publish boundary rather than at each authoring site, so a reason string copied into a new publisher inherits the check.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A sweep turns a lever and records an objective on each arm. One axis of the objective is computed by a session whose inputs the lever cannot reach — it reads an upstream intermediate rather than the artefact the lever rewrote. The axis then returns the SAME value on every arm while every arm's actual artefacts differ. No individual number looks wrong, no gate fires, and the sweep publishes the axis as searched. A reader concludes the lever does not affect that axis, which is the exact opposite of what happened.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_metric_constant_across_arms_that_differ_is_not_measured_under_that_lever(sample_text, ports):
    """Across a set of arms whose implementations provably differ, an axis that takes ONE distinct value on every arm is not evidence that the lever does not move it; it is evidence that the axis was not measured downstream of the lever. Refuse to publish such an axis as searched. The invariance is stronger evidence than any single arm's magnitude error, and it is available without a reference measurement, which is what makes it checkable in the flow rather than only in a review."""
    # Expected signal: ERROR
    # Suggested fix action: At sweep publication, for each objective axis over the set of arms that RAN: count distinct values, and separately count distinct implementation identities. Refuse when the arms carry two or more implementation identities and the axis carries exactly one value. Name the axis, the shared value, and the number of arms. Two arms are enough for the rule to be non-vacuous, so it must not be gated behind a minimum sweep size; a sweep of one arm is skipped and SAYS it was skipped.
    return []  # list of findings — TODO implement
