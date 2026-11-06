---
name: ppa-diagnose
description: Explain why a PPA number is where it is — which paths, cells, nets or flow decisions account for a timing, power or area result — starting from what the deterministic diagnosis already found and adding only falsifiable hypotheses on top. Use when the user says "why is timing failing", "where is the area going", "what is burning the power", "diagnose this PPA result", or when a closure loop needs a reason before it needs a candidate.
---

# Diagnose PPA

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Start with the measured failing metric and the original requirement. Read the
native path, cell, net, power or congestion breakdown that accounts for it.

1. For timing, separate cell delay, interconnect, logic depth, fanout and skew.
   Check constraints and I/O loading before proposing an RTL change.
2. For area, identify the dominant cells, memories, macros and unused reserve.
   Keep intentional ECO spare area separate from removable logic.
3. For power, identify activity, capacitance, voltage, leakage and the dominant
   switching structures. State any missing activity or model coverage.
4. For congestion or IR, connect the hotspot to the actual geometry, grid and
   measured demand.
5. Propose a bounded change and a falsifiable expected effect. Preserve the
   previous design, run the owning tools, and compare the same metric and scope.

Report observations separately from hypotheses. Cite source paths and native
numbers. An untested explanation remains a hypothesis. Keep original limits
and disclose tradeoffs in every other affected metric. No context receipt or
separate diagnostic authorization is required.
