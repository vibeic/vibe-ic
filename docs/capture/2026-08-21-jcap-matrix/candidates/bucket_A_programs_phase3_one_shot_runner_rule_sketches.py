# Bucket A — program-rule sketches for programs/phase3_one_shot_runner.py
# Corpus-sweep REQUIRED before merging into programs/phase3_one_shot_runner.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A module spawns a checking program and discards the outcome: the result is unbound, the raise-on-failure flag is off, and the call sits inside a catch-everything block. The mirror shape is a gate whose declared subject is whether something RAN, implemented with no way to start a process or read a status at all. Both publish a verdict about something they never observed, and in both the prose around the code asserts the opposite.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_spawned_gate_whose_status_is_discarded(sample_text, ports):
    """A gate spawned as a subprocess delivers its verdict in its exit status. When the caller leaves the result unbound, turns off raise-on-failure, and encloses the call in a handler that swallows every exception, the verdict reaches nothing — and a comment beside the call can describe it as blocking with no reader noticing the contradiction. A call whose status no branch reads costs time and decides nothing."""
    # Expected signal: ERROR
    # Suggested fix action: Parse every module that spawns a subprocess whose argument vector names a checking program. Refuse when the result is not bound to a name, when no branch reads its status, or when the call is enclosed by a handler catching every exception without re-raising. Refuse separately when a program whose name or docstring claims to check that something RAN contains no process-spawning call and no status read. Where a spawn is deliberately advisory, require that intent declared at the call site, so it is a decision on the record rather than an absence inferred from silence.
    return []  # list of findings — TODO implement
