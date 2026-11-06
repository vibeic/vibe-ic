---
name: ppa-measure
description: Read PPA artefacts that the tools already wrote — STA reports, power reports, area reports, DEF/GDS summaries — and turn them into an evidence-linked measurement report of canonical `vibeic.ppa.metric.v1` records, each carrying its scope and its native source path. Use when the user says "measure PPA", "what is the real area/power/timing", "collect the PPA numbers", "post-route PPA", or when a report must state what was measured AND what was not.
---

# Measure PPA

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Collect the numbers from the tool's actual outputs. Name the design, top,
stage, corner, mode, Liberty files, activity basis and parasitics used.

- Read cell area and cell counts from the synthesis or physical database.
  Distinguish cell area, macro area, core area and die area, and keep their units.
- Read setup and hold WNS, TNS, unconstrained paths and DRV from native timing
  reports. Identify whether timing used estimated or extracted parasitics.
- Read power with its voltage, process/temperature corner and switching-activity
  basis. Missing activity is a limitation, not measured design power.
- Read wirelength, via counts, congestion and physical violations from the
  native implementation reports when those measures were requested.

Write a table with each measured value, units, original requirement, result
and source path. Report an absent value as `NOT_MEASURED`. Do not replace it
with zero, an estimate, a stale report or a hash-bound claim. Explain any
reused measurement's actual scope. Review physical plausibility and state
what the run did not measure. Early estimates belong in `ppa-predict`.
