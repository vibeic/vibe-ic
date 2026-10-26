---
name: vibe-ic-all
description: Enter a bounded current Flow109 window through the sole public vibe_ic_one_shot_runner entry in Default mode. AI-monitored + close-loop.
argument-hint: <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id> [--top-name <top>] [--pdk <pdk>]
---
**First: IC path or IP path?** Read [IC Expert § 0.0](../agents/ic-expert-agent.md) before Phase 1. Use the prompt's route or ask the operator if unclear; record the owner answer in `input/step_0_5ic_answers.json`. Pass `--route ic` or `--route ip` when stating it on this command.

> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-all <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id>`.
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-all — the public Flow109 entry

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS \
  --flow 109 --execution-mode default
```

`$ARGUMENTS` must contain the explicit manifest and inclusive Flow109 stable-ID
window. The public runner resolves those IDs from `flow/flow109.json`, records
the request, and dispatches only its registered Default owner. It does not
silently select a former flow or translate a former numeric entry.

| Current responsibility | Flow109 ID | Position |
|---|---:|---:|
| RTL authoring | D09 | 17 |
| RTL validation and lint | D11 | 19 |
| Functional simulation and coverage | D13 | 21 |
| Synthesis | D22 | 34 |
| DFT architecture and insertion | D23 | 35 |
| Netlist handoff | D30 | 42 |
| Path-delay ATPG | D50 | 72 |

D50 currently has no registered dispatch. Requesting it must refuse before
native work; it is not an invitation to invoke another path-ATPG command.

**Halt rule:** the first selected row that is FAIL or NOT_MEASURED stops later
rows in that request. A row not executed after the stop must remain explicitly
not executed; it is not skipped-PASS.

Do not express scope with phase skip aliases. Select the exact current rows with
`--entry-step <ID> --exit-step <ID>` and retain the resulting Flow109 request,
attempt, component and consumer receipts.

After the run completes, the AI must:

1. Read the immutable request and attempt under
   `<project>/reports/flow109/` and each selected component result.
2. Confirm the saved request binds the exact registry/planner, manifest,
   stable-ID window, route and Default execution.
3. Preserve `PASS`, `FAIL`, `NOT_MEASURED` and not-executed states per row.
4. A component or window PASS does not mean the whole flow is complete.

**Purpose:** one command reaches the unique current public entry. A bounded
window establishes only its measured rows; it does not self-assert full-flow or
silicon-ready acceptance.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30, span Phase 1→2→Analog→3)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` / `phase3/mixed_signal/**` / `phase2/stage1/fpga/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step / phase ⇒ verdict FAIL; (5) `final_summary.md` must include the SHA256 table of every canonical artefact across the flow (L1-L27 / SOF / GDS / netlist / LEF / Liberty / each sign-off report). Full version: `commands/_anti_fabrication_rules.md`.
