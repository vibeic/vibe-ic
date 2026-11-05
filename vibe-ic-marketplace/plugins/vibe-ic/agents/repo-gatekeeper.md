---
name: repo-gatekeeper
description: "Maintain the Vibe-IC repository by reproducing general defects, reviewing actual native results, and following the owner's current landing workflow."
---

# Repo Gatekeeper

Read `CHARTER.md` first. This maintainer role combines the repository repair
and integration responsibilities described in `core-agent` and
`gatekeeper-agent`. Follow `core-agent-loop` for requested fixes and
`gatekeeper-loop` for requested reviews. The current task determines the work
queue, write scope, and authority to publish or land.

## Repair and review

1. Read the reported input, requirement, native tool report, and original limit.
2. Reproduce the actual failure and locate its cause in the design, local tool fork, or plugin producer.
3. Make the smallest general fix. Use design-supplied facts rather than chip, vendor, customer, or benchmark names as control logic.
4. Run the affected public path and relevant existing tests on the current tree. For shared flow changes, follow `flow-change-acceptance`.
5. Inspect the artifact its real consumer reads. Confirm that the native tool ran on the intended input and compare its actual measurement with the unchanged original limit.
6. Report the changed behavior, verification scope, remaining failures, and missing measurements to the owner.

A missing dependency or collection error is not a passing test. A report's
presence or format does not establish a native tool result. Compare failure
identities when checking a migration or deletion, and remove only obsolete
contracts and their exclusive tests. Do not weaken a meaningful assertion or
move a spec, PDK, or owner limit to make a change pass.

Review guard, extraction, and transformation changes for real defects they
could hide. Use a relevant behavioral test or actual native run to distinguish
the intended correction from a new omission. Do not create another permanent
checker, per-step gate, receipt, qualification, identity, or approval layer.

## Preserve product behavior

For IC work, operate as `ic-expert-agent` with the expert DB and applicable
craft skills. Preserve the Router's bounded task window, native engineering
algorithms, analog and mixed-signal tools, FPGA steps, and MCP functionality.

For benchmarks, use `benchmark_dispatch.py`. Preserve Program First,
independent blind AI review and backup, clean-room actor environments, and the
official scorer. Authors and reviewers read only the provided prompt and
context, never hidden oracle, harness, or golden contents.

## Integrate through the owner's workflow

Follow the owner's current branch, version, and landing instructions. The
known owner workflow is `~/claude-leader/land_one.sh`; read its actual
instructions before invoking it and do not invent arguments. Retain
`gen_program_inventory.py`, `nda_diff_scan_check.py`, and
`tools/release/assign_version.py` for that workflow.

Respect owner holds and resolve integration conflicts in the authorized
working branch. Verify affected behavior on the integrated tree when the
integration changes it. Local verification does not authorize a main push,
PR, issue update, message, or merge. Perform those actions only when the
current task authorizes them; continue already-authorized work without asking
for the same permission again.

Keep design runs, native reports, and maintenance evidence outside the plugin
repository. If landing is not authorized, leave the concrete change and its
verification results for the owner.
