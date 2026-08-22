# Bucket A — program-rule sketches for programs/pad_ring_check.py
# Corpus-sweep REQUIRED before merging into programs/pad_ring_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A step reports that a declared thing is absent, and its message discloses a count without disclosing which CLASSES of source that count ranges over. The reader cannot separate 'I looked everywhere and it is not there' from 'I looked in one of the two places that can declare it'. Disclosing a denominator and disclosing the POPULATION that denominator covers are different properties, and only the first was enforced anywhere.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_absence_verdict_names_its_search_space(sample_text, ports):
    """A negative verdict about a declared thing must enumerate the source classes it consulted, not merely count the items it found inside one of them. Not-found and not-looked-for are different verdicts; a message that states only a count reports the first while doing the second."""
    # Expected signal: ERROR
    # Suggested fix action: Require every absence verdict to carry the list of source classes searched, alongside the per-class count. A resolver that can read more than one class of source must name every class it can read in the refusal it raises when none of them answered.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A step re-implements a computation that an upstream flow already performs, cites the upstream file in prose, and nothing mechanical ever reads that file. The prose citation is a claim made once by a human and never re-checked, so the re-implementation drifts from its source silently and the drift surfaces later as an unrelated refusal rather than as a mismatch.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_reimplementation_is_pinned(sample_text, ports):
    """When a step re-implements an upstream computation, a test must READ the upstream artefact and go red when our version drifts from it. A citation in a comment is not a pin: it is a claim about a file, made once, that nothing re-evaluates."""
    # Expected signal: ERROR
    # Suggested fix action: Declare every module that mirrors an upstream computation, and require each declared mirror to carry a test that opens the upstream file and compares the pinned property. On a host without the upstream artefact the test declines BY NAME rather than passing vacuously.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A step publishes, as a disclosure to its reader, the finding that one of its configuration inputs has no effect. The finding rests on a sweep that varied that input while observing only PART of the population the input governs. Every number in the sweep is correct and the inference drawn from it is false, so the claim is unfalsifiable by re-reading the numbers and survives review.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_no_effect_claim_states_the_population_swept(sample_text, ports):
    """A published claim that a configuration input is without effect must state which population was varied AND which population was observed. No-effect and not-varied-for-the-part-that-responds are different verdicts, and a sweep that observed a subset can only support the second."""
    # Expected signal: ERROR
    # Suggested fix action: Require a no-effect disclosure to carry the observed population beside the varied one, so a reader can see when the two do not cover the same set. A claim whose observed set is narrower than the set the input is documented to govern is not a measurement of inertness.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A guard that requires a negative verdict to disclose where it looked accepts, as that disclosure, any word from its own vocabulary appearing anywhere in the message prose. Part of that vocabulary consists of the ordinary nouns for the thing whose absence is being reported, which an absence message can hardly avoid containing. The guard therefore passes verdicts that name no place at all, and would not notice if a real one stopped naming one.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_locus_word_naming_the_missing_thing_is_not_a_locus(sample_text, ports):
    """Words that disclose a PLACE and words that merely name the MISSING THING must not satisfy the same predicate. Only the first tells a reader where the search happened; the second is the subject of every absence message ever written, so accepting it makes the check unfalsifiable for the population it most needs to bind."""
    # Expected signal: ERROR
    # Suggested fix action: Partition the vocabulary. Only place-denoting words satisfy the prose branch; thing-denoting nouns continue to count when they are identifier names or appear beside a path-shaped literal, which is where they carry real information. The partition must be measured against the existing conformant population before it ships, because a guard that reddens on the state we just shipped is a bug rather than a guard.
    return []  # list of findings — TODO implement
