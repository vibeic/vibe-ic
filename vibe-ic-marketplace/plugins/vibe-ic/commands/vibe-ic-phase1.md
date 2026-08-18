---
name: vibe-ic-phase1
description: Run Phase 1 (natural-language → L1-L27 JSON + human MD) via the deterministic phase1_one_shot_runner. AI-monitored + close-loop.
argument-hint: <project-dir> [--ic-name <name>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase1 <project-dir>` (e.g. `/vibe-ic-phase1 1st_benchmark_example/phase2_v0119.48-vendor`).
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /phase1 — Phase 1 (Path A) entry

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/phase1_one_shot_runner.py $ARGUMENTS
```

The first positional argument is the project directory (e.g. `/home/<your-user>/AI_IC_design/<project>`).

**After the program completes, the AI must:**
1. Read `<project>/reports/phase1_one_shot.json` — verdict + status / detail of every step
2. For each `FAIL` or `WAIVED` step:
   - Capture the corresponding stderr / log and **mark** the root cause
   - If close-loop patching is needed (e.g. user did not provide `input/phase1_structured.yaml`), **proactively guide** the user via dialogue (IC Expert Agent, plain-language register) to fill in the missing info, write the dialogue result into `input/phase1_structured.yaml`, and re-run the runner
3. Once all PASS, print the verdict + L doc path list, and hint the next step: `/phase2`

**Helper skills (do not auto-expand; surface only when the user asks):**
- `phase1` — natural-language → L1-L27 dialogue flow
- `spec-review` — human review after L1-L27 emit

**Phase 1 not PASS means cannot enter Phase 2** — strictly depends on generated_docs/L*.json.
