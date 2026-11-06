---
name: core-agent-loop
description: "Repeatedly reproduce and fix general plugin or MCP defects, verify native behavior, and follow the owner's landing workflow."
---

# Core agent loop

Read `CHARTER.md` and `agents/core-agent.md`. Use the work queue or defect set
provided by the current task. This skill does not authorize additional
messages, issue updates, PRs, or pushes.

## Resolve each defect

1. Read the reported input and expected behavior. Reproduce the actual failure before changing the producer.
2. Follow the native tool result to determine whether the fix belongs in the design, local tool fork, or plugin.
3. Make one general change that removes the cause. Prefer deleting a blocking wrapper over adding machinery to satisfy it.
4. Run the affected public entry and relevant existing tests. Keep the original numeric limits.
5. Record the actual result, changed behavior, tests, and remaining gaps outside the plugin repository.
6. Continue with the next requested item. Stop when the requested work is complete or when a concrete external dependency prevents further progress.

A useful regression test asserts behavior visible to the consumer. An import
error, an absent test module, or a missing tool is not proof that the original
bug was reproduced. For shared flow changes, use `flow-change-acceptance`.

For IC work, use `ic-expert-agent`, the expert DB, and relevant craft skills.
For benchmarks, preserve Program First, independent blind AI review and backup,
and the official scorer. Authoring and review use only visible design input.

## Hand off for landing

Use the owner's current branch instructions and landing process. The known
process is `~/claude-leader/land_one.sh`, with `gen_program_inventory.py`,
`nda_diff_scan_check.py`, and `tools/release/assign_version.py`. Read the actual
workflow before invoking it and do not invent its arguments.

A passing local test is evidence about that test, not permission to land.
Respect owner holds. If landing is not authorized, leave a concrete, reviewable
change and its verification result for the owner.
