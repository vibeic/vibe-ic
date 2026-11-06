---
name: vibe-ic-phase2
description: Run frontend steps through the Router-selected native step table and review every tool result.
argument-hint: <project-dir> [--route ic|ip] [--entry-step <id> --exit-step <id>] [--pdk <pdk>]
---

# /vibe-ic-phase2

Read `CHARTER.md` and `agents/ic-expert-agent.md` before running. Design documents are the input. For physical delivery, use the owner's stated IC or IP route. For bounded RTL work, `task_nature_route` determines the entry and evidence exit without a packaging question.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS
```

The public entry always runs `flow_engine.py` with `flow/steps.json`. The Router controls the inclusive entry and exit window. An explicit window requires both `--entry-step` and `--exit-step`. Use `--from <step-name>` and `--to <step-name>` only to narrow that window. The phase entry programs use this same engine.

After each tool finishes, read its native report and `<project>/steps/<step-name>/result.json`. Confirm the tool ran on the intended design, read its native measurement, and compare it with the original spec or PDK limit. Review missing measurements and physical plausibility. Keep `PASS`, `FAIL`, and `NOT_MEASURED` distinct. A selected window does not establish whole-chip signoff.

If the Program requests `spec-to-rtl`, complete the declared AI handoff from the visible documents, then rerun this public entry. For lint, synthesis, timing, DRC, LVS, IR-drop, analog, or FPGA problems, use the corresponding expert skill and fix the design, local tool fork, or plugin. Keep numeric limits unchanged.

Report the step name and its 1-based position in the run's complete `flow/steps.json` table. Historical execution IDs remain internal. Save run results outside the plugin repository.
