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
2. Complete the mandatory IC Expert track before crediting D1:
   - Read `<project>/reports/audit/phase1/expert_parse_track.json`.
   - If `ai_subtrack.status` is `HANDOFF_EMITTED`, use the host's Agent/subagent
     tool to dispatch the exact `subagent_type` declared in
     `<project>/reports/audit/phase1/expert_parse_track_pack/ic_expert_agent_handoff.json`.
     Give that agent the handoff JSON; it must read only the pack's declared
     `design_input.txt` plus expert digests and write the declared
     `l_doc_expectations.json` answer target. Do not hand-author a substitute.
   - Re-run the same `phase1_one_shot_runner.py` command after the agent returns.
     Continue this dispatch-and-rerun loop for a schema refusal; stop on an
     execution error. `HANDOFF_EMITTED`, `ANSWER_SCHEMA_MISMATCH`, `ERROR`, or
     `CONSUMED_EMPTY` is `INCOMPLETE`, never a Phase-1 pass.
   - Credit the track only when `ai_subtrack.status == CONSUMED`,
     `ai_convergence.consumed >= 1`, and both `denominator.ai` and
     `denominator.total` are non-zero. Preserve and report every named
     disagreement; findings are advisory, answer consumption is mandatory.
3. For each remaining `FAIL` or `WAIVED` step:
   - Capture the corresponding stderr / log and **mark** the root cause
   - If close-loop patching is needed (e.g. user did not provide `input/phase1_structured.yaml`), **proactively guide** the user via dialogue (IC Expert Agent, plain-language register) to fill in the missing info, write the dialogue result into `input/phase1_structured.yaml`, and re-run the runner
4. Once all PASS, print the verdict + L doc path list, and hint the next step: `/phase2`

**Helper skills (do not auto-expand; surface only when the user asks):**
- `phase1` — natural-language → L1-L27 dialogue flow
- `spec-review` — human review after L1-L27 emit

**Phase 1 not PASS means cannot enter Phase 2** — strictly depends on generated_docs/L*.json.
