# Bucket A — program-rule sketches for programs/crosslayer_rewrite_equivalence.py
# Corpus-sweep REQUIRED before merging into programs/crosslayer_rewrite_equivalence.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.69
# Pattern: A prover reports the same negative verdict whether it ran out of budget partway or finished its method and left a point open. The two demand opposite responses -- more time, or a different relation -- and the record distinguishes them only by elapsed seconds, which a reader must interpret. Detect by requiring any verdict a budget can cause to carry both how far the method got and whether the budget ended it.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_verdict_reachable_by_exhaustion_must_say_whether_it_exhausted(sample_text, ports):
    """A verdict reachable by exhaustion says whether it exhausted.

A negative result that a budget can produce is two findings wearing one name: the method did not finish, or the method finished and did not prove it. A caller that cannot tell them apart either wastes the budget again or abandons a provable case. Emit the depth the method reached and an explicit exhaustion flag beside the verdict, so the next decision is read rather than guessed."""
    # Expected signal: a budget-reachable verdict carries the depth reached and an explicit exhausted true or false
    # Suggested fix action: MEASURED on the program and on two of its own runs. Its emitted vocabulary includes `compared_points`, counterexample, `elapsed_sec`, `exit_code`, explanation, and -- this is the part that makes the omission legible -- `bounded_refutation_depth`. The program therefore already carries a depth field for ONE half of its method and emits 0 fields naming how far the induction got or whether a budget ended it. The consequence is two runs that a search must treat differently arriving identical: one converged and left a point open in 3.8 seconds, the other exhausted its budget partway through an estimated 33 induction steps after 1795 seconds, and both report a single unproven point. The only discriminator in the record is elapsed time, which the reader has to interpret. BUILD: emit the induction depth reached and an explicit exhaustion boolean beside the verdict, in the shape the refutation half already uses; the predicate is presence of both on any verdict a budget can cause, the population is every negative verdict the prover emits, and the refusal is a schema that will not accept one without them. The deeper prize named by the source is that the rewrite an agent is most likely to attempt -- changing a state encoding -- is the one this relation proves least well, so telling exhaustion from convergence is what decides whether that whole family is reachable.
    return []  # list of findings — TODO implement
