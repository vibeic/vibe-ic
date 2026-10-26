---
name: vibe-ic-phase2
description: Run a bounded frontend Flow109 row through the sole public entry in Default mode. AI-monitored + bounded repair/retry.
argument-hint: <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D09|D11|D13|D22|D23|D30> --exit-step <same-or-supported-D-id> [--top-name <top>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase2 <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id>`.
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-phase2 — bounded Flow109 frontend entry

**Prerequisite**: the selected current Flow109 row's declared inputs must exist.
The manifest must select that row for the owner-declared IC/IP route.

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS \
  --flow 109 --execution-mode default
```

Do not call the owner runner directly. The public entry resolves the stable ID,
records the immutable Flow109 request/attempt, and then dispatches the existing
owner. Current frontend anchors are:

| Responsibility | ID | Position |
|---|---:|---:|
| RTL authoring | D09 | 17 |
| RTL validation and lint | D11 | 19 |
| Functional simulation and coverage | D13 | 21 |
| Synthesis | D22 | 34 |
| DFT architecture and insertion | D23 | 35 |
| Netlist handoff | D30 | 42 |

Use only a registry-supported inclusive window. A refusal is terminal for that
request; never retry it through a former numeric step or a direct runner.

After the run completes, the AI must:

1. Read `<project>/reports/flow109/attempts/` and the selected
   `<project>/reports/flow109/components/<D-id>.json`; preserve row-local and
   whole-flow verdicts separately.
2. If `<project>/phase2/stage1/formal/formal_authoring_request.json` exists,
   **invoke `formal-verify` now** on that artifact. This is a required fallback,
   not a suggestion in a manifest: read every unresolved L3/L6/L8 obligation ID,
   author only sound properties bound to visible RTL/declarations in
   `phase2/stage1/formal/formal_expert_properties.svh` (the fragment the
   generated harness includes; author `formal_<top>.sv` only when no harness
   was generated), update
   `property_contract.json`, write `formal_expert_review.json` with
   `invocation_status: INVOKED` and a `dispositions` list containing one row
   per obligation (`id`, `status`, and the exact `property` name for every
   `AUTHORED` row), then run
   `formal_property_run.py` and `formal_proof_evidence_check.py`, and sign
   `reports/audit/ai_judgements/5.json` over the resulting evidence (it binds
   the fragment and the harness). If no sound
   property can be authored, keep the request `verdict: INCOMPLETE` and name the
   missing declaration/property; never replace it with a skip.
3. For every FAIL step:
   - **`rtl_gen`** FAIL → check `aid_class_rtl_gen.py` stderr; usually L8/L9 fields missing → return to `/phase1` to fill in
   - **`reference_tb`** FAIL → iverilog parse / sim error; bounded RTL repair/retry loop (runner auto-retries up to 3 times); if retries are exhausted, modify `aid_class_rtl_gen.py` template
   - **`fpga_compile`** FAIL → check `fpga/compile.log`; common: QSF init_file SEARCH_PATH, SystemVerilog patterns Quartus does not accept → fix RTL template / qsf_gen
   - **`fpga_burn`** FAIL → parse `error_code` and `failed_gates` (pre-burn structural-gate audit); close-loop each gate (call `programs/<gate>.py` to capture detail → patch RTL/L doc → re-run)
   - **`md905_verify`** FAIL → `<unparsed>` = driver did not see frame; first verify the SOF was burned in + <half-duplex-tester> connected to PIN_V10; if `expected ≠ observed` it is a real hardware bug and requires RTL repair (not a metal-layer ECO)
4. A selected-row PASS permits only the next dependency-valid Flow109 request;
   it does not imply frontend or whole-flow PASS.

**Helper skills:** `spec-to-rtl` / `cdc-check` / `rtl-review` / `formal-verify` / `bringup-plan`

**Rule:** the selected Flow109 attempt and every selected component must be
current and terminal. A row-local PASS is never promoted to phase or whole-flow
PASS by this command.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase2/stage1/fpga/**` / `phase3/stage4/**` / `phase3/mixed_signal/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
