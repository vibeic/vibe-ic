# Vibe-IC Design Charter

Status: fixed by the owner on 2026-11-03. Only the owner changes this file.
It binds every program, skill, agent, review and landing in this plugin, and it
wins over any older rule, ruling or doc that conflicts with it.

## Principle

Stand on the shoulders of giants. LibreLane, OpenROAD, Yosys, KLayout, Magic,
Netgen, OpenSTA, ngspice and the other EDA tools do the engineering. Vibe-IC
gets a chip through them with the least effort and the shortest path.

## Architecture: three layers

| Layer | What it is | Who owns the verdict |
|---|---|---|
| 1. Tools | The EDA tools and their native reports | The tool |
| 2. Flow | Flow109: each step is a tool command, its native report and the original limit. LibreLane State carries data between steps. | The tool's result against the limit |
| 3. Proprietary | Only what no tool does (below) | Measured by layer 1 like everything else |

Proprietary means: natural-language requirements to L-documents, IC-expert
knowledge, analog topology and sizing, analog layout generation where no open
tool covers it, PPA improvement on top of tool results, and running the flow.
Everything else is the tools' job.

## Rules

**C1. Tool first.** Use, in this order: a LibreLane step; another tool's native
command; a fix in our fork of the tool; our own code. Our own code must name why
no tool does the job. Where LibreLane or OpenROAD defines a method, that is the
method. A stricter method needs the owner's approval.

**C2. A verdict is the tool's result against the original limit.**
- PASS: the tool ran and its native report meets the limit.
- FAIL: its native report violates the limit.
- NOT_MEASURED: the tool did not run, or left no report.
Nothing else can change a verdict. If the wrapper disagrees with a native result,
the wrapper is the bug.

**C3. Glue stays thin.** Glue around a tool runs it, reads its report and compares
the numbers. It does not rebuild what the tool knows.

**C4. No self-imposed gates.** Do not add receipts, identity or adoption records,
hash chains, provenance checks, cross-image validators, schema layers, shadow
checkers or review lanes. A new check is allowed only if it catches a real chip
defect that the tools do not check, and it must show that defect.

**C5. Subtract first.** When a wrapper blocks a tool result, delete or shrink the
wrapper. Do not add code to satisfy it. Do not change a tool result to satisfy it.

**C6. Honest numbers, unchanged limits.** Limits come from the spec, the PDK or the
owner. Never move a limit to pass. Never fabricate data. NOT_APPLICABLE needs a
contract citation. When a shortcut leaves something out, say what it leaves out.

**C7. Cost is a requirement.** Prefer the fastest method the tools accept. Do not
rerun work whose inputs did not change. A step that takes hours must change a
signoff outcome, or it does not run.

**C8. Agents do not grow the framework.** No agent, skill, ruling or brief may widen
this architecture or edit this charter. If a task seems to need that, stop and ask
the owner. Reviewers and the gatekeeper refuse a change that breaks a rule here,
and cite the rule.

## Before any change

1. Does a tool already do this? Then use the tool.
2. Does the chip need this, or only our wrapper? If only the wrapper, do not build it.
3. Can it be done by deleting something? Then delete.
4. Is this the smallest path to a native result against the original limit?

## Existing code

Older layers that break these rules are debt. No rewrite is needed. Remove a layer
when it blocks a tool result or when the code around it changes. Until then, a step
is judged on its native result, and the gap in the front door is reported, not hidden.
