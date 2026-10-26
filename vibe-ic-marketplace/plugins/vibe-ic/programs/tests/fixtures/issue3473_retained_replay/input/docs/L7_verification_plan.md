# Verification plan

The bounded functional denominator contains exactly five named scenarios:

| Test case | Stimulus | Expected result |
| --- | --- | --- |
| `random_multiplication_functional_equivalence` | At least 10,000 deterministic pseudo-random unsigned operand pairs. | Every emitted bit matches the unsigned multiplication oracle; 100% pass. |
| `corner_operand` | Zero, one, maximum value, alternating bits, and one-hot operand corners. | Every emitted bit matches the oracle; 100% pass. |
| `case_3` | Consecutive transactions without an idle gap. | State sequencing remains correct and every product matches; 100% pass. |
| `reset` | Assert synchronous active-high reset before work and during arithmetic work. | All state and `p` clear on the next rising edge; subsequent multiplication restarts correctly; 100% pass. |
| `toggle_branch_coverage` | Deterministic operands that exercise arithmetic and reset decisions. | Native line, branch, and toggle coverage are measured and reported without inventing a threshold. |

## Required verification milestones

| Type | Milestone | Resolution | Note |
| --- | --- | --- | --- |
| Functional verification | `RANDOM_MULTIPLICATION_FUNCTIONAL_EQUIVALENCE` | Required | At least 10,000 deterministic operand pairs must match the unsigned multiplication oracle. |
| Functional verification | `CORNER_OPERAND` | Required | Zero, one, maximum, alternating-bit, and one-hot operands are required. |
| Functional verification | `CASE_3` | Required | Consecutive transactions without an idle gap are required. |
| Functional verification | `RESET` | Required | Reset before and during arithmetic work, followed by a correct restart, is required. |
| Coverage measurement | `TOGGLE_BRANCH_COVERAGE` | Required | Native line, branch, and toggle coverage must be measured and reported; no threshold is declared. |
| Verification method | `REAL_DUT_BEHAVIOR_EXECUTION` | Required | The testbench must instantiate the emitted `spm` RTL and compare behavior, not search source text. |
| Evidence policy | `CURRENT_AI_EVIDENCE_REQUIRED` | Required | Missing scenario declarations, missing native execution, or missing current AI evidence are not PASS. |

The testbench must instantiate the emitted `spm` RTL and compare behavior, not
search source text.  Missing scenario declarations, missing native execution,
or missing current AI evidence are not PASS.  This replay covers Steps 1 through
4 only and makes no downstream physical or whole-IC claim.
