# Bucket A — program-rule sketches (corpus-sweep before merge)

# v0.1.34+ — auto-captured by benchmark-enhancement-capture
# Pattern: Restoring division remainder register must be `dividend_width + 1` bits (extra bit catches the borrow/subtract result), NOT `dividend_width`.
# Source: div_16bit recovery 2026-05-28
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the existing VerilogEval + RTLLM + benchmark_clean corpora.

def rule_restoring_division_remainder_width(sample_text, ports):
    """Detect a restoring-division-style sequential / combinational divider where the remainder register width equals the dividend width. Common-bug WARN."""
    # Expected signal: WARN
    # Suggested fix action: Widen remainder to dividend_width + 1.
    return []  # list of findings — TODO implement
