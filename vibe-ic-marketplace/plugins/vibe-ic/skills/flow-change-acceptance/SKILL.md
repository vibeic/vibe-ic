---
name: flow-change-acceptance
description: "Verify a shared flow change through its actual consumers, native tool reports and unchanged original limits before the owner lands it."
---

# Verify a flow change

Read `CHARTER.md`. A shared flow change affects every design that reaches its
consumer. Verify that behavior directly without creating another permanent
checker, receipt, identity, or approval layer.

## Establish the changed behavior

1. Identify the producer, its actual consumer, and the failed behavior.
2. Capture the current native report and original limit before changing the producer.
3. For a bug fix, replay the reported failure on the old code and the fix on the new code. Verify the substantive disagreement, not merely an import error or an absent new field.
4. Exercise representative valid inputs and the reported failure through the actual public entry. Do not plant errors or qualify the EDA tool again during an ordinary design run.
5. Confirm that the tool ran on the intended design, produced its native report, and retained the original spec, PDK, or owner limit.
6. Run relevant existing tests and inspect the actual artifact the consumer reads.

Choose verification that can distinguish the claimed behavior. A compiling
module or a report containing the expected word is insufficient when the
claim concerns synthesis, simulation, routing, timing, or signoff. A missing
measurement remains unmeasured. A native failure remains a failure until a
real fix and tool rerun meet the original limit.

## Review generality and scope

Use design-supplied data rather than design, customer, vendor, or benchmark
names as control logic. Synthetic fixtures should describe the general
failure. Preserve the Router's bounded task window and the native engineering
algorithms. Do not weaken assertions or move thresholds to make a change pass.

Source completeness is a consumer question. Check that a fact reaches the
field the consumer reads, with the same meaning and authority. Its presence
elsewhere in a document set does not establish that contract.

For a deletion or migration, verify surviving imports, actual dynamic calls,
native tool invocation, and remaining test outcomes. Remove only obsolete
contracts and their exclusive tests. Compare failure identities rather than
only totals, and distinguish a pre-existing failure from a new one.

## Hand back evidence

Report the changed behavior, native command and report, unchanged limit,
relevant tests, comparison revision, and remaining gaps. Keep run evidence
outside the plugin repository. Follow the owner's current landing process;
this skill grants no authority to publish, message others, open a PR, or land.
