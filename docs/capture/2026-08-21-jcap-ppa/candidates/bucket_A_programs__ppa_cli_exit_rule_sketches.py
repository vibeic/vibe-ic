# Bucket A — program-rule sketches for programs/_ppa/cli_exit.py
# Corpus-sweep REQUIRED before merging into programs/_ppa/cli_exit.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.68
# Pattern: An interface fixes which output stream carries the human summary and which carries a refusal, so that a caller can capture one without the other and a grep over a log means something. Nothing enforces it, because the obvious test — run the command and look — is run with no arguments, which produces an argument-parser error rather than a verdict. So every program looks identical under the test, the clause is never measured, and programs drift onto whichever stream their author reached for.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_which_stream_carries_the_summary_is_part_of_the_contract_and_must_be_driven_to_a(sample_text, ports):
    """Stream assignment is part of a command's contract, not a formatting preference: a caller that captures one stream and not the other gets a different answer depending on which program it invoked, and a log grep that finds nothing cannot distinguish a clean run from a summary written where nobody looked. Enforcing it requires driving each command to a REAL verdict, because the argument-parser error path is on the refusal stream for every command and tells you nothing about the clause."""
    # Expected signal: ERROR
    # Suggested fix action: Give each command a known-verdict invocation in the layer's own contract test — an input that produces a finding, and one that produces a could-not-check — and assert per stream that the summary lands where the interface says and the refusal marker lands on the other. MEASURED, two-sided, on comparable runs: the comparison command driven to a vacuous corpus puts its summary line on the output stream and its could-not-check marker on the error stream, which is the contract observed exactly; the contract command driven to a real document with sixteen findings puts EVERYTHING on the error stream, summary line included, leaving the output stream empty. One conformant, one not, out of the two I drove to a real verdict — the other seventeen are NOT MEASURED and are not claimed. THE SCREEN WARNING, EARNED: running each command with no arguments and comparing stream byte counts reports eighteen of nineteen on the error stream and is worthless, because that is the argument-parser path. It measures argparse, not the contract.
    return []  # list of findings — TODO implement
