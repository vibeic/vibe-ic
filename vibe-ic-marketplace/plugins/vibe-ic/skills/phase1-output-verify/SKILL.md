---
name: phase1-output-verify
description: After phase1_one_shot_runner emits 13 L*.json, AI spot-checks completeness and source meaning. Triggers on phrases like "verify L docs", "check phase 1 output", "confirm extraction is correct", or automatically when /vibe-ic-phase1 / /vibe-ic-phase2 returns PASS.
tier: verification
paired_program: phase1_one_shot_runner.py
---

# Review Phase 1 output

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

Compare the admitted source documents with the generated fields where their
actual consumers read them. Review the following independently.

1. Required facts are present in their owning layers. A copied token in an
   unrelated field does not close a missing requirement.
2. Port names, widths, directions, clocks and resets agree across the source,
   integration documents and verification plan.
3. Register addresses, OTP data, opcode sets and error/default behavior retain
   the source meaning, units and bounds.
4. Analog blocks, physical constraints and unavailable implementations are
   explicitly represented when the input requires them.
5. Placeholders, unsupported assumptions and open questions are disclosed.

Read representative source passages and their exact generated counterparts.
When a field is absent or wrong, repair the owning extractor or document and
rerun that generation step. Keep a concise report of the discrepancy, fix and
remaining scope. Use `phase1-completeness-deep-review` for semantic ownership
and completeness. Do not qualify content through a receipt or schema score.
