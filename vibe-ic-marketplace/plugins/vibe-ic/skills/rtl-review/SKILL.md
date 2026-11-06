---
name: rtl-review
description: Audit RTL code for lint violations, synthesis hazards, coding-style compliance, and readability. Use when the user says "review this Verilog", "check my RTL", "lint this module", "is this code synthesizable", or shares an HDL file and asks for feedback before simulation or tape-in.
---

# Review RTL

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Run the normal selected RTL validation window first. Read the native Verilator
or Yosys diagnostics and the existing `rtl_hygiene_lint.py` findings. Preserve
the actual top, source files, include paths, defines and parameters.

Review synthesis hazards, resets and clock domains, style that changes
semantics, arithmetic widths and signedness, control correctness, and port
fidelity against the input. Inspect the design's encoding, CRC/bit order and
counter behavior when the source specification requires those features.

Report each finding with its source location, native evidence where available,
and the requirement it violates. Distinguish a confirmed defect from a
hypothesis. For a semantic rejection, write a prompt-derived executable test
before repair. Rerun the appropriate native lint, simulation or formal tool on
the fix. Preserve ECO spare cells and their keep attributes.

A numerical review score, identity receipt or signature is not a tool result.
Do not add one to decide whether RTL passes.

## Error-flag site classification — recoverable vs fatal (#468)

Review every error-flag assignment site (an `error <= 1`, `err_o = 1'b1`,
`status[ERR] <= 1`, etc. raised on an undefined-access / illegal-command /
out-of-range path). RTL structure alone does not establish whether that error
is *recoverable* (the FSM keeps serving subsequent transactions) or *fatal* (the FSM halts / needs reset
to clear). That halt-vs-continue semantic lives in the **protocol prose** of L3
(external interface / transaction protocol) and L5 (ADI / error-handling spec), not
in the netlist topology — so it is the residual LLM judgment for this skill.

**Procedure** (per error-flag assignment site):

1. Read the L3/L5 sentences that describe what the protocol does *after* this error
   condition is signalled.
2. Classify:
   - **recoverable** — the error flag is set on the undefined-access (or
     illegal-command / out-of-range) path AND the FSM **continues serving the next
     transaction** per L3/L5 (e.g. "an unsupported command sets the error bit and
     the slave returns to IDLE ready for the next frame"). Add the annotation
     `// fsm_error: recoverable` at the assignment site.
   - **fatal** — the error flag binds to a **halt / lockup state**, or L3/L5 says it
     **requires a reset (or explicit clear sequence) to clear** before any further
     transaction is served. Verify the halt/reset behavior and document the
     requirement.
3. In the review prose, **quote the exact L3/L5 sentence(s)** that justify the
   classification.

4. Derive an executable challenge from the provided prompt and L3/L5: trigger
   the error, then offer the next legal transaction. Check specified recovery
   or persistent halt until the required reset/clear. Review the actual native
   simulation or formal result against that requirement. Missing native
   evidence is `NOT_MEASURED`; hygiene lint does not prove this semantic behavior.

**FORBIDDEN:** dismissing an error-recovery or fatal-state concern *without*
quoting the L3/L5 sentence(s) that establish recoverable-vs-fatal. An unquoted
"this is fine, it's recoverable" is an honesty-rule violation — the annotation must
be backed by protocol text, not by an unsupported assertion.

**why_not_bucket_a (cannot be a deterministic rule):** the halt-vs-continue
judgment requires reading the protocol's error-handling semantics in L3/L5 prose; whether the FSM resumes or
locks up is a property of the *spec's intent*, not of the RTL's `case`/state
structure (the same `error <= 1` line is recoverable in one protocol and fatal in
another). No regex over the RTL can decide it; it needs the L3/L5 sentence.

**Why this is GENERAL:** every command/transaction-driven protocol with an
error-flag has an undefined-access path; recoverable-vs-fatal is a universal axis of
error-handling specs. It names no chip and depends only on generic L3/L5 protocol
prose + the gate's structural flag.
## Review reset intent

A constant-arm data mux is a possible reset implementation, not proof of an
architectural reset. Read the source reset requirement and the actual RTL
branch/selector before interpreting a native CDC/RDC finding. Distinguish
synchronous reset, functional update and unresolved intent. A signal name,
constant value or absent document alone does not establish reset intent.

Verify the source-required behavior with native simulation or formal results.
Keep conflicting or insufficient intent unresolved, and never fabricate a
source requirement or change rule severity to clear a finding.
