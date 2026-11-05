---
name: tapeout-checklist
description: Review native DRC, LVS, STA, IR-drop, EM, antenna, ERC, LEC, DFT coverage and release evidence against original requirements before an authorized GDS handoff.
---

# Tapeout Checklist

Review every applicable native tool result before a GDS handoff. Read
`<project>/reports/flow_engine.json` produced by the normal public runner;
`flow/steps.json` supplies the current row positions and names. The Router's
selected window runs through the sole engine path. Do not introduce another
execution or approval layer.

For each selected row, open the native files named in `reports` and inspect
`tool_ran`, `native_steps`, `native_metrics`, and the value/operator/original
limit in `metrics`. Confirm the intended design, corner and tool actually ran.
AI review each native result for physical plausibility, missing coverage and
engineering risk, retaining the existing per-row review and its measured
duration. Missing native data or an absent original limit is `NOT_MEASURED`;
it cannot be turned into PASS by an archive, report format or summary.

Keep spec, PDK and owner limits unchanged. Failed, deferred or unmeasured work
remains open. Record any owner-accepted engineering exception with its actual
scope and risk; an exception does not make the unexecuted measurement pass.

## Portable design-release archive

The existing packaging producer writes `release_manifest.json`, `SHA256SUMS`
and a relative `archive/` tree. The manifest separates final-GDS design
material, retained internal STA/SDC/SPEF and logic/electrical closure, external
PDK/tool dependencies, and the provider upload subset. A file's presence does
not qualify its signoff: existing producer readers must measure the selected
final-GDS subject, and incomplete or failed measurements remain incomplete.
Manufacturing-service `PENDING_FOUNDRY_*` fields are not seven universal gates.

For a new version without changing the source project:

```bash
python3 programs/foundry_handoff_pack_gen.py <project> --out-dir <new-version-dir>
python3 programs/foundry_handoff_package_check.py <new-version-dir> \
  --package-dir <new-version-dir> --json <check-output.json>
```

`--out-dir` must not already exist; old versions are retained. A provider die
assembly is selected only through its producer-owned `--release-record` and
`die_finishing_gen.read_admitted_release`, never an arbitrary GDS override.
Use the packaging checker's existing `--design-release` mode when checking
technical release completion; its compatibility mode reports `LEGACY_SKELETON`.
A relocated check validates the retained archive; it does not
rerun EDA or claim provider submission/order acceptance. Slot, CoB and IDs
must come from the actual selected provider inputs and current precheck.

## Read the actual measurements

Use the selected native tool results for SPEF parasitic extraction, post-route
MCMM STA, IR/EM/antenna/SI, post-layout gate simulation, SPICE correlation,
ECO, metal fill, FPGA final recompile, and analog work when applicable. A
smaller subset of successful reports cannot establish completion of those
obligations. For static IR-drop, keep the actual declared budget; the existing
budget reader can inspect the native report without moving that budget:

```bash
python3 plugins/vibe-ic/programs/ir_drop_budget_check.py \
    <ir_report_or_dir> --vdd <V> --budget-pct 10
```

The command's 10 percent budget applies only when it is the actual original
requirement; it does not replace a stricter spec or PDK limit. Use each run's
native report paths and disclose every selected `FAIL` or `NOT_MEASURED` item
in the final report, along with any deferred obligation and its real risk.

## When to use

- Final 1–2 weeks before GDS release
- After the final ECO
- As a nightly regression item for any design in the "tapeout window"

## Checklist categories

The native tools and their existing readers supply the integer counts,
coverage and corner-slack comparisons below. Read the actual report and its
original requirement, then AI review the engineering meaning. File presence
is not a substitute for a measurement.

1. **Functional**
   - RTL regression 100% pass + coverage ≥ target (code/functional/assertion)
     — *enforced by* `programs/coverage_metric_check.py` (and the analog/
     state variants).
   - Formal properties all proven or bounded — *enforced by* `programs/
     assertion_property_check.py`.
   - LEC RTL↔netlist clean — *enforced by* `programs/lec_equivalence_check.py`.
2. **Timing**
   - STA setup/hold/recovery/removal + min-pulse-width / max-transition /
     max-cap clean across all MCMM corners — *enforced by* `programs/
     sta_report_check.py` (+ `programs/corner_coverage_audit.py` for MCMM
     completeness).
3. **Power integrity**
   - Static IR-drop < budget (typical 5–10% Vdd) — *enforced by* `programs/
     ir_drop_budget_check.py` (numeric `max_drop < pct·Vdd` gate; presence/
     authenticity by `programs/ir_drop_report_check.py`; hotspot causes by
     `programs/ir_drop_triage_classify.py`).
   - EM current density < library limit — *enforced by* `programs/
     em_report_check.py`.
