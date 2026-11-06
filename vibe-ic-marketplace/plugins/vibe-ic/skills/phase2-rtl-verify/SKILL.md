---
name: phase2-rtl-verify
description: After design_one_shot_runner emits RTL + SOF + reference TB PASS, AI spot-checks RTL quality and L9-contract conformance. Triggers when /vibe-ic-phase2 / /vibe-ic-phase2 returns PASS, or on phrases like "review the RTL", "check RTL quality", "verify phase 2 output".
tier: verification
paired_program: design_one_shot_runner.py
---

# Phase 2 RTL Verification

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on residual narrative.

## Read the native verification results

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

## Review the completed verification window

Review the exact RTL and native outputs from the selected public window.
Keep design-input-only authoring and independent review. When semantic
review rejects RTL, demonstrate the issue with a source-derived executable
test before repair. Rerun the affected native tools after the fix.

## Verification checklist

1. Compare native elaborated ports, widths, directions and submodules with the
   actual L9 integration contract.
2. Check required FSM states and transitions through native simulation or
   formal coverage, including source-declared normal and error behavior.
3. Read native lint and `rtl_hygiene_lint.py` diagnostics for undriven signals,
   unread state, incomplete cases, width/sign changes and unintended latches.
4. For a protocol that forbids device-generated break, verify the relevant
   transmit states and durations against the original protocol limit.
5. If self-receive masking is required, test its behavior while the device
   drives the bus. Do not infer it from a signal name.
6. Compare OTP addresses and values with the actual loaded memory image.
7. Exercise every source-declared scenario and its boundary/default behavior.
   Read the native transcript and coverage for each required case. Keep any
   missing execution explicitly unmeasured.

## Spot-check actions

- Pull a random opcode from L3.opcodes that's NOT in {0x70, 0x72, 0x74}, send via host_emulator (or scope inject), confirm chip responds with the expected response opcode.
- Diff this run's RTL vs known-good reference from a previously hardware-verified project. Identify structural deltas.

## When to escalate

- Find any Wave-34 violation → invoke the `rtl-repair` skill for the bounded
  RTL repair/retry loop (not a physical/metal ECO)
- Find L9 contract mismatch → re-run phase2 after patching aid_class_rtl_gen template
- Find dead RTL → call out to user, may be intentional or may reveal regression

## Output

Append findings to `<project>/reports/phase2_verify.md`. If all checks pass, write single-line PASS summary.
