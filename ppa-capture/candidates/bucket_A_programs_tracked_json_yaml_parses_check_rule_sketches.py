# Bucket A — program-rule sketches for programs/tracked_json_yaml_parses_check.py
# Corpus-sweep REQUIRED before merging into programs/tracked_json_yaml_parses_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A hygiene gate walks everything the repository tracks and is given one root. A body of data is later moved into its own repository — the product still consumes it, resolving it at run time through an environment variable — and every root-scoped gate silently stops covering it. Nothing changes in the gate, its name, its wiring or its verdict; the population it walks simply got smaller and it has no way to say so. The split is recorded as a size or layout improvement and the loss of coverage is not recorded at all.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_repository_scoped_gate_loses_its_coverage_when_a_tree_is_split_out(sample_text, ports):
    """Coverage of a root-scoped gate is defined by the root it is handed, so a tree that leaves the repository leaves every such gate at the same moment, keeping the gate green while the data goes unchecked. Where the product already knows how to resolve an external tree at run time, the gates must be handed that root too, and where the tree cannot be resolved the run must SAY the tree was not covered rather than report on the part it could see. A split-out tree that is neither contained nor declared is invisible to the very checks written to walk everything."""
    # Expected signal: ERROR
    # Suggested fix action: Enumerate the gates that walk a repository index and the external trees the product resolves at run time, and run each gate over each tree, reporting per tree so an unresolvable one is a stated gap rather than a silent omission. MEASURED on this tree: 37 programs walk a repository index; 98 programs reference the split-out tree by name; the tree is NOT present here and the module list declares NO submodule, so it is resolved only through an environment variable at run time. The hygiene gate for this exact class is wired and is invoked with this repository's root alone. Its own header records the failure it was written for — a file truncated mid-string passing every landing gate — and the split-out tree was later found to hold five tracked files with precisely that corruption, discovered by a lane that happened to walk it with a different tool, because nothing else was looking.
    return []  # list of findings — TODO implement
