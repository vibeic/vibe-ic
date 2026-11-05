---
name: field-agent-loop
description: "Exercise the public flow on requested real design inputs, reproduce general defects, and verify fixes on native tool results."
---

# Field agent loop

Read `CHARTER.md` and `agents/field-agent.md`. Work through the input set and
scope supplied by the owner. Use the normal public runner and the unchanged
Router rather than a design-specific shortcut.

## Run, inspect, and resolve

1. Run the requested design documents through `vibe_ic_one_shot_runner.py` and `flow/steps.json`.
2. Inspect every native tool report. Confirm the intended input, original limit, physical plausibility, and missing measurements.
3. Trace each discrepancy to the first producer or consumer that went wrong. Fix the design, local tool fork, or plugin as the task permits.
4. Run the actual affected behavior and relevant tests again. A changed report alone does not prove that the tool ran.
5. Keep the input, command, native report, finding, and fix evidence outside the plugin repository.
6. Recheck any claimed fix against its real consumer, then continue until the requested work is complete.

For Phase 1, verify that admitted source facts reach the fields their consumers
read. A token found anywhere in the document set does not prove that the
correct layer carries it. For later phases, verify the native tool's actual
output rather than another summary of that output.

## Preserve engineering meaning

Use `ic-expert-agent`, the expert DB, and the applicable design skills. Fix
root causes across the affected layers without copying one design's values
into general control logic. Do not add a permanent policy checker for each
incident. Keep original numeric limits and report any unmeasured obligation.

For open benchmarks, use `benchmark_dispatch.py`. Keep Program First,
independent blind AI review and backup, and official scoring. Each actor sees
only the visible design input needed for its task. The author and reviewer do
not read hidden oracle, harness, or golden contents.

Use the current task's authorization for external reports, messages, fixes,
commits, and landing. If an external dependency prevents progress, report the
specific missing input and continue independent work. A local note is enough
unless the task authorizes publishing it elsewhere.
