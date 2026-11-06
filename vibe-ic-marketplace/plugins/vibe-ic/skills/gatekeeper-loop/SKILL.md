---
name: gatekeeper-loop
description: "Review requested changes against native results and original limits, then use the owner's current landing workflow."
---

# Gatekeeper loop

Read `CHARTER.md` and `agents/gatekeeper-agent.md`. Review only the changes
requested by the current task. The owner controls landing and any standing work
queue. This skill creates no additional publishing or messaging authority.

## Review the actual result

1. Read the diff, the reported failure, and the input the affected tools consumed.
2. Confirm that each claimed measurement came from an executed native tool and its real report.
3. Compare native numbers with the original spec, PDK, or owner limit. Keep failed and unmeasured work open.
4. Inspect the fix for a general cause, unintended scope changes, and loss of actual tool functionality.
5. Check relevant tests and public-entry evidence on the current tree. Preserve the Router's bounded task window.
6. Hand the reviewed result to the owner or perform the already-authorized landing action through the owner's process.

For IC work, preserve the expert DB and design craft, analog and mixed-signal
programs, FPGA steps, and the MCP tools. For benchmarks, preserve Program First,
independent blind AI review and backup, clean-room actor environments, and the
official scorer. Do not read hidden oracle, harness, or golden contents.

## Landing and reporting

Use `~/claude-leader/land_one.sh` according to its actual instructions. Retain
`gen_program_inventory.py`, `nda_diff_scan_check.py`, and
`tools/release/assign_version.py`. Do not introduce another merge queue,
receipt, identity, qualification, or approval layer.

Report the changed behavior, actual native result, test scope, and anything
still unmeasured. Report step names and positions from the run's current step
table. Keep all run outputs outside the plugin repository. An owner hold stays
in force until the owner changes it.
