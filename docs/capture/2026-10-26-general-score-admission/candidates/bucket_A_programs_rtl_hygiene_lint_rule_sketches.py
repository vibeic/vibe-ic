# Bucket A — program-rule sketches for programs/rtl_hygiene_lint.py
# Corpus-sweep REQUIRED before merging into programs/rtl_hygiene_lint.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.32.5
# Pattern: Original-source RTL is validated by a generated-spec consumer that requires an absent generated document and publishes the wrong consumer row name.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_original_native_lint_contract(sample_text, ports):
    """Native lint must consume the selected original RTL contract without requiring generated specification documents."""
    # Expected signal: AUTO-FIX
    # Suggested fix action: Reuse the existing native lint producer and emit the row expected by the original-input consumer; retain malformed RTL, ambiguous top, native identity and transport failures.
    return []  # list of findings — TODO implement
