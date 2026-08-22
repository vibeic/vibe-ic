# Bucket A — program-rule sketches for programs/plugin_change_pytest_gate.py
# Corpus-sweep REQUIRED before merging into programs/plugin_change_pytest_gate.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A checker resolves its subject from an environment pointer after parsing an explicit location argument and lets the pointer win unconditionally, so a caller who names a small fixture is answered about a large shared tree, the fixture's own defect is never seen, and binding the shared tree and testing against fixtures become mutually exclusive.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_explicit_argument_outranks_the_environment_pointer(sample_text, ports):
    """A pointer read from the environment may replace a location that is absent; it may never replace one the caller named on the command line. A program that lets the pointer win measures a tree the caller did not ask about and publishes the verdict under the caller's name, and the louder the pointer's tree, the more convincing the wrong answer looks."""
    # Expected signal: ERROR
    # Suggested fix action: Route every consumer through the one resolver that already states the rule — the pointer applies only when the named location is not a directory — and announce in the output both which location was scanned and which pointer was set and not followed. Add a source scan that refuses a pointer read which overwrites an already-parsed location argument.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A selection asks the runtime to load a plugin the runtime does not carry, every test in those files dies at load rather than at assertion, and the resulting failures are counted against the revision under test because nothing in the record names the runtime that produced them.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_pytest_aggregate_carries_its_runtime_identity(sample_text, ports):
    """An aggregate of test results records the tree it measured but not the runtime it ran in, so a failure caused by a dependency the runtime cannot import is charged to the tree. Two aggregates produced by different runtimes are then differenced as if they were one measurement, and the difference is read as a change in the code."""
    # Expected signal: ERROR
    # Suggested fix action: Stamp the aggregate with the runtime's identity — the image reference actually executed, the interpreter version, and the set of plugins the selection requests that the runtime cannot import — and refuse to difference two aggregates whose runtime stamps differ, naming the difference instead of subtracting across it.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: Automation prepares a checkout by cloning a branch name from a local path, the local branch position is stale, the commit under test is absent from the resulting tree, and the gate run produces a complete and internally consistent verdict about the wrong revision.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_prepared_checkout_states_the_revision_it_holds(sample_text, ports):
    """A checkout prepared for a gate run must state which revision it holds and prove it against the upstream reference it names. A clone taken from a local repository inherits that repository's own branch position, which can be many releases behind, so the run measures a revision nobody asked for and reports it under the newer one's name."""
    # Expected signal: ERROR
    # Suggested fix action: Resolve the named upstream reference from the upstream remote at preparation time and refuse when the prepared checkout's head differs, printing both. When the upstream cannot be reached, report that the revision could not be confirmed rather than passing — a checkout that cannot prove its revision is undetermined, not correct.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: One part of a system prepares a checkout with default options while another part requires that checkouts be self-contained, so the requirement and the preparation contradict each other permanently and the failure is read as a property of the subject instead of the setup.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_local_clone_does_not_borrow_objects(sample_text, ports):
    """A checkout cloned from a local path shares object storage with the source repository unless the clone is told not to. A preflight that requires a self-contained checkout then refuses the very checkout the automation prepared, every time, and the refusal names the checkout rather than the preparation that made it that way."""
    # Expected signal: ERROR
    # Suggested fix action: Scan the source for any clone of a local path that does not disable hardlinked and shared object storage, and require the option at every checkout-preparation site. Pair it with the preflight so the two cannot drift: the option the preflight demands is the option the preparation passes.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A refusal prints an invocation that omits an argument the entry point requires, so following the printed remedy exactly fails without ever running the command, and the reader concludes the refusal itself is wrong rather than that the message is stale.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_printed_remedy_runs_as_printed(sample_text, ports):
    """A refusal that prints a command must render that command from the same argument list a caller would run, and a test must execute it. A remedy assembled as prose beside the code that runs the real thing drifts from it silently, and the reader who follows the printed line exactly is the one who discovers the drift."""
    # Expected signal: ERROR
    # Suggested fix action: Build the printed remedy from one argument-list builder shared with the caller that runs it, so the printed line and the executed line cannot drift. Execute it in a test that asserts BOTH a zero exit and a marker in the output — a zero exit alone is the signature of an entry point that swallowed the command — and add the negative control that the same list without the entry-point argument fails, otherwise the test passes against an image with no entry point at all.
    return []  # list of findings — TODO implement
