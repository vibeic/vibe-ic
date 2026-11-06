---
name: spec-validator
description: "Cross-check Datasheet, Application Note, and Spec for consistency. Detects pin name mismatches, register address conflicts, and unresolved TBD values. Also runs auto-quality scoring on DS (0-100) and AN (0-80). Triggers when: 'check consistency', 'validate docs', 'cross-check DS and AN', 'are the docs consistent', 'run spec validator', or before Checkpoint 1 gate. This is an automated pre-gate check — run before every Phase 1 to Phase 2 transition."
---

# Review specification consistency

Read the datasheet, application note and specification as the design inputs.
Compare their facts where the generated documents and RTL consumers use them.

- Match pin names, directions, widths and voltage domains.
- Compare register addresses, field widths, reset values and access behavior.
- Compare clock rates, timing units, protocol encoding and latency.
- Resolve contradictory limits, absent requirements and undocumented defaults.
- Check that examples exercise the stated normal, boundary and error cases.

Keep original source and PDK limits. Report the conflicting facts with their
source locations rather than resolving them through a quality score. When RTL
exists, run the normal native lint, simulation, formal or equivalence task for
the concrete requirement. An absent execution result is `NOT_MEASURED`.

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```
