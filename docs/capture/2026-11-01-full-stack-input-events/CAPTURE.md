# Schedule real input events before connectivity checks

## Result

Bucket A, AUGMENT-EXISTING: the generic full-stack TB producer now schedules
real ordinary-data transitions when no DUT clock resolves. The transitions
occur after the existing reset sequence, restore the initial zero values and
settle through the existing run delay before the unchanged output checks.

The exact-base/candidate matrix has 32 matched IDs: base 3 FAIL / 29 PASS;
candidate and restored producer 32 PASS, zero introduced failures. Evidence is
source-only product generation plus host immutable Icarus execution. Native
container, canonical benchmark and full-suite acceptance are NOT_RUN.

## Source identity and ownership

- Initial exact main: `ad881e06d943791b8c0cd1cf8d7bcfbbebc69701`.
- Refreshed exact main: `b0f565e677f154700abbc53054a98a0599e63244`.
- Branch: `capture/comb-tb-input-event1101`.
- Owning producer: `programs/design_one_shot_runner.py::step_full_stack_tb_gen`.
- Existing contracts reused: reconciled DUT inputs, resolved clock/reset roles,
  generated skeleton ownership and the existing connectivity transcript reader.
- Capture routing: `phase2.full_stack_tb.input_events`.

The installed plugin, active benchmark artifacts, professional expert hooks and
previous published capture checkouts/branches/packets were not changed. Only the
supplied diagnostic summaries were read; no referenced campaign candidate/TB,
private prompt or official dataset artifact was opened. Reproduction uses new
neutral ordinary RTL projects.

## Reproduction before editing

The actual producer generated a TB for valid scalar and vector combinational
`always @(*)` modules. Their input regs were initialized only in declarations;
the generated clock/reset affected TB-local regs, so no DUT data event occurred
after time zero. Both compiled and ran to DONE, but their outputs remained X:
`FULL_STACK_TB_CHECKS pass=0 fail=1`. The existing connectivity reader refused
the transcript. A mixed module with one valid output and one truly undriven
output reported pass=0/fail=2. Active-high/active-low clocked controls passed.

Those three wrong values were preserved before product edits and graded by
`control_substance_check` as 3/3 substantive failures. DUT RTL bytes remain
unchanged through every generation and simulation.

## Bounded producer change

Thirteen added lines use the producer's existing ordinary-input and clock/reset
role lists. Only the no-resolved-DUT-clock path gets the settling events; DUT
reset and TB-local clock/reset regs are excluded. Each eligible reg starts at
zero, complements at a separate positive time, and complements again to restore
zero. This is connectivity preparation, not a functional reference model.

No output declaration, check, counter, threshold or connectivity-reader rule is
modified. The existing post-reset run delay settles the restored data before
checks. Supported clocked DUTs emit exactly the same TB bytes and keep their
existing clock/reset sequencing. Author-enhanced TB preservation is unchanged.

## Verification and receipts

Packet: `/home/reyerchu/codex_tasks/out/comb-tb-event-capture1101/`.

| Receipt | Evidence |
| --- | --- |
| `red.xml`, `red-substance.log` | Actual generator/Icarus/connectivity-reader refusal; 3/3 value-bearing failures |
| `base.xml`, `candidate.xml`, `comparison.json` | Same 32 IDs: 3 improved, 29 unchanged PASS, zero regressions |
| `reverse.xml`, `reverse-substance.log` | Keep both delays but reassign zero to zero: all three wrong values return, 3/3 substantive |
| `restored.xml` | Restore exact candidate producer: 32/32 PASS |
| `parity.json`, `analyze_receipts.py` | Real VCD input events; unchanged output checks; byte-identical clocked TBs |
| `source-guard.json`, `entry-guard.json`, `doctrine.json` | Source, entry-surface and convergence-doctrine checks PASS |
| `routing.xml`, `enhancement-emit.log`, `capture-compliance.log` | Six routing tests, capture emission and skill compliance PASS |

VCDs record zero-to-all-ones at 201000 ps and back to zero at 202000 ps for
the ordinary scalar/vector inputs. They contain no corresponding positive-time
data changes on base. The mixed negative still reports the genuinely undriven
output as `CHECK FAIL`, pass=1/fail=1, and the connectivity reader still refuses
it. The valid sibling output now resolves. Both clocked active-high/active-low
TBs are byte-identical across arms. The existing no-clobber and output-named
clock/reset controls also pass.

All simulations use the requested immutable Icarus binaries under
`/nix/store/49sr1m6qw81ja2hzlva163qlvj5vqmnq-iverilog-12.0/bin`:
`iverilog` SHA-256
`f51a1e5f944a15d6f5f27df3983cb133135ef265ac50dfc3381622e126e2c1e8`,
`vvp` SHA-256
`1e878e13f6ccf0fc612859a958934bda9af2bb7e68e675ec078b7ed9f078306e`.

The successful record is connectivity evidence only. Professional expert-hook
authoring and functional verification retain their normal entry and gates;
this producer repair does not fill or waive those obligations.

## Next

Proceed to independent exact-source review of the sealed, versionless patch.
No commit, version assignment, push, PR or merge has been performed. Preserve
the host/source scope and native/benchmark/full-suite NOT_RUN limits.
