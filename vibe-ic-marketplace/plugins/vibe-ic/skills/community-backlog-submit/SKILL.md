---
name: community-backlog-submit
description: "Prepare a general, de-identified report of an observed plugin or MCP defect, and submit it only when the current task authorizes publication."
---

# Community backlog report

Read `CHARTER.md`. Record a general capability gap encountered in the current
design session. A useful report explains the observed defect, its cause, and
where a correction belongs. This skill grants no authority to create an issue,
message others, publish data, open a PR, push, or land a change.

## Establish the finding

1. Preserve the visible input, exact command, native report, original limit, and observed failure outside the plugin repository.
2. Identify the failed requirement and the producer or consumer responsible for it.
3. Distinguish a design error, a local native-tool defect, and a plugin or MCP defect. Fix the responsible one when the current task authorizes a fix.
4. Verify a correction through the actual affected behavior and relevant existing tests. Do not change an engineering limit or add a permanent policy checker merely to record the incident.
5. Explain the general input pattern and wrong outcome so another design can reproduce the same class of defect.

Preserve the applicable IC Expert knowledge and craft. A reusable lesson can
belong in an existing expert skill; a deterministic producer or tool defect
belongs in that producer or local tool fork. Do not convert every design bug
into a demand for another gate. Do not fabricate a general gap from a single
design's name or an expected hidden answer.

## Prepare the authorized report

Use the current task's requested format and location. Keep a local report and
its evidence outside the plugin repository unless the task explicitly asks
for repository content. Include:

- The measured plugin version, read from `.claude-plugin/plugin.json`.
- A concise title and the affected existing component: program, skill, MCP tool, or flow stable ID.
- The general input pattern, failed requirement, observed result, and expected behavior.
- A minimal reproducible input or command, native evidence, and the original engineering limit.
- The responsible producer or consumer, proposed correction, actual verification result, and remaining measurement gaps.

When a cited run directory can change, preserve a copy of the relevant input
and report with the local finding. Distinguish the captured evidence from a
later rerun. A copied artifact proves only what that artifact actually records;
it does not create a receipt, admission requirement, or signoff verdict.

Remove identifying design and customer data, proprietary source text and
register maps, vendor-specific filenames, private paths, device identifiers,
and secrets from anything intended for external publication. Never include
API keys, tokens, passwords, cookies, private keys, or complete authenticated
commands. Preserve only the general behavior and non-sensitive evidence needed
to reproduce the defect. Review the report itself; no sanitizer or body-lint
program substitutes for understanding what it discloses.

For benchmarks, preserve Program First, independent blind AI review and backup,
and the official scorer. Authors and reviewers read only the provided prompt
and context, never hidden oracle, harness, or golden contents.

## Deliver within the current authorization

If the current task authorizes filing an issue or another external report,
submit the reviewed, de-identified content through that authorized channel and
record its resulting location. Do not request the same permission again when
it has already been granted. Otherwise, leave the concrete local report for
the owner; do not send or file it.

Keep fixes and their verification separate from a report's publication status.
A filed issue is not a verified fix, and a local report does not authorize a
repository commit, main push, or landing. Follow the owner's current workflow
for any such action.
