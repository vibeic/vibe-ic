---
name: vibe-ic-phase23
description: Run one explicit current Flow109 window through the sole public entry in Default mode. AI-monitored + close-loop.
argument-hint: <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id> [--top-name <top>] [--pdk <pdk>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase23 <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id>`.
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-phase23 — bounded cross-stage Flow109 entry

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS \
  --flow 109 --execution-mode default
```

The command no longer selects a separate phase-chain route. The single public
front door resolves the explicit stable-ID window from `flow/flow109.json` and
uses only registered owners. D09/17, D11/19, D13/21, D22/34, D23/35 and D30/42
are the current frontend anchors. The window must be contiguous in the selected
plan and fully dispatchable; otherwise the request refuses before approximation.

After the run completes, the AI must (combine `/vibe-ic-phase2` + `/vibe-ic-phase3` monitoring rules):

1. Read the immutable request and attempt under `<project>/reports/flow109/`
   plus every selected component result.
2. Close-loop only the first selected row that is FAIL or NOT_MEASURED; later
   rows must remain not executed.
3. Preserve the selected rows' exact PASS/FAIL/NOT_MEASURED states; do not
   fold missing or not-executed rows into PASS.
4. A selected-row or bounded-window PASS does not mean the whole flow is
   complete.

Do not use phase skip aliases to emulate a Flow109 window. Use only the current
stable IDs and positions recorded by the registry.

**Helper skills:** same as `/vibe-ic-phase2` + `/vibe-ic-phase3`, plus `tapeout-checklist`, `flow-orchestrate`.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` / `phase3/mixed_signal/**` / `phase2/stage1/fpga/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
