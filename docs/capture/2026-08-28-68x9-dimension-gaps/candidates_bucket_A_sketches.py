# Bucket A — program-rule sketches for programs/flow_gate_grid.py
# Corpus-sweep REQUIRED before merging into programs/flow_gate_grid.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.12.33
# Pattern: 
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_gate_dict_reaches_the_executor_check(sample_text, ports):
    """A wiring dimension that supplies its own caller can never observe a missing caller.

MEASURED (mutation probe, v1.12.33). d1's published claim is 'does something real parse and execute the gate?'. Its observation point sits INSIDE `_evaluate_gate`, and the test hands `_evaluate_gate` the gate dict itself — so the caller is supplied by the test and cannot be wrong.

MUT-A (a gate names a program with no matching file) -> RED, correctly.
MUT-B (remove what hands the executor its gate dict for step 21) -> GREEN, 86 passed, while the BEHAVIOUR is plainly broken: on a real project the step vanishes from the tally, the per-step listing and the blocker list; MISSING drops 40 -> 39 and 18 steps that were blocked-by-upstream silently unblock.

What this rule adds: for every step the flow declares a gate for, assert that some reachable caller PASSES that gate dict to the executor — the seam one level above where d1 looks. Deterministic: it is an AST reachability question over the runners, the same shape `checker_execution_wiring_audit` already answers for programs."""
    # Expected signal: ERROR
    # Suggested fix action: Walk the runners' AST for call sites that pass a step's gate to `_evaluate_gate`; a step whose gate is declared but never handed to the executor is reported by name. Pairs with d1 rather than replacing it: d1 keeps proving the walk inside the executor is complete.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.12.33
# Pattern: 
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_red_that_only_means_nothing_ran_check(sample_text, ports):
    """A non-zero exit earned on an EMPTY tree does not prove a gate can fail on a project that DID something.

MEASURED (mutation probe, v1.12.33). d2 asks 'can the gate reach a genuine non-zero exit?' and its exec rule is `if not passed: return RED` with no absence tier. 54 of the 121 reds it counted were earned on EMPTY, where the FAIL text is literally `REQUIRED_ARTEFACT_MISSING` / `MISSING_NETLIST` / `PLACED_DEF_MISSING` / 'no file on disk matches pattern' / 'absent or not valid JSON'.

MUT-M1 (a gate always exits 0) -> RED, correctly.
MUT-M2 (kill the namesake verdict, leave the absence arm alive) -> GREEN. The gate can no longer fail on anything a design DID, and d2 does not notice, because the absence arm still returns non-zero.

What this rule adds: classify each red by WHICH arm produced it. A gate whose only reachable red is an absence message has not been shown falsifiable — that is exactly the 'red that only means nothing is there' this repo already names elsewhere. Deterministic: the FAIL text is matched against the absence vocabulary the gates already emit."""
    # Expected signal: ERROR
    # Suggested fix action: Split d2's red into `ABSENCE_RED` and `VERDICT_RED` by matching the emitted FAIL message against the artefact-absence vocabulary; a clause with no `VERDICT_RED` on any arm is reported. The 54 currently counted as falsifiable are the starting population.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.12.33
# Pattern: 
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_declared_output_has_a_live_producer_check(sample_text, ports):
    """Finding a file in a committed corpus does not show that the flow still writes it.

MEASURED (mutation probe, v1.12.33). d3's claim is 'are declared `required_outputs` genuinely written?'. 122 of its 166 entries (73%) ask whether some run tree committed into `benchmark-data` still carries a non-empty HEAD-tracked file matching the glob — a question about the corpus repository's history, answered without executing one line of plugin code.

MUT-B1 (delete the WRITER of step A8's declared .gds, surgically) -> GREEN in every configuration: 15 passed / 53 skipped shipped, the same 4 and then the same 7 failures under `VIBE_IC_BENCHMARK_DATA` as the clean tree, and both of A8's dedicated guards pass individually on the mutated tree.

What this rule adds: for each declared `required_output`, assert a REACHABLE producer still writes it — the artefact->writer map, which the flow already needs for d7. Deterministic and complementary: d3 keeps proving the artefact once existed; this proves something still makes it."""
    # Expected signal: ERROR
    # Suggested fix action: Build artefact -> writer over the runners and the flow yaml, and report any `required_outputs` entry with no reachable writer. Reuse the reader/writer maps d7 already derives so the two dimensions share one source of truth.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.12.33
# Pattern: 
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_disclosure_token_is_not_a_working_gate_check(sample_text, ports):
    """Adding a disclosure word to a broken gate must not turn a red cell green.

MEASURED (mutation probe, v1.12.33). d6 promises two halves — (a) is the skip conditioned on a runtime fact, (b) is it reported at a non-PASS tier. It delivers (b) only.

M1b (a gate stops working and says nothing) -> RED, hard.
M1 (the same gate stops working and says `VACUOUS_PASS`) -> GREEN, 80 passed / 1 xfailed, identical to clean. Worse, the module's own capability census counted the mutated gate as having MORE live legs than before (L2, L3c, L6 became 'capable') while the number that actually fired stayed 0.

Behaviour on a realistic project (a `clock_plan.json` present but defining zero clocks): clean gives step 16 status=FAIL; mutated gives status=`VACUOUS_PASS` and the headline moves it out of 'executed'. The gate that exists to catch an empty clock plan stops catching it, and the matrix reads greener than before.

What this rule adds: a skip must be conditioned on a runtime fact, not merely announced. A clause whose disclosure tier rises while its fired-leg count stays zero is reported. Deterministic: both numbers are already computed by the module — the rule compares them instead of reading only the tier."""
    # Expected signal: ERROR
    # Suggested fix action: Compare disclosure tier against fired-leg count per clause: a clause that gains capability legs without gaining fired legs is flagged, so a disclosure token can never buy a green cell.
    return []  # list of findings — TODO implement
