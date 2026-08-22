# Bucket A — program-rule sketches for programs/phase3_one_shot_runner.py
# Corpus-sweep REQUIRED before merging into programs/phase3_one_shot_runner.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: An emitter labels a line or a key as the source of its numbers and fills it from a literal in its own source, so every run of every design publishes the same source claim; when a measured source stamp is later added beside it, the artefact carries two source claims and the constant one can never look wrong.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_provenance_value_is_resolved_not_constant(sample_text, ports):
    """A field that states where an artefact's numbers came from must hold a value the emitter resolved, never a path typed into the emitter's own format string. A constant reports the path the author intended to read rather than the path that was read, so it stays correct-looking when the read failed, when the layout moved, and when the artefact is about something else entirely."""
    # Expected signal: ERROR
    # Suggested fix action: At each write of an artefact, refuse a path-shaped value under a source-naming label when that value is a constant in the emitter rather than a resolved variable, and refuse a second source-naming line in a write that already emits a resolved input list. Render every such line from the resolved values, and record an input that was named but could not be read as unreadable rather than omitting the line, so that an absent input and an unexamined one stay different facts.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: One report in a family carries the stage statement because its own emitter writes it, and the sibling reports that actually decide the slow and fast corners are written by different emitters that do not, so the rows that matter most are scoped to nothing and the missing evidence is reported as an incomplete view set.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_signoff_report_states_its_stage(sample_text, ports):
    """A report a step offers as sign-off evidence must state which side of place-and-route its numbers come from. The reader that normalises that statement is already correct in treating its absence as undeclared, which means an unstamped report is dropped from the evidence set quietly instead of being refused, and an axis with no evidence reports an incomplete view rather than a failure."""
    # Expected signal: ERROR
    # Suggested fix action: Emit the stage statement from one shared helper used by every report emitter in the family rather than per emitter, and add a gate that requires it on every report a step declares as sign-off evidence: missing at emit time is an error, and missing at read time is an undetermined verdict, never a pass.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A report header states one side of place-and-route while the script beside it links the netlist from the other side and loads no parasitics, so the published number is invariant under every knob that changes the layout and still reads as a measurement of the thing that was built.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_declared_basis_matches_the_session_inputs(sample_text, ports):
    """The stage an artefact claims must be derived from the inputs its own analysis session declared, not from the directory the artefact was filed in. A session that links the pre-layout netlist and loads no extracted parasitics has measured the pre-layout design however its header reads, and the resulting number cannot move when the layout moves."""
    # Expected signal: ERROR
    # Suggested fix action: Parse the emitted analysis script for the netlist it links and for whether it loads extracted parasitics, derive the stage from those declarations, and refuse a header whose claimed basis disagrees with them; a header claiming a post-layout basis in a session that loaded no parasitics is an error, not a note.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A generator writes the absolute path of the directory a run happened in into the script that defines the measurement, so the artefact that ought to be the stable identity of a configuration becomes unique per run and every identity check over it either refuses or is dropped.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_emitted_script_portability_check(sample_text, ports):
    """A path an emitter writes into a generated analysis script must be relative to the project root or to a declared tool root. An absolute run-directory path makes two runs of one configuration hash differently, so any identity taken over that script identifies where the run happened instead of what was configured, and the two runs can never be compared as the same measurement."""
    # Expected signal: ERROR
    # Suggested fix action: Write every path in a generated analysis script relative to the project root or to a declared tool root, and fail the emit when an absolute path outside those roots is written. Extend the existing absolute-path rule from shipped source and from analog decks to the population of generated analysis scripts; do not solve it by dropping the script from the identity.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A consumer proves an axis from one metric name while the extractor publishes the same quantity under another, so the axis is unprovable on every run and each run appears to blame its own evidence rather than the wiring.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_every_required_metric_key_has_a_producer(sample_text, ports):
    """A key a floor check proves an axis from must be a key that some producer emits. When the consumer's name and the producer's name for one quantity differ, the check reports the value as not measured on every view of every run, which reads as missing evidence about that run instead of as a wiring fault that no run can ever satisfy."""
    # Expected signal: ERROR
    # Suggested fix action: Cross-reference the key names consumers prove from against the key names producers emit, and error at wiring time on any required key that no producer emits, naming both sides. Model it on the existing gate that requires a producer for every document field a checker reads: same shape, different population.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A consumer resolves an axis to the emitter's raw measurement file instead of to the sign-off checker that compares that measurement against a declared limit, so the absence of a count becomes indistinguishable from a count of zero and the axis reports a pass that no comparison produced.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_measurement_only_artefact_is_not_a_verdict_source(sample_text, ports):
    """An artefact whose own verdict field declares it a measurement rather than a sign-off may not be read as the evidence for a floor check. A reader that derives a count from it gets either an unmeasured row or, worse, a zero — and a zero here is a clean result that nobody computed, against a limit that was never named."""
    # Expected signal: ERROR
    # Suggested fix action: Refuse an artefact that declares itself a measurement as evidence for a floor check; resolve the sign-off producer registered for that axis instead, and where no sign-off ran, report that it did not run together with the reason. Never substitute zero for a count that was not computed.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A precheck delegates to the same checker with a reduced argument set and writes the result at the flow's canonical evidence path, so one path has two writers and the writer that dropped the sign-off scoping wins by running last.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_only_the_declaring_step_writes_its_output(sample_text, ports):
    """A path one step declares as its own required output may be written only by that step's producer. A helper that runs the same checker with fewer arguments leaves a strictly weaker verdict wearing the declared filename, and a release-gating tier then grades the weaker file without any indication that a stronger one existed."""
    # Expected signal: ERROR
    # Suggested fix action: Refuse any write to a path that the flow declares as another step's required output. A non-declaring writer must use both a private directory and a different basename, because discovery here is by recursive glob and a private directory alone is still found. Guard the rule with a negative control asserting the historical paths are still recognised as flow-owned, so the check cannot pass over an empty set.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A generator emits a value that could have come either from the design's own input documents or from its own last-resort default, marks neither, and the resulting artefact is indistinguishable in both cases, so a silently unread input produces a complete and plausible run about the wrong constraint.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_generated_values_state_whether_they_were_read_or_defaulted(sample_text, ports):
    """A generator that falls back to a built-in value when it cannot read one from the design must say which of the two happened, and cite the input it read. Without that line a default and a design-declared value are the same bytes, so nobody can see that the design's own statement was never applied, and every verdict downstream is about a constraint the design may never have asked for."""
    # Expected signal: ERROR
    # Suggested fix action: For every value a generator can either read or default, emit a disclosure line beside it stating which happened; for a read value name the input file and line it came from and the key that matched. A design that declares nothing keeps the historical default byte-for-byte and its disclosure says exactly that, and two input rows that match with different values are refused rather than resolved by list order.
    return []  # list of findings — TODO implement
