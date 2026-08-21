# Bucket A — program-rule sketches for programs/ppa_feasibility_check.py
# Corpus-sweep REQUIRED before merging into programs/ppa_feasibility_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A gate proves each of its axes from a fixed set of canonical measurement names, and the modules that emit measurements each carry their own name table. Nothing relates the two tables. When no emitting module carries any name an axis proves from, that axis is structurally unprovable: every run reports it as not determined, the gate's overall verdict can never be reached, and no candidate can ever be promoted. Every per-module test stays green throughout, because each module is only ever tested against its own table.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_gate_proof_vocabulary_has_a_producer(sample_text, ports):
    """Every measurement name a gate proves from must appear in at least one emitting module's declared name table. An axis whose whole proof vocabulary is unproduced is not a strict gate; it is a gate that cannot be answered, and the flow reports it as undetermined forever while looking healthy. The check is a set difference between two tables that already exist, so it costs one pass and it covers a name added tomorrow the day it lands."""
    # Expected signal: ERROR
    # Suggested fix action: Build the union of the emitting modules' declared name tables (the physical sign-off source list, the power category map, the area taxonomy, and a name table the timing module must gain because it composes its names with a format string today). Compare that union against the gate's per-axis proof vocabulary. Refuse, naming the axis and every name in it, when no group of an axis has a single produced name. Report the same difference in the other direction as a warning: a produced name no gate proves from is a measurement nobody reads.
    return []  # list of findings — TODO implement
