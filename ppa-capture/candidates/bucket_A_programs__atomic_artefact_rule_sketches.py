# Bucket A — program-rule sketches for programs/_atomic_artefact.py
# Corpus-sweep REQUIRED before merging into programs/_atomic_artefact.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A tool takes an output path from the caller and writes it as given. A relative path is resolved against the process working directory, which for a tool invoked from inside the installation is the installation. The write then creates directories and files inside the INSTALLED product, where they survive the run, appear as untracked additions, and can be picked up by the next hygiene or packaging pass as if they were shipped content. The failure is invisible to the caller because the write succeeds.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_runtime_output_path_may_not_resolve_inside_the_installed_tree(sample_text, ports):
    """An artefact written on behalf of a caller belongs to that caller's run, so its resolved destination must lie outside the installed product tree. Resolve the destination before opening it and refuse when it falls inside the installation, naming both the resolved path and the installation root. The refusal must happen BEFORE any directory is created: a run that refuses and still leaves a directory behind has done the damage it declined to do, which is worse than either outcome alone."""
    # Expected signal: ERROR
    # Suggested fix action: In the shared atomic writer, resolve the destination and compare it against the installation root computed from the module's own location. Refuse with the bad-invocation code before creating any parent directory. Two properties must be tested rather than assumed: that the refusal fires on a relative path when the working directory is the installation, and that after a refusal the tree carries no new entry — the measured case refused with the could-not-check code AND still wrote the file and its parent directory.
    return []  # list of findings — TODO implement
