# Bucket A — program-rule sketches for programs/pad_ring_gen.py
# Corpus-sweep REQUIRED before merging into programs/pad_ring_gen.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A step resolves a declared name against files it discovered itself, finds nothing, and refuses NOT FOUND while naming only how many candidates it found. The count is real and the search space behind it is one view of several, so the refusal reads as a fact about the input when it is a fact about where the step looked. Not found and not looked for arrive at the reader as the same sentence.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_refusal_names_the_views_it_read(sample_text, ports):
    """A refusal that says a declared name was not found must enumerate the search space it covered: every source kind consulted, the path each one resolved to, and how many candidates each one yielded. A count of hits is not a search space. The enumeration goes in the artefact as data, not only in the message as prose, so a reader and a downstream gate see the same list."""
    # Expected signal: ERROR
    # Suggested fix action: Emit the consulted source kinds as a list on the refusal record, each with its resolved path and its yield, and render the same list into the human message. A source kind that was skipped is listed with the reason it was skipped rather than omitted.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: Our code re-derives a computation that an upstream flow already performs, the two are never compared by any machine, and ours drifts. The drift is silent because the re-derivation is self-consistent and its own tests assert our constants against our constants. It surfaces later as an unrelated refusal, at a distance from the line that drifted.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_upstream_reimplementation_carries_a_pin(sample_text, ports):
    """A program that re-implements a computation performed by an upstream flow must carry a pin: the upstream file, the exact anchor text in it that fixes the quantity, and the quantity our code takes from it. A test must read the real upstream file and fail when the anchor is absent, and must decline honestly with a named missing input when the upstream tree is not present on the host, never pass vacuously."""
    # Expected signal: ERROR
    # Suggested fix action: Declare the pin beside the code it constrains, resolve the upstream file at test time from the installed tool tree, and assert the anchor. Report an unpinned re-implementation as a census entry rather than a pass, so the set of unpinned ones is a measured number instead of an assumption.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A configuration variable is accepted by a step and changes nothing it produces. The step is silent about that, so an author who sets the knob is told nothing and reads the unchanged result as the knob having been honoured. Inertness is decidable by measurement rather than by reading code: perturb the value, re-run on the same input, and diff the artefact.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_inert_declared_variable_degrades_loudly(sample_text, ports):
    """A variable a step accepts but whose value provably cannot change the step output must degrade loudly in both directions. Left at the upstream default, indistinguishable from never having been set, the step proceeds and records the inertness with the measurement that established it, in every report it emits including the skips and the refusals. Deliberately set to a non default, the step returns exit code two and names the variable, because a request it cannot honour is neither a pass nor a finding about the design."""
    # Expected signal: ERROR
    # Suggested fix action: Establish inertness by differential probe rather than by inspection, carry the measurement in a registry beside the variable, disclose it on every emitted report including the ones that decline, and refuse a declared non default with exit code two naming the variable.
    return []  # list of findings — TODO implement