4. **Physical**
   - DRC 0 errors (or waivers signed) — *enforced by* `programs/
     drc_report_check.py`.
   - LVS clean — *enforced by* `programs/lvs_report_check.py` /
     `programs/lvs_signoff_guard.py`.
   - Antenna DRC clean — *enforced by* `programs/antenna_report_check.py`.
   - Density rules clean (min/max metal density) — *enforced by* `programs/
     metal_fill_density_check.py`.
   - ERC clean — *enforced by* `programs/erc_density_check.py`.
5. **Test** (missing DFT data = `NOT_MEASURED`, not SKIP; the DFT signoff obligation remains failed) — FOUNDRY / ATE bar
   - Scan ATPG **stuck-at** coverage ≥ **foundry floor (95 %, up to 98 %)**;
     a lenient written target is clamped UP to the floor; **missing DFT
     report = FAIL** (the measurement remains `NOT_MEASURED`) — *enforced by* `programs/dft_atpg_coverage_check.py`
     (no SKIP path; recomputed, never a trusted self-asserted boolean).
   - **Transition (at-speed / launch-off-capture)** coverage ≥ target, OR a
     DOCUMENTED OSS-engine limitation (Fault is stuck-at-only — never a
     fabricated at-speed number) — *emitted by* `programs/fault_atpg_run.py`
     (`transition` block + `transition_atpg_plan.md`).
   - MBIST integrated/simulated + **boundary-scan BSDL present for a padded
     design** (bare core → honest N/A) — *emitted + gated by*
     `programs/bsdl_emit.py` (BSDL + boundary-scan-cell-per-pad plan).
   - The three roll up into `programs/dft_signoff_check.py` (aggregate DFT
     sign-off: stuck-at + transition + BSDL; absent evidence FAILs honestly).
6. **Power intent**
   - UPF consistency across synth / P&R / STA / sim
   - All isolation + level-shifter cells in place
7. **Documentation**
   - Pin list frozen; package / bond diagram matches pad ring; release notes,
     change log, waiver log complete — file-presence inventory *enforced by*
     `programs/tapeout_checklist_gen.py`.
8. **Release**
   - GDS stream-out (Calibre + KLayout), md5 checksum recorded, fab-specific
     deliverables bundled — inspect the native stream-out and existing
     `programs/foundry_handoff_package_check.py` results.
   - The md5 above ATTESTS one artefact — what this file was — and that is the
     right instrument for it. It is the WRONG instrument for comparing two
     runs. A GDSII stream stamps its own write time into every BGNLIB and
     BGNSTR record, so two stream-outs of one layout are never byte-equal:
     measured in the pinned image, one layout written twice 2.2 s apart differs
     in exactly six bytes, six of six inside a date field. To ask "did the
     layout change between these two runs", use
     `programs/gds_canonical_digest.py`, which zeroes those fields and hashes
     the rest. Comparing two GDS by md5/sha256 reports "not reproducible" every
     time, on any design, forever (vibe-ic#2221).

## Workflow

Read every applicable native result against its unchanged original limit.
The AI review then addresses the engineering facts those measurements leave
unresolved:

1. Assess whether any proposed mitigation is technically credible and its residual risk acceptable to the owner. A well-formed exception cannot establish that a failed measurement passed.
2. Route each failed or unmeasured obligation to its owning skill (`/sta-review`, `/drc-fix`, `/ir-drop-triage`, `/lvs-triage`, …) and resolve the cause in the design, local tool fork or existing producer.
3. Rerun the actual affected tool and review its new native result. Do not fabricate coverage or move an engineering limit.
4. Write the engineering recommendation using per-row position/name, native evidence, original limit, AI finding and remaining work. Current owner instructions govern any physical release or external handoff.

## Output format

- `tapeout/checklist.md` — the table above with status + evidence links
- `tapeout/waivers.md` — every waiver with owner, rationale, risk assessment
- `tapeout/release.md` — GDS release note

## Technical basis

Standard pre-tapeout flows at commercial foundries (TSMC, Samsung, GF) require this category of checklist. Open reference: Efabless tapeout docs for shuttle runs (https://efabless.com/).

### The open-MPW precheck driver, and why it is documented rather than wired

    programs/mpw_precheck_driver.py --input-directory <gds-dir> --pdk-root <pdk>

**READ THE PROGRAM'S OWN HEADER BEFORE TRUSTING A VERDICT FROM IT.** The
counterparty it addresses — the Efabless/chipIgnite open-MPW shuttle — CEASED
OPERATING IN 2025. It no longer accepts submissions and it no longer refuses
them. Nothing in the driver is broken; it is pointed at a party that stopped
answering, so a PASS from it means the local checks ran, never that a shuttle
accepted the design.

It is kept and named here rather than deleted or wired. Deleted, the next person
targeting a shuttle rebuilds it; wired into the flow, it would report a
submission verdict no counterparty stands behind. Documented, it is available to
whoever points it at a shuttle that is still answering.

## Handoff

- Any red item routes back to its owning skill (`/sta-review`, `/drc-fix`, etc.)
- After applicable native measurements meet their original limits, follow the owner's authorized GDS release workflow.
