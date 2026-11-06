---
name: checkpoint-gate
description: "Verify that all required artifacts exist and pass quality checks before advancing to the next phase. Triggers at Phase 1→2 and Phase 2→3 transitions. Use when: 'ready to proceed', 'check if we can move on', 'checkpoint', 'sign off', or at the end of each phase. Use the native tool results and original requirements to review the transition."
---

# Review a phase transition

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Before moving to the next selected row, confirm that the native artifacts it
needs were produced by the preceding tools. Use the current step table and
resolved configuration to find the actual paths.

- From documents to RTL, review the source requirements and the generated
  ports, clocks, resets, register behavior and verification scenarios.
- From RTL to physical design, review lint, simulation, synthesis, formal and
  equivalence results for the selected scope, including any unmeasured item.
- For physical signoff, read the native DRC, LVS, STA, IR/EM, antenna and density
  results against their original spec or PDK limits.
- For FPGA delivery, review the native Quartus compile, fit and timing reports,
  the produced programming file, and any requested hardware measurement.

File presence alone does not establish a result. State the scope of every
waiver or unavailable measurement. Fix a native failure or explain its actual
engineering impact before reporting completion. Do not create a second
transition gate, provenance ledger or layout-migration requirement.
