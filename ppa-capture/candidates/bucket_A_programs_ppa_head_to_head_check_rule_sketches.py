# Bucket A — program-rule sketches for programs/ppa_head_to_head_check.py
# Corpus-sweep REQUIRED before merging into programs/ppa_head_to_head_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A comparison gate declares, per axis, the set of measurement-condition keys two numbers must both carry before they may be compared. The module that emits that axis fills the keys it happens to have. Nothing relates the two sets. A producer short of one key makes every comparison over its numbers refuse, on both arms at once, before any value is looked at — and the refusal names a key, not a producer, so it reads as a caller mistake rather than as the emitting module's gap.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_required_scope_keys_are_emitted_by_their_producer(sample_text, ports):
    """Each key a comparison gate requires of an axis must be emitted by the module that produces that axis, or that module must record, beside the scope it did not fill, the reason it could not. The two-sided rule matters: a key filled with an empty or null placeholder is worse than an absent one, because two placeholders compare equal and two numbers taken under conditions nobody recorded then pass as taken under the same conditions."""
    # Expected signal: ERROR
    # Suggested fix action: For each axis of the comparison gate's required-keys table, construct the producing module's scope on a fixture and diff the key sets. Refuse when a required key is neither emitted nor accounted for by a recorded gap reason. Refuse separately, and with a distinct code, when a required key is present with a null or empty value.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A tool grows a second way to name its input — a directory of many alongside the single positional one — and the two are wired as independent options rather than as alternatives. Given both, the later branch wins and the other input is never opened. Nothing is printed about the input that was dropped, so a caller who names a failing record and adds the directory flag is told the directory's verdict and never learns the record was not read. The exit code changes with it, from a finding to a could-not-check, which reads as an improvement.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_two_input_selectors_given_together_must_refuse(sample_text, ports):
    """Two selectors that name the same input in different ways are ALTERNATIVES and must be declared as such: given both, refuse as a bad invocation and name both. Silently letting one shadow the other converts a real verdict into a different verdict on an unrelated population, and the caller has no way to tell — the output is well-formed and describes work that was genuinely done, just not on the thing they named."""
    # Expected signal: ERROR
    # Suggested fix action: Put the single-target and the collection selectors in one mutually exclusive group so the argument parser itself refuses both, and return the bad-invocation exit code rather than the could-not-check one. Where an existing caller depends on passing both, adjudicate BOTH populations and aggregate under the most-severe rule; never pick one silently. Add the both-given case to the layer's bad-invocation arm so every tool in the layer is covered by the same test rather than this one.
    return []  # list of findings — TODO implement
