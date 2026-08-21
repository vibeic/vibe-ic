# Bucket A — program-rule sketches for programs/changelog_command_reproducibility_check.py
# Corpus-sweep REQUIRED before merging into programs/changelog_command_reproducibility_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: Shipped documentation quotes a command as the way to run a tool. The tool's options change; the document does not, because nothing relates the two. An existing guard may already check that the named FILE exists — which it does — so the command looks verified while the invocation itself has never been tried. An agent following the instruction literally gets an argument error and no output, and the document that sent it there is the same document a reviewer would consult to confirm the instruction is right.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_documented_command_must_be_accepted_by_the_program_it_names(sample_text, ports):
    """Every command quoted in shipped instruction text must be ACCEPTED by the program it names, not merely name a file that exists. Two extensions over the usual form of this guard, and each was needed to see a real case: the population must include the instruction surface an agent actually follows, not only the release notes and manifests; and the test must reach the OPTIONS, because a stale flag and a correct one point at the same existing file."""
    # Expected signal: ERROR
    # Suggested fix action: Join backslash continuations FIRST, then extract each quoted invocation, then decide acceptance from the program's own declared options — or by invoking it in a way that can only fail on argument parsing. Report the document, the program and the offending options. MEASURED: 165 quoted commands name a program that exists; 11 use an option the program neither declares nor mentions; 2 of those 11 confirmed by running them, one reporting `unrecognized arguments` outright and both exiting on an argument error. WRITE THE SCREEN CAREFULLY — mine was wrong twice, in opposite directions, on this same corpus: matching greedily across lines bled the trailing compliance block into the preceding command and reported 47, and confining the match to one line excluded every multi-line invocation and reported 0, missing the one case already proven by execution. A checker for this that is itself built by grep will reproduce one of those two numbers.
    return []  # list of findings — TODO implement
